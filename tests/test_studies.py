"""
tests/test_studies.py — Step §7.6 parameter-sweep primitive.

Sweep GT load 70–100% and assert:
  • one SweepPoint per input, all converged
  • steam and water KPIs are strictly increasing in load
  • the 100% endpoint matches a direct single-point solve exactly
  • a bad param name fails fast
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dataclasses import replace
import pytest

from simulators.gt_system.system import GTSystemParams, build_gt_system, summary
from nexablock.studies            import ParameterSweep, SweepResult


# ── fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def base():
    return GTSystemParams()


@pytest.fixture(scope="module")
def load_sweep(base):
    sweep = ParameterSweep(builder=build_gt_system, base_params=base, kpi_fn=summary)
    return sweep.run({"load_pct": [70, 80, 90, 100]})


# ── basic plumbing ────────────────────────────────────────────────────────────

def test_sweep_runs_each_point(load_sweep):
    assert isinstance(load_sweep, SweepResult)
    assert len(load_sweep.points) == 4
    assert all(p.converged for p in load_sweep.points)
    assert load_sweep.varied == ["load_pct"]


def test_inputs_carried_through(load_sweep):
    inputs = load_sweep.input("load_pct")
    assert inputs == [70, 80, 90, 100]


# ── physics sanity: KPIs move with load ───────────────────────────────────────

def test_steam_rises_with_load(load_sweep):
    steam = load_sweep.kpi("Steam generation t/h")
    for a, b in zip(steam, steam[1:]):
        assert b > a, f"steam not monotonic: {steam}"


def test_water_rises_with_load(load_sweep):
    water = load_sweep.kpi("MED water m3day")
    for a, b in zip(water, water[1:]):
        assert b > a, f"water not monotonic: {water}"


def test_gt_power_rises_with_load(load_sweep):
    power = load_sweep.kpi("GT actual power kW")
    for a, b in zip(power, power[1:]):
        assert b > a, f"GT power not monotonic: {power}"


# ── endpoint cross-check vs direct single-point solve ────────────────────────

def test_endpoint_matches_direct_solve(base, load_sweep):
    """Last sweep point at load_pct=100 should equal summary(build_gt_system(
    replace(base, load_pct=100))) exactly — same code path, same numbers."""
    direct = summary(build_gt_system(replace(base, load_pct=100)))
    swept  = load_sweep.points[-1].kpis
    for k, v in direct.items():
        assert swept[k] == v, f"{k}: sweep={swept[k]} vs direct={v}"


# ── safety net: typo'd param ──────────────────────────────────────────────────

def test_unknown_param_raises(base):
    sweep = ParameterSweep(builder=build_gt_system, base_params=base, kpi_fn=summary)
    with pytest.raises(ValueError, match="Unknown parameter"):
        sweep.run({"not_a_field": [1, 2]})


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
