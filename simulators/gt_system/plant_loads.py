"""
simulators.gt_system.plant_loads — plant electrical aux, IT/flow-driven.

Pumps are computed from the fluid each one moves  (P = Q·ΔP / η),
the dry-cooler fan rides a VSD (cube law on dry-cooler utilisation),
HVAC is the container-envelope cooling load, lights = lights_frac · HVAC.

GT auxiliaries are NOT here — they are an internal GT de-rate (GT net power).
"""
from __future__ import annotations


def _pump_kW(q_m3h: float, dp_bar: float, eta: float) -> float:
    if q_m3h <= 0 or dp_bar <= 0:
        return 0.0
    return (q_m3h / 3600.0) * (dp_bar * 1e5) / max(eta, 1e-3) / 1000.0


def plant_loads(solved, p) -> dict:
    """Itemised plant electrical (kW) from the solved flows + the head/η/HVAC
    parameters on GTSystemParams `p`. Returns {items, total, fan, hvac, lights, util}."""
    from nexablock.blocks import (GasTurbine, HRSG, LiBrChiller,
                                  DoubleEffectLiBrChiller, MED,
                                  GPUCassette, Radiator)

    def R(cls, label, default=0.0):
        for b in solved.blocks:
            if isinstance(b, cls) and label in b.results:
                return b.results[label].value
        return default

    g = lambda n, d: getattr(p, n, d)
    eta = g("pump_eta", 0.70)

    # ── flows (m³/h) ──────────────────────────────────────────────────────────
    q_diel  = R(GPUCassette, "Coolant vol flow m3/h")
    q_loop  = R(LiBrChiller, "Rejection loop flow")
    q_fw    = R(HRSG, "Feedwater flow m3/h")
    q_sw    = R(MED, "Seawater feed")
    q_brine = R(MED, "Brine reject")
    q_dist  = R(MED, "Water production m3/h")
    q_cond  = R(LiBrChiller, "Condensate flow m3/h")
    q_cool  = R(LiBrChiller, "Cooling capacity kW")

    # LiBr internal solution flow (screening): refrigerant = Q_cool / h_fg(~5°C),
    # solution = circulation-ratio × refrigerant.
    refrig_kgps = (q_cool * 1e3) / 2480e3
    q_libr_m3h  = g("libr_circ_ratio", 12.0) * refrig_kgps / 1500.0 * 3600.0
    _libr_pump  = _pump_kW(q_libr_m3h, g("dp_libr_bar", 2.0), eta)
    _is_de = any(isinstance(b, DoubleEffectLiBrChiller) for b in solved.blocks)

    # Pumps (ordered). A double-effect chiller has TWO solution circuits (a
    # high-temperature and a low-temperature generator), so its internal
    # pumping is itemised as HT + LT solution pumps instead of one.
    pumps = {"Dielectric coolant pump": _pump_kW(q_diel, g("dp_diel_bar", 3.0), eta)}
    if _is_de:
        pumps["LiBr HT solution pump"] = _libr_pump
        pumps["LiBr LT solution pump"] = _libr_pump
    else:
        pumps["LiBr chiller pump"] = _libr_pump
    pumps.update({
        "Cooling-loop pump":       _pump_kW(q_loop,  g("dp_loop_bar", 3.0), eta),
        "HRSG feed-water pump":    _pump_kW(q_fw,    g("dp_bfp_bar", 9.0), eta),
        "Seawater intake pump":    _pump_kW(q_sw,    g("dp_sw_bar", 2.0), eta),
        "MED feed pump":           _pump_kW(q_sw,    g("dp_med_feed_bar", 2.0), eta),
        "Brine pump":              _pump_kW(q_brine, g("dp_brine_bar", 2.0), eta),
        "Distillate pump":         _pump_kW(q_dist,  g("dp_dist_bar", 2.0), eta),
        "Condensate pump":         _pump_kW(q_cond,  g("dp_cond_bar", 2.0), eta),
    })
    pump_total = sum(pumps.values())

    # ── dry-cooler fan: VSD cube law on utilisation ───────────────────────────
    q_cond_kW = R(LiBrChiller, "Condenser duty")
    rad_duty  = R(Radiator, "Radiator duty")
    util = min(1.0, max(0.0, rad_duty / q_cond_kW if q_cond_kW > 0 else 0.0))
    fan  = g("fan_rated_frac", 0.015) * q_cond_kW * util ** 3

    # ── HVAC (container envelope) + lights ────────────────────────────────────
    it_kW  = R(GPUCassette, "IT power")
    n_cont = g("containers_per_MW", 3.0) * (it_kW / 1000.0)
    hvac   = max(0.0, n_cont * g("container_area_m2", 70.0) * g("container_U", 0.5)
                 * (g("t_ambient_C", 25.0) - g("container_inside_C", 27.0))) / 1000.0
    lights = g("lights_frac", 0.25) * hvac

    items = dict(pumps)
    items["Dry-cooler fan (VSD)"] = fan
    items["HVAC (containers)"]    = hvac
    items["Lights"]               = lights
    return {"items": items, "pumps": pumps, "pump_total": pump_total,
            "fan": fan, "hvac": hvac, "lights": lights,
            "n_containers": n_cont, "util": util, "total": sum(items.values())}
