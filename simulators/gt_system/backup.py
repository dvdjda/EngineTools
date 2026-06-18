"""
simulators.gt_system.backup — Tier-3 resilience KPIs for the Backup engine.

Computed from the solved operating point + the storage/UPS/accumulator inputs.
Steady-state can't draw the transient curve, but it sizes the buffers and
pass/fails the ride-through budget:
  • prime-mover fuel autonomy (diesel tank vs backup-hours target)
  • cooling-tower top-up duty + whether it can cool the dielectric at this wet-bulb
  • fresh-water buffer (MED banks it; tower make-up draws it)
  • UPS electrical ride-through (covers the diesel start?)
  • thermal accumulator ride-through (covers the tower/diesel ramp?)
"""
from __future__ import annotations

_DIESEL_MJ_PER_L = 36.0      # diesel LHV ~36 MJ/L
_H_FG = 2257.0               # kJ/kg evaporation
_DIESEL_START_S = 15.0       # fast-start genset to load
_TOWER_RAMP_S = 30.0         # fans/pumps to full
_UPS_TRANSFER_MS = 10.0      # online double-conversion, bumpless


def resilience(solved, p) -> dict:
    from nexablock.blocks import (GasTurbine, DieselGenset, LiBrChiller,
                                  GPUCassette, MED, Radiator)

    def R(cls, label, d=0.0):
        for b in solved.blocks:
            if isinstance(b, cls) and label in b.results:
                return b.results[label].value
        return d

    pm_block = next((b for b in solved.blocks if isinstance(b, GasTurbine)), None)
    on_diesel = isinstance(pm_block, DieselGenset)
    gpu_heat  = R(GPUCassette, "Heat load")                  # IT + cassette overhead
    it_kW     = R(GPUCassette, "IT power")
    libr_cool = 0.0 if getattr(p, "libr_failed", False) else R(LiBrChiller, "Cooling capacity kW")

    # ── cooling tower: top-up (or full, on LiBr failure) ──────────────────────
    tower_duty   = max(0.0, gpu_heat - libr_cool)            # what the tower must add
    tower_sup_C  = p.tower_wetbulb_C + p.tower_approach_K
    direct_ok    = tower_sup_C <= p.gpu_t_in_C + 1e-6        # can it cool dielectric to set-point?
    tower_fan_kW = 0.02 * tower_duty
    tower_makeup = (tower_duty / _H_FG) * 1.3 * 3.6          # m³/h evap + blowdown

    # ── prime-mover fuel autonomy ─────────────────────────────────────────────
    fuel_kW = R(GasTurbine, "Fuel energy input")
    if on_diesel:
        fuel_Lph  = fuel_kW * 3600.0 / (_DIESEL_MJ_PER_L * 1000.0)   # kW→L/h
        autonomy_h = (p.diesel_tank_m3 * 1000.0) / fuel_Lph if fuel_Lph > 0 else float("inf")
    else:
        fuel_Lph = 0.0
        autonomy_h = float("inf")                            # GT on gas, not the diesel tank

    # ── fresh-water buffer ────────────────────────────────────────────────────
    med_m3day   = R(MED, "Water production m3/day")
    draw_m3day  = tower_makeup * 24.0
    net_m3day   = med_m3day - draw_m3day                     # +ve fills the tank
    if net_m3day >= 0:
        water_days = float("inf")
    else:
        water_days = p.water_tank_m3 / (-net_m3day)

    # ── UPS electrical ride-through (IT + critical cooling pumps) ─────────────
    crit_kW   = it_kW + 0.10 * it_kW                          # IT + ~10% critical pumps
    ups_min   = (p.ups_kwh / crit_kW) * 60.0 if crit_kW > 0 else float("inf")

    # ── thermal accumulator ride-through ──────────────────────────────────────
    # usable energy = (accumulator + bare immersion inventory) × dielectric cp×ΔT
    diel_m3   = p.accumulator_m3 + p.dielectric_inventory_m3
    therm_MJ  = diel_m3 * p.coolant_rho * p.coolant_cp * max(1.0, p.gpu_t_out_C - p.gpu_t_in_C) / 1e6
    bridge_min = (therm_MJ * 1e3 / gpu_heat) / 60.0 if gpu_heat > 0 else float("inf")

    target_h  = p.backup_hours_target
    return {
        "on_diesel": on_diesel,
        "prime_mover": "Diesel genset" if on_diesel else "Gas turbine",
        "gpu_heat_kW": gpu_heat,
        "libr_cooling_kW": libr_cool,
        "tower_topup_kW": tower_duty,
        "tower_supply_C": tower_sup_C,
        "tower_direct_ok": direct_ok,
        "tower_fan_kW": tower_fan_kW,
        "tower_makeup_m3h": tower_makeup,
        "diesel_fuel_Lph": fuel_Lph,
        "diesel_autonomy_h": autonomy_h,
        "fuel_target_met": autonomy_h >= target_h,
        "med_water_m3day": med_m3day,
        "water_net_m3day": net_m3day,
        "water_buffer_days": water_days,
        "ups_ride_min": ups_min,
        "ups_covers_start": ups_min * 60.0 >= _DIESEL_START_S,
        "thermal_bridge_min": bridge_min,
        "thermal_covers_ramp": bridge_min * 60.0 >= max(_DIESEL_START_S, _TOWER_RAMP_S),
        "backup_hours_target": target_h,
    }
