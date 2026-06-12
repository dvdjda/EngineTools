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
    derate   = max(0.50, 1.0 - 0.007 * max(0.0, t_amb_K - 288.15))
    p_derate = p.p_rated_kW * derate                         # kW
    p_gt     = p_derate * load_pct / 100.0
    fuel_kW  = p_gt / max(p.gt_eff, 1e-6)
    waste_kW = fuel_kW - p_gt
    exh_kW   = waste_kW * _EXH_FRAC
    hrsg_kW  = exh_kW * (p.hrsg_eff_pct / 100.0)

    p_st_Pa  = p.steam_p_bar * 1e5
    fw_K     = p.fw_t_C + 273.15
    t_sat    = _props.t_sat(p_st_Pa)
    t_steam  = t_sat + 30.0                                   # 30°C superheat
    h_st     = _props.h_steam(p_st_Pa, t_steam)
    h_fw     = _props.h_water(p_st_Pa, fw_K)
    dh       = max(h_st - h_fw, 1.0)
    return hrsg_kW * 1000.0 / dh                              # kg/s


_CTRL_SAFETY = 1.03    # 3% headroom so controller-vs-block model differences
                       # don't leave the block actually short of cooling
                       # (small enthalpy approximation mismatches accumulate)


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


def _aux_loads_kW(p, load_pct: float, libr_frac: float,
                  total_steam_kgps: float, gpu_heat_kW: float) -> dict:
    """Per-block aux electrical at the given load_pct + libr_frac. Mirrors
    the block-level formulas so the controller's setpoint matches what the
    real solve will see."""
    derate    = max(0.50, 1.0 - 0.007 * max(0.0, (p.t_ambient_C + 273.15) - 288.15))
    p_derate  = p.p_rated_kW * derate
    p_gt      = p_derate * load_pct / 100.0
    gt_aux    = p.gt_aux_frac * p_derate
    bop_aux   = p.bop_frac    * p_gt
    # Cooling chain
    q_cool    = gpu_heat_kW                                  # LiBr-priority delivers exactly this
    libr_aux  = p.libr_pump_frac * q_cool
    q_cond    = q_cool * (1.0 + p.libr_cop) / max(p.libr_cop, 1e-6)
    ct_aux    = p.ct_fan_frac    * q_cond
    # MED — residual steam
    med_steam_kgps = max(0.0, (1.0 - libr_frac) * total_steam_kgps)
    gor       = 0.8 * p.med_effects
    mdot_dist = med_steam_kgps * gor                          # kg/s
    m3pd      = mdot_dist * 86400.0 / 1000.0
    med_aux   = 1.5 * m3pd / 24.0                             # kWh/m³ × m³/h
    return {
        "gpu_kW":   gpu_heat_kW,                              # GPU electrical = GPU heat (immersion)
        "med":      med_aux,
        "libr":     libr_aux,
        "ct":       ct_aux,
        "gt_aux":   gt_aux,
        "bop":      bop_aux,
    }


def control_setpoints(p, max_iter: int = 8,
                      tol: float = 0.5) -> ControlSetpoints:
    """Resolve load_pct and libr_frac under the configured modes.

    p is a GTSystemParams. Returns ControlSetpoints with the final
    resolved values plus diagnostic context.
    """
    gpu_heat_kW = p.gpu_it_kW * p.gpu_pue                     # immersion: all elec → heat
    t_amb_K     = p.t_ambient_C + 273.15
    derate      = max(0.50, 1.0 - 0.007 * max(0.0, t_amb_K - 288.15))
    p_derate    = p.p_rated_kW * derate

    # Steam demand for LiBr-priority cooling — invariant to load_pct.
    libr_steam_kgps = _libr_steam_demand_kgps(p, gpu_heat_kW)

    # Pre-compute steam at 100% load (no plant-aux dependence here).
    steam_at_100 = _hrsg_steam_kgps(p, 100.0, t_amb_K)
    required_load_for_steam_pct = (libr_steam_kgps / max(steam_at_100, 1e-9)) * 100.0

    # Iterate: aux loads depend on load_pct/libr_frac, which depend on aux.
    load_pct  = p.load_pct  if p.gt_power_mode   == "manual" else 85.0
    libr_frac = p.libr_frac if p.steam_split_mode == "manual" else 0.5
    last_load = -1.0
    iters = 0
    for iters in range(1, max_iter + 1):
        total_steam = _hrsg_steam_kgps(p, load_pct, t_amb_K)
        aux = _aux_loads_kW(p, load_pct, libr_frac, total_steam, gpu_heat_kW)
        # Electrical demand (NEXA + island external)
        elec_demand = (gpu_heat_kW + aux["med"] + aux["libr"]
                       + aux["ct"] + aux["gt_aux"] + aux["bop"])
        if p.operating_mode == "island":
            elec_demand += p.external_load_kW
        required_load_for_elec_pct = elec_demand / max(p_derate, 1e-9) * 100.0

        # Resolve modes
        new_load = load_pct
        if p.gt_power_mode == "auto":
            if p.operating_mode == "island":
                new_load = min(required_load_for_elec_pct, 100.0)
            else:  # grid_tied
                new_load = min(max(required_load_for_elec_pct,
                                    required_load_for_steam_pct), 100.0)

        new_libr = libr_frac
        if p.steam_split_mode == "auto":
            new_total_steam = _hrsg_steam_kgps(p, new_load, t_amb_K)
            new_libr = min(libr_steam_kgps / max(new_total_steam, 1e-9), 1.0)

        if (abs(new_load - load_pct) < tol
                and abs(new_libr - libr_frac) < 1e-4):
            load_pct, libr_frac = new_load, new_libr
            break
        load_pct, libr_frac = new_load, new_libr

    # Grid export = supply − all NEXA demand (positive only).
    final_total_steam = _hrsg_steam_kgps(p, load_pct, t_amb_K)
    final_aux = _aux_loads_kW(p, load_pct, libr_frac, final_total_steam, gpu_heat_kW)
    p_gt_kW = p_derate * load_pct / 100.0
    nexa_demand = (gpu_heat_kW + final_aux["med"] + final_aux["libr"]
                   + final_aux["ct"] + final_aux["gt_aux"] + final_aux["bop"])
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
        derived_libr_frac=(p.steam_split_mode == "auto"),
        required_load_for_elec_pct=required_load_for_elec_pct,
        required_load_for_steam_pct=required_load_for_steam_pct,
        iterations=iters,
    )
