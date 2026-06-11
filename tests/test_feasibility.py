"""
tests/test_feasibility.py — system-level power balance check.

Strictly separate from solver convergence. A converging solve can still
fail feasibility (the GT can't power its own load); they're independent
status objects that must both be green for a "trustful" screening.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import nexa_toolkit.engines                                  # noqa: registers
from nexa_toolkit.framework import get
from simulators.gt_system.system        import GTSystemParams, build_gt_system
from simulators.gt_system.feasibility   import power_balance, FeasibilityStatus


@pytest.fixture(scope="module")
def engine():
    return get("gt_system_v2")


# ── physics at default inputs (feasible) ─────────────────────────────────────

def test_default_inputs_are_feasible(engine):
    v = engine.defaults()                                 # gpu_it_kW = 5000
    r = engine.solve(v)
    f = r["feasibility"]
    assert isinstance(f, FeasibilityStatus)
    assert f.feasible
    assert f.shortfall_kW == 0
    assert f.generation_kW > 7000
    assert f.demand_kW > 5000
    assert f.balance_kW > 0


# ── physics at deficit inputs (high GPU load) ────────────────────────────────

def test_high_gpu_load_reports_deficit(engine):
    """gpu_it_kW = 10000, PUE = 1.05 → GPU draw ≈ 10500 kW. Plus itemised
    aux (MED + LiBr pump + CT fan + GT aux + BoP ≈ 430 kW) brings demand
    to ~10930 kW. GT supplies ~7905 kW → shortfall ≈ 3000 kW (±150)."""
    v = engine.defaults(); v["gpu_it_kW"] = 10000.0
    r = engine.solve(v)
    f = r["feasibility"]
    assert not f.feasible
    assert f.balance_kW < 0
    assert 2900 < f.shortfall_kW < 3200, (
        f"shortfall {f.shortfall_kW:.0f} kW outside expected ~3000 band")
    assert 10400 < f.breakdown["GPU IT × PUE"] < 10600


# ── assumption text is explicit ──────────────────────────────────────────────

def test_assumption_text_present(engine):
    f = engine.solve(engine.defaults())["feasibility"]
    assert "GT-powered" in f.assumption
    assert "GT electrical bus" in f.assumption


# ── MED electrical is counted ────────────────────────────────────────────────

def test_med_electrical_counted_in_demand(engine):
    f = engine.solve(engine.defaults())["feasibility"]
    assert "MED electrical (pumps)" in f.breakdown
    med_kw = f.breakdown["MED electrical (pumps)"]
    assert med_kw > 0
    assert f.demand_kW > f.breakdown["GPU IT × PUE"]      # MED adds on top


# ── every contributor is itemised at screening fidelity ─────────────────────

def test_breakdown_itemises_every_aux_load(engine):
    """Every plant aux load is now modelled — no more 'not modelled' entries."""
    f = engine.solve(engine.defaults())["feasibility"]
    expected_keys = {
        "GT actual power",
        "GPU IT × PUE",
        "MED electrical (pumps)",
        "LiBr pump electrical",
        "Cooling tower fan electrical",
        "GT auxiliaries",
        "Plant BoP (lights/HVAC)",
    }
    assert set(f.breakdown.keys()) == expected_keys
    for k, v in f.breakdown.items():
        assert v is not None, f"{k} should be modelled, not None"
        assert v >= 0,        f"{k} should be ≥ 0, got {v}"


def test_each_block_emits_its_own_aux_row(engine):
    """The new aux rows live on their respective blocks so they're auditable."""
    from nexablock.blocks import GasTurbine, LiBrChiller, CoolingTower
    solved = engine.solve(engine.defaults())["solved"]
    for cls, label in [
        (GasTurbine,   "GT aux electrical"),
        (LiBrChiller,  "LiBr pump electrical"),
        (CoolingTower, "CT fan electrical"),
    ]:
        b = next(b for b in solved.blocks if isinstance(b, cls))
        assert label in b.results, f"{cls.__name__} missing aux row {label!r}"
        assert b.results[label].value > 0


def test_bop_frac_zeroes_facility_load(engine):
    """Setting bop_frac=0 zeroes the facility BoP line — independent knob."""
    v = engine.defaults(); v["bop_frac"] = 0.0
    f = engine.solve(v)["feasibility"]
    assert f.breakdown["Plant BoP (lights/HVAC)"] == 0.0


# ── feasibility independent of convergence ───────────────────────────────────

def test_feasibility_is_independent_of_convergence(engine):
    """High-GPU deficit case: solver still converges (acyclic GT system),
    but feasibility flags the deficit. Two separate truths."""
    v = engine.defaults(); v["gpu_it_kW"] = 10000.0
    r = engine.solve(v)
    assert r["solved"].convergence.converged is True       # solver fine
    assert r["feasibility"].feasible is False              # power balance not
