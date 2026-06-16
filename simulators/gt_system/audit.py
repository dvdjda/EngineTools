"""
simulators.gt_system.audit — composition-level audit checks for the GT system.

These complement the per-block checks declared in each block's
audit_checks(). They cover invariants that only make sense across the
whole composition or that depend on the resolved control modes
(island vs grid, auto vs manual).
"""
from __future__ import annotations

from nexablock.audit import energy_balance, pass_fail, bounds_check
from nexablock.blocks import GasTurbine, GPUCassette, MED, LiBrChiller, Radiator


def _first(solved, cls):
    return next((b for b in solved.blocks if isinstance(b, cls)), None)


def _read(block, label):
    if block is None: return 0.0
    res = block.results.get(label)
    return res.value if res is not None else 0.0


def gt_system_audit_checks(solved, bop_frac: float = 0.010) -> list:
    """Return the GT-system composition checks. Pass via audit(solved,
    extra_checks=gt_system_audit_checks(solved, bop_frac=...))."""
    gt   = _first(solved, GasTurbine)
    gpu  = _first(solved, GPUCassette)
    med  = _first(solved, MED)
    libr = _first(solved, LiBrChiller)
    ct   = _first(solved, Radiator)

    cs = getattr(solved, "control", None)
    operating_mode = getattr(solved, "operating_mode", "island")

    # Aggregate demand at the actual operating point — mirrors feasibility.
    actual_kW   = _read(gt, "GT actual power")
    silicon_kW  = _read(gpu, "IT power")
    overhead_kW = _read(gpu, "Cassette overhead electrical")
    med_aux_kW  = _read(med,  "MED electrical")
    libr_aux_kW = _read(libr, "LiBr pump electrical")
    ct_aux_kW   = _read(ct,   "Radiator fan electrical")
    gt_aux_kW   = _read(gt,   "GT aux electrical")
    bop_aux_kW  = max(0.0, bop_frac) * actual_kW
    nexa_demand = (silicon_kW + overhead_kW + med_aux_kW + libr_aux_kW
                   + ct_aux_kW + gt_aux_kW + bop_aux_kW)

    external_load = cs.external_load_kW if cs is not None else 0.0
    grid_export   = cs.grid_export_kW   if cs is not None else 0.0

    checks: list = []

    # E9: Bus closure — supply = NEXA demand + (island: external_load OR grid: export)
    if operating_mode == "island":
        supply_side = actual_kW
        demand_side = nexa_demand + external_load
        name = "E9: bus closure (island) — supply = NEXA + external"
    else:
        supply_side = actual_kW
        demand_side = nexa_demand + grid_export
        name = "E9: bus closure (grid) — supply = NEXA + grid export"
    checks.append(energy_balance(
        name=name, supply=supply_side, demand=demand_side,
        affects=["GT actual power"], tol_rel=5e-2))

    # F1: island mode — supply must meet all demand without grid backstop
    if operating_mode == "island":
        checks.append(pass_fail(
            "F1: island power balance closed without grid import",
            passed=actual_kW + 1.0 >= nexa_demand + external_load,
            detail=f"supply {actual_kW:.0f} kW ≥ NEXA+external "
                   f"({nexa_demand + external_load:.0f}) kW",
            category="Plausibility", affects=["GT actual power"],
        ))

    # F2: external load finite and ≥ 0
    import math
    finite_nonneg = math.isfinite(external_load) and external_load >= 0
    checks.append(pass_fail(
        "F2: external load finite and non-negative",
        passed=finite_nonneg,
        detail=f"external_load = {external_load:.0f} kW (island only; grid mode forces 0)",
        category="Plausibility", affects=[],   # generic — flags whole system if bad
    ))

    # F3: auto GT — derived load_pct ≤ 100%
    if cs is not None and cs.derived_load_pct:
        checks.append(bounds_check(
            "F3: derived GT load_pct ≤ 100% (auto)",
            value=cs.load_pct, lo=0.0, hi=100.0, unit="%",
            affects=["GT actual power"],
        ))

    # F4: auto split — derived libr_frac ∈ [0, 1]
    if cs is not None and cs.derived_libr_frac:
        checks.append(bounds_check(
            "F4: derived libr_frac in [0, 1] (auto)",
            value=cs.libr_frac, lo=0.0, hi=1.0, unit="-",
            affects=["LiBr cooling capacity"],
        ))

    # F5: grid mode — grid_export ≥ 0 (no imports)
    if operating_mode == "grid_tied":
        checks.append(pass_fail(
            "F5: grid export ≥ 0 (imports forbidden)",
            passed=grid_export >= 0.0,
            detail=f"grid_export = {grid_export:+.0f} kW",
            category="Plausibility", affects=["GT actual power"],
        ))

    return checks
