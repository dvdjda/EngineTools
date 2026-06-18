"""
GT System v2 (double-effect + Backup) — Tier-3 resilience variant.

Copy of the double-effect engine with the standby architecture added:
  • a DIESEL genset that takes over as prime mover when the GT fails (its exhaust
    still drives the double-effect chiller; the cooling tower covers the rest);
  • a WET COOLING TOWER in place of the dry radiator (normal reject + top-up, and
    full GPU cooling if the LiBr fails);
  • storage (diesel fuel, fresh water), a UPS battery (electrical ride-through)
    and a thermal accumulator (cooling ride-through), surfaced as resilience KPIs;
  • GT-failure and LiBr-failure switches to simulate each contingency.

Status: trusted — promoted by David. Resilience KPIs stay screening-basis
(design-sizing estimates). Does NOT touch the other engines.
"""
from __future__ import annotations

from nexa_toolkit.framework.contract import InputSpec, OutputSpec, register
from simulators.gt_system.system      import build_gt_system, summary
from simulators.gt_system.feasibility import feasibility
from simulators.gt_system.audit        import gt_system_audit_checks
from simulators.gt_system.backup        import resilience
from nexablock.audit                   import audit

from .gt_system_v2_de import GTSystemV2DE, _params_double

_FAIL = {0: False, 1: True}

# The wet cooling tower supersedes the dry radiator, so its two design knobs are
# dropped from the Backup engine's inputs (the cooling-tower wet-bulb/approach/fan
# replace them). Module-level so the class-body comprehension can see it.
_DROP_RADIATOR = {"radiator_approach_K", "fan_rated_frac"}


@register
class GTSystemV2DEBackup(GTSystemV2DE):
    key        = "gt_system_v2_de_backup"
    name       = "GT System v2 — nexablock (GT + HRSG + 2xLiBr + GPU + MED + Backup)"
    kind       = "simulator"
    status     = "trusted"   # promoted by David
    provenance = ("Copy of gt_system_v2_de with the Tier-3 backup architecture: "
                  "diesel standby genset, wet cooling tower (replacing the dry "
                  "radiator), diesel/water storage, UPS + thermal accumulator "
                  "ride-through KPIs, and GT/LiBr failure switches. David's spec. "
                  "Promoted to trusted by David.")
    notes = (
        "Double-effect engine + standby. Switches simulate a GT trip (→ diesel "
        "genset powers IT and drives the LiBr via its exhaust; the cooling tower "
        "covers the cooling balance) and a LiBr trip (→ cooling tower carries the "
        "full GPU cooling, scaled to wet-bulb). The wet cooling tower replaces the "
        "dry radiator. Resilience KPIs size the diesel fuel / water storage and "
        "the UPS + thermal-accumulator ride-through against a backup-hours target. "
        "Screening, pre-verification."
    )
    chart_format = "svg"

    inputs = [i for i in GTSystemV2DE.inputs if i.key not in _DROP_RADIATOR] + [
        InputSpec("gt_status",   "GT status", "-", 0, 0, 1,
                  choices={"Normal": 0, "Failed → diesel": 1}),
        InputSpec("libr_status", "LiBr status", "-", 0, 0, 1,
                  choices={"Normal": 0, "Failed → cooling tower": 1}),
        InputSpec("diesel_rated_kW", "Diesel genset rating",      "kW", 1500.0, 200, 50_000),
        InputSpec("diesel_eff",      "Diesel efficiency",         "-",  0.40, 0.30, 0.48),
        InputSpec("diesel_exhaust_C","Diesel exhaust temp",       "°C", 480.0, 350, 600),
        InputSpec("tower_wetbulb_C", "Cooling-tower wet-bulb",    "°C", 25.0, 5, 35),
        InputSpec("tower_approach_K","Cooling-tower approach",    "K",  5.0, 2, 12),
        InputSpec("diesel_tank_m3",  "Diesel fuel storage",       "m³", 25.0, 1, 500),
        InputSpec("water_tank_m3",   "Backup water storage",      "m³", 250.0, 10, 5000),
        InputSpec("backup_hours_target", "Backup autonomy target","h",  72.0, 1, 720),
        InputSpec("ups_kwh",         "UPS battery (usable)",      "kWh", 150.0, 10, 5000),
        InputSpec("accumulator_m3",  "Cooling accumulator",       "m³", 15.0, 0, 500),
    ]

    def solve(self, v: dict) -> dict:
        p = _params_double(v)                       # double-effect base
        p.heat_reject       = "tower"               # wet cooling tower, not radiator
        p.gt_failed         = _FAIL.get(int(v.get("gt_status", 0)), False)
        p.libr_failed       = _FAIL.get(int(v.get("libr_status", 0)), False)
        p.diesel_rated_kW   = float(v.get("diesel_rated_kW", 1500.0))
        p.diesel_eff        = float(v.get("diesel_eff", 0.40))
        p.diesel_exhaust_C  = float(v.get("diesel_exhaust_C", 480.0))
        p.tower_wetbulb_C   = float(v.get("tower_wetbulb_C", 25.0))
        p.tower_approach_K  = float(v.get("tower_approach_K", 5.0))
        p.diesel_tank_m3    = float(v.get("diesel_tank_m3", 25.0))
        p.water_tank_m3     = float(v.get("water_tank_m3", 250.0))
        p.backup_hours_target = float(v.get("backup_hours_target", 72.0))
        p.ups_kwh           = float(v.get("ups_kwh", 150.0))
        p.accumulator_m3    = float(v.get("accumulator_m3", 15.0))
        solved = build_gt_system(p)
        return {
            "solved":      solved,
            "kpis":        summary(solved),
            "feasibility": feasibility(solved, bop_frac=p.bop_frac),
            "audit":       audit(solved,
                                  extra_checks=gt_system_audit_checks(
                                      solved, bop_frac=p.bop_frac)),
            "resilience":  resilience(solved, p),
            "inputs":      dict(v),
        }

    def outputs(self, r: dict) -> list:
        rows = super().outputs(r)
        b = r.get("resilience")
        if b is None:
            return rows
        ok = lambda flag: " ✓" if flag else " ✗"
        # Prime mover is surfaced on the PFD (backup note) and via GT actual power;
        # the stray "= … — 0" divider row was dropped (it read like a 0-value metric).
        # The cooling-tower fan is already itemised in the plant-aux block above.
        rows += [
            OutputSpec("Cooling-tower top-up duty", b["tower_topup_kW"], "kW", "screening", "{:.0f}"),
            OutputSpec(f"Tower supply temp (direct cool{ok(b['tower_direct_ok'])})",
                       b["tower_supply_C"], "°C", "screening", "{:.0f}"),
            OutputSpec("Tower make-up water", b["tower_makeup_m3h"], "m³/h", "screening", "{:.1f}"),
            OutputSpec(f"Diesel fuel autonomy (target {b['backup_hours_target']:.0f} h{ok(b['fuel_target_met'])})",
                       b["diesel_autonomy_h"], "h", "screening", "{:.0f}"),
            OutputSpec("Fresh-water buffer", b["water_buffer_days"], "days", "screening", "{:.1f}"),
            OutputSpec(f"UPS ride-through (covers diesel start{ok(b['ups_covers_start'])})",
                       b["ups_ride_min"], "min", "screening", "{:.1f}"),
            OutputSpec(f"Thermal accumulator bridge (covers ramp{ok(b['thermal_covers_ramp'])})",
                       b["thermal_bridge_min"], "min", "screening", "{:.1f}"),
        ]
        return rows
