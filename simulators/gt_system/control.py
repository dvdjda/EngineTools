"""
simulators.gt_system.control — resolve load_pct and libr_frac per mode.

GPU drives the system: it dumps heat and pulls electrical. GT follows
GPU + plant aux + (island only) external load. MED is a residual steam
balancer.

Island vs grid-tied:
  Island  — load_pct capped by the ELECTRICAL demand. We never ramp the
            GT past where its power has a home (no grid backstop). If
            steam at that load isn't enough to cool GPU → cooling deficit
            surfaces in feasibility/audit.
  Grid    — load_pct can ramp higher to satisfy the cooling-driven steam
            requirement; surplus power exports to grid. Imports are
            forbidden — if GT can't supply demand even at 100% derated,
            it's infeasible.

libr_frac (LiBr-priority):
  steam_to_libr_required = GPU_heat / (libr_cop · Δh_steam_to_cond)
  libr_frac = min(steam_to_libr_required / total_steam, 1.0)
  MED takes (1 − libr_frac) — pure residual.

The aux loads depend on load_pct and libr_frac themselves, so this is a
small fixed-point iteration. Converges in 2–4 iterations at screening
fidelity.
"""
from __future__ import annotations
from dataclasses import dataclass

from nexablock.core import props as _props


_NG_LHV   = 50_050e3     # J/kg
_EXH_FRAC = 0.85         # exhaust share of waste heat (matches GasTurbine block)


def active_pm(p) -> dict:
    """The active prime mover: the GT in normal operation, or the diesel genset
    when the GT has failed (Backup engine). Single source of truth for rating /
    efficiency / exhaust / de-rate, shared by the controller and build_gt_system."""
    if getattr(p, "gt_failed", False):
        return dict(is_diesel=True, label="Diesel Genset",
                    rated_kW=p.diesel_rated_kW, eff=p.diesel_eff,
                    exhaust_C=p.diesel_exhaust_C, exh_frac=p.diesel_exh_frac,
                    slope=0.003, ref_C=25.0, floor=0.80)
    return dict(is_diesel=False, label="Gas Turbine",
                rated_kW=p.p_rated_kW, eff=p.gt_eff,
                exhaust_C=p.t_exhaust_C, exh_frac=_EXH_FRAC,
                slope=0.007, ref_C=15.0, floor=0.50)


def _pm_derate(p, t_amb_K: float) -> float:
    pm = active_pm(p)
    return max(pm["floor"], 1.0 - pm["slope"] * max(0.0, t_amb_K - (pm["ref_C"] + 273.15)))


def med_loop_cold_C(p) -> float:
    """The temperature MED cools the captured loop branch down to.
    Manual: the HRSG return set-point (fw_t_C) — MED never over-cools.
    Auto:   MED's real cold-end (seawater + pinch), which is below the set-point,
            so the bypass has to hold the return up to fw_t_C."""
    if getattr(p, "med_bypass_mode", "manual") == "auto":
        return p.sw_t_C + getattr(p, "med_cold_pinch_K", 15.0)
    return p.fw_t_C


def med_bypass_fraction(p) -> float:
    """Resolved MED 3-way bypass. Manual: the user value. Auto: the fraction
    that, blending the MED-cooled branch (at the cold-end) with the bypassed hot
    branch (at the LiBr rejection temp), brings the loop back to the HRSG return
    set-point fw_t_C — so the feedwater inlet holds set-point and the radiator
    idles. Prioritises MED capture (water); opens only as far as needed."""
    if getattr(p, "med_bypass_mode", "manual") != "auto":
        return min(1.0, max(0.0, p.med_bypass_frac))
    t_cold = med_loop_cold_C(p)
    denom  = max(1.0, p.libr_reject_t_C - t_cold)
    return min(1.0, max(0.0, (p.fw_t_C - t_cold) / denom))


@dataclass
class ControlSetpoints:
    """Resolved control variables + diagnostic context."""
    load_pct:              float            # final GT load setpoint
    libr_frac:             float            # final steam split to LiBr
    external_load_kW:      float            # island: user input;  grid: 0.0
    grid_export_kW:        float            # grid: derived excess; island: 0.0
    derived_load_pct:      bool             # True if auto-resolved (not user input)
    derived_libr_frac:     bool             # True if auto-resolved (not user input)
    required_load_for_elec_pct:  float      # diagnostic
    required_load_for_steam_pct: float      # diagnostic
    iterations:            int


def _hrsg_steam_kgps(p, load_pct: float, t_amb_K: float) -> float:
    """Analytical: HRSG steam mass flow at the given load_pct.
    Mirrors GasTurbine + HRSG block physics so the pre-solve guess is
    consistent with what the solver will compute."""
    pm       = active_pm(p)
    derate   = _pm_derate(p, t_amb_K)
    p_derate = pm["rated_kW"] * derate                       # kW
    p_gt     = p_derate * load_pct / 100.0
    fuel_kW  = p_gt / max(pm["eff"], 1e-6)
    waste_kW = fuel_kW - p_gt
    exh_kW   = waste_kW * pm["exh_frac"]
    hrsg_kW  = exh_kW * (p.hrsg_eff_pct / 100.0)

    p_st_Pa  = p.steam_p_bar * 1e5
    fw_K     = p.fw_t_C + 273.15
    t_sat    = _props.t_sat(p_st_Pa)
    t_steam  = t_sat + 30.0                                   # 30°C superheat
    h_st     = _props.h_steam(p_st_Pa, t_steam)
    h_fw     = _props.h_water(p_st_Pa, fw_K)
    dh       = max(h_st - h_fw, 1.0)
    return hrsg_kW * 1000.0 / dh                              # kg/s


_CTRL_SAFETY = 1.00    # No hidden safety margin on the controller side.
                       # The controller targets exactly what's needed. Small
                       # block-vs-analytical mismatches (~0.5%) are absorbed
                       # by the SCREENING TOLERANCE on the cooling balance
                       # and M7 audit check — see SCREENING_TOL_COOLING below
                       # and the corresponding mass-balance tolerance in the
                       # GPUCassette M7 check.
                       #
                       # Rationale: a hidden controller margin that only works
                       # in grid mode (where the GT can ramp for steam) was
                       # misleading. In island mode the GT is electrically
                       # pinned and the margin can't be applied. Surface real
                       # deficits as real, treat sub-1% rounding-level gaps as
                       # OK within screening fidelity.


def _libr_steam_demand_kgps(p, gpu_heat_kW: float) -> float:
    """Steam mass flow LiBr needs to cool GPU heat at this COP / Δh,
    with a small safety margin so the block-level solve actually closes."""
    p_atm    = 101325.0
    p_st_Pa  = p.steam_p_bar * 1e5
    t_sat    = _props.t_sat(p_st_Pa)
    t_steam  = t_sat + 30.0
    h_st     = _props.h_steam(p_st_Pa, t_steam)
    h_cond   = _props.h_sat_liq(p_atm)
    dh_libr  = max(h_st - h_cond, 1.0)
    q_cool_W = gpu_heat_kW * 1000.0 * _CTRL_SAFETY
    q_gen_W  = q_cool_W / max(p.libr_cop, 1e-6)
    return q_gen_W / dh_libr                                 # kg/s


def _pump_kW(q_m3h: float, dp_bar: float, eta: float) -> float:
    if q_m3h <= 0 or dp_bar <= 0:
        return 0.0
    return (q_m3h / 3600.0) * (dp_bar * 1e5) / max(eta, 1e-3) / 1000.0


def _aux_loads_kW(p, load_pct: float,
                  total_steam_kgps: float, gpu_heat_kW: float) -> dict:
    """Plant electrical aux at the given load_pct — the analytical mirror of
    `plant_loads.plant_loads` (pumps P=Q·ΔP/η, VSD fan, container HVAC, lights),
    so the controller's setpoint matches what the real solve will compute.
    GT aux is the internal GT de-rate (kept separate). No steam splitter — all
    steam → LiBr; MED is rejection-driven."""
    derate   = _pm_derate(p, p.t_ambient_C + 273.15)
    p_derate = active_pm(p)["rated_kW"] * derate
    gt_aux   = p.gt_aux_frac * p_derate
    eta      = p.pump_eta

    # Cooling chain — LiBr delivers ~GPU heat; rejection = Q_cond.
    q_cool = gpu_heat_kW
    q_cond = q_cool * (1.0 + p.libr_cop) / max(p.libr_cop, 1e-6)
    f      = med_bypass_fraction(p)

    # ── flows (m³/h), mirroring the block formulas ────────────────────────────
    cp_w    = 4187.0
    dt_diel = max(0.1, p.gpu_t_out_C - p.gpu_t_in_C)
    q_diel  = gpu_heat_kW * 1e3 / (p.coolant_cp * dt_diel) / p.coolant_rho * 3600.0
    loop_dt = max(1.0, p.libr_reject_t_C - p.fw_t_C)
    q_loop  = (q_cond * 1e3 / (cp_w * loop_dt)) / 1000.0 * 3600.0
    q_fw    = total_steam_kgps * 3.6
    refrig  = q_cool * 1e3 / 2480e3                          # LiBr refrigerant kg/s
    q_libr  = p.libr_circ_ratio * refrig / 1500.0 * 3600.0
    gor       = 0.8 * p.med_effects
    h_fg      = 2257.0                                       # kJ/kg
    q_med_kW  = (1.0 - f) * q_cond
    mdot_dist = gor * q_med_kW / h_fg                        # kg/s
    mdot_sw   = mdot_dist / 0.35                             # MED recovery 35%
    mdot_br   = mdot_sw - mdot_dist
    q_dist, q_sw, q_br = mdot_dist * 3.6, mdot_sw * 3.6, mdot_br * 3.6

    pumps = (_pump_kW(q_diel, p.dp_diel_bar, eta)
             + _pump_kW(q_libr, p.dp_libr_bar, eta)
             + _pump_kW(q_loop, p.dp_loop_bar, eta)
             + _pump_kW(q_fw,   p.dp_bfp_bar, eta)
             + _pump_kW(q_sw,   p.dp_sw_bar, eta)
             + _pump_kW(q_sw,   p.dp_med_feed_bar, eta)
             + _pump_kW(q_br,   p.dp_brine_bar, eta)
             + _pump_kW(q_dist, p.dp_dist_bar, eta)
             + _pump_kW(q_fw,   p.dp_cond_bar, eta))         # condensate ≈ steam mass

    # Heat-reject fan. Dry cooler: VSD cube law on radiator utilisation ≈ bypassed
    # share. Wet cooling tower (Backup engine): the fan rides the loop-trim reject
    # PLUS the GPU cooling the tower carries directly (top-up when the LiBr is
    # steam-short on the diesel, or the full GPU heat when the LiBr has tripped).
    # Mirrors plant_loads so the GT-load setpoint accounts for it and the bus closes.
    if getattr(p, "heat_reject", "radiator") == "tower":
        if getattr(p, "libr_failed", False):
            libr_cool = 0.0
        else:
            p_atm   = 101325.0
            p_st_Pa = p.steam_p_bar * 1e5
            t_steam = _props.t_sat(p_st_Pa) + 30.0
            dh_libr = max(_props.h_steam(p_st_Pa, t_steam) - _props.h_sat_liq(p_atm), 1.0)
            steam_to_libr = total_steam_kgps                     # all steam → LiBr (no split here)
            libr_cool = min(gpu_heat_kW, p.libr_cop * steam_to_libr * dh_libr / 1e3)
        topup = max(0.0, gpu_heat_kW - libr_cool)
        fan   = 0.02 * (q_cond * f ** 3 + topup)                 # _TOWER_FAN_FRAC
    else:
        fan = p.fan_rated_frac * q_cond * f ** 3
    # Container-envelope HVAC + lights (IT/ambient driven).
    n_cont = p.containers_per_MW * (p.gpu_it_kW / 1000.0)
    hvac   = max(0.0, n_cont * p.container_area_m2 * p.container_U
                 * (p.t_ambient_C - p.container_inside_C)) / 1000.0
    lights = p.lights_frac * hvac

    return {
        "gpu_kW": gpu_heat_kW,          # GPU electrical = GPU heat (immersion)
        "plant":  pumps + fan + hvac + lights,
        "gt_aux": gt_aux,
    }


def control_setpoints(p, max_iter: int = 8,
                      tol: float = 0.5) -> ControlSetpoints:
    """Resolve load_pct and libr_frac under the configured modes.

    p is a GTSystemParams. Returns ControlSetpoints with the final
    resolved values plus diagnostic context.
    """
    gpu_heat_kW = p.gpu_it_kW * p.cassette_pue                # immersion: all elec → heat
    t_amb_K     = p.t_ambient_C + 273.15
    derate      = _pm_derate(p, t_amb_K)
    p_derate    = active_pm(p)["rated_kW"] * derate

    # Steam demand for LiBr-priority cooling — invariant to load_pct.
    libr_steam_kgps = _libr_steam_demand_kgps(p, gpu_heat_kW)

    # Pre-compute steam at 100% load (no plant-aux dependence here).
    steam_at_100 = _hrsg_steam_kgps(p, 100.0, t_amb_K)
    required_load_for_steam_pct = (libr_steam_kgps / max(steam_at_100, 1e-9)) * 100.0

    # Iterate: aux loads depend on load_pct, which depends on aux.
    load_pct  = p.load_pct if p.gt_power_mode == "manual" else 85.0
    libr_frac = 1.0        # no splitter — all steam → LiBr
    iters = 0
    for iters in range(1, max_iter + 1):
        total_steam = _hrsg_steam_kgps(p, load_pct, t_amb_K)
        aux = _aux_loads_kW(p, load_pct, total_steam, gpu_heat_kW)
        # Electrical demand (NEXA + island external). Gross GT must cover the
        # bus (GPU + plant aux) PLUS the GT's own aux derate, so net = bus.
        elec_demand = aux["gpu_kW"] + aux["plant"] + aux["gt_aux"]
        if p.operating_mode == "island":
            elec_demand += p.external_load_kW
        required_load_for_elec_pct = elec_demand / max(p_derate, 1e-9) * 100.0

        new_load = load_pct
        if p.gt_power_mode == "auto":
            if p.operating_mode == "island":
                new_load = min(required_load_for_elec_pct, 100.0)
            else:  # grid_tied — also ensure enough steam for full cooling
                new_load = min(max(required_load_for_elec_pct,
                                    required_load_for_steam_pct), 100.0)

        if abs(new_load - load_pct) < tol:
            load_pct = new_load
            break
        load_pct = new_load

    # Grid export = supply − all NEXA demand (positive only).
    final_total_steam = _hrsg_steam_kgps(p, load_pct, t_amb_K)
    final_aux = _aux_loads_kW(p, load_pct, final_total_steam, gpu_heat_kW)

    # LiBr-priority steam split: when enabled, feed the chiller only the steam it
    # needs to cool the GPU; the surplus goes to the calorifier → MED. When the
    # chiller is cooling-limited (demand ≥ available) the fraction saturates at 1
    # and the calorifier idles. Off (default): all steam → LiBr (frac = 1).
    derived_libr = p.steam_split_mode == "auto"
    if derived_libr:
        libr_frac = min(1.0, libr_steam_kgps / max(final_total_steam, 1e-9))
    p_gt_kW = p_derate * load_pct / 100.0
    nexa_demand = final_aux["gpu_kW"] + final_aux["plant"] + final_aux["gt_aux"]
    if p.operating_mode == "grid_tied":
        grid_export = max(0.0, p_gt_kW - nexa_demand)
        external_load = 0.0           # no manual external load in grid mode
    else:
        grid_export   = 0.0
        external_load = p.external_load_kW

    return ControlSetpoints(
        load_pct=load_pct,
        libr_frac=libr_frac,
        external_load_kW=external_load,
        grid_export_kW=grid_export,
        derived_load_pct=(p.gt_power_mode == "auto"),
        derived_libr_frac=derived_libr,
        required_load_for_elec_pct=required_load_for_elec_pct,
        required_load_for_steam_pct=required_load_for_steam_pct,
        iterations=iters,
    )
