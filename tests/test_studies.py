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
from nexablock.studies            import (ParameterSweep, SweepResult,
                                          OneAtATimeSensitivity, SensitivityResult,
                                          Scenario, ScenarioRunner, ScenarioResult)


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


# ══════════════════════════════════════════════════════════════════════════════
# §7.7 — One-at-a-time sensitivity
# ══════════════════════════════════════════════════════════════════════════════

_BOUNDS = {
    "load_pct":     (10.0, 100.0),
    "libr_frac":    (0.05, 0.95),
    "gt_eff":       (0.15, 0.45),
    "hrsg_eff_pct": (50.0, 95.0),
    "libr_cop":     (0.5,  0.85),
}

_KPIS = [
    "GT actual power kW",
    "Steam generation t/h",
    "LiBr cooling kW",
    "MED water m3day",
]


@pytest.fixture(scope="module")
def sens(base):
    s = OneAtATimeSensitivity(
        builder=build_gt_system, base_params=base, kpi_fn=summary,
        rel_step=0.01, abs_step=0.01,
        bounds=_BOUNDS,
        step_override={"med_effects": 1.0},
    )
    return s.run(
        inputs=["load_pct", "gt_eff", "libr_frac", "libr_cop",
                "hrsg_eff_pct", "med_effects", "t_ambient_C"],
        kpis  =_KPIS,
    )


def _e(result, kpi, inp):
    """Pull the single entry for (inp, kpi)."""
    for ent in result.entries:
        if ent.input == inp and ent.kpi == kpi:
            return ent
    raise AssertionError(f"no entry for input={inp!r} kpi={kpi!r}")


# ── plumbing ──────────────────────────────────────────────────────────────────

def test_sens_returns_one_entry_per_pair(sens):
    assert isinstance(sens, SensitivityResult)
    assert len(sens.entries) == 7 * len(_KPIS)
    assert all(e.error is None for e in sens.entries)


def test_sens_base_kpis_present(sens):
    for k in _KPIS:
        assert k in sens.base_kpis


# ── sign sanity at the base point ────────────────────────────────────────────

def test_dSteam_dLoad_positive(sens):
    assert _e(sens, "Steam generation t/h", "load_pct").elasticity > 0


def test_dWater_dMEDeffects_positive(sens):
    assert _e(sens, "MED water m3day", "med_effects").elasticity > 0


def test_dWater_dLibrFrac_negative(sens):
    """More steam to LiBr leaves less for MED."""
    assert _e(sens, "MED water m3day", "libr_frac").elasticity < 0


def test_dCool_dLibrCOP_positive(sens):
    assert _e(sens, "LiBr cooling kW", "libr_cop").elasticity > 0


def test_dPower_dAmbient_negative(sens):
    """GT derate kicks in above 15°C — warmer ambient → less power."""
    assert _e(sens, "GT actual power kW", "t_ambient_C").elasticity < 0


def test_dCool_dLibrFrac_positive(sens):
    assert _e(sens, "LiBr cooling kW", "libr_frac").elasticity > 0


# ── magnitude sanity ─────────────────────────────────────────────────────────

def test_power_load_elasticity_near_one(sens):
    """P_GT scales linearly with load_pct (after derate, before COP). ε ≈ 1.0."""
    eps = _e(sens, "GT actual power kW", "load_pct").elasticity
    assert abs(eps - 1.0) < 0.05, f"expected ε≈1.0, got {eps:.4f}"


def test_cool_libr_cop_elasticity_near_one(sens):
    """Q_cool = Q_gen × COP → ε(cool, cop) ≈ 1.0."""
    eps = _e(sens, "LiBr cooling kW", "libr_cop").elasticity
    assert abs(eps - 1.0) < 0.05, f"expected ε≈1.0, got {eps:.4f}"


# ── tornado helper ───────────────────────────────────────────────────────────

def test_tornado_sorted_descending_by_magnitude(sens):
    tor = sens.tornado("MED water m3day")
    mags = [abs(e.elasticity) for e in tor if not (e.elasticity != e.elasticity)]
    for a, b in zip(mags, mags[1:]):
        assert a >= b, f"tornado not monotonic: {mags}"


# ── edge cases ───────────────────────────────────────────────────────────────

def test_sens_unknown_input_raises(base):
    s = OneAtATimeSensitivity(
        builder=build_gt_system, base_params=base, kpi_fn=summary)
    with pytest.raises(ValueError, match="Unknown parameter"):
        s.run(inputs=["not_a_field"], kpis=["Steam generation t/h"])


def test_bounds_clamp_at_load_100():
    """Base load_pct=99.5 with bounds (10,100): high clamps to 100, low at ~98.5.
    span < 2h, dY/dX still finite."""
    base = GTSystemParams(load_pct=99.5)
    s = OneAtATimeSensitivity(
        builder=build_gt_system, base_params=base, kpi_fn=summary,
        rel_step=0.01, bounds={"load_pct": (10.0, 100.0)})
    r = s.run(inputs=["load_pct"], kpis=["Steam generation t/h"])
    e = r.entries[0]
    assert e.high_input == 100.0, f"upper should clamp to 100, got {e.high_input}"
    assert e.low_input  < 99.5
    assert e.span > 0
    assert e.dY_dX == e.dY_dX  # not NaN
    assert e.elasticity > 0


# ══════════════════════════════════════════════════════════════════════════════
# §7.8 — Scenarios
# ══════════════════════════════════════════════════════════════════════════════

_SUMMER = {"t_ambient_C": 40.0, "load_pct": 100.0, "t_wb_C": 30.0}
_WINTER = {"t_ambient_C":  5.0, "load_pct":  40.0, "t_wb_C": 10.0}


@pytest.fixture(scope="module")
def runner(base):
    return ScenarioRunner(builder=build_gt_system, base_params=base, kpi_fn=summary)


@pytest.fixture(scope="module")
def scenarios_result(runner):
    return runner.run({"summer peak": _SUMMER, "winter low load": _WINTER})


# ── shape ────────────────────────────────────────────────────────────────────

def test_scenarios_table_shape(scenarios_result):
    assert isinstance(scenarios_result, ScenarioResult)
    assert len(scenarios_result.points) == 2
    assert {p.name for p in scenarios_result.points} == {"summer peak", "winter low load"}
    assert all(p.converged for p in scenarios_result.points)


def test_scenarios_kpis_populated(scenarios_result):
    for p in scenarios_result.points:
        for k in ("GT actual power kW", "Steam generation t/h", "MED water m3day"):
            assert k in p.kpis


# ── direction sanity: summer (100% load, 40°C) vs winter (40% load, 5°C) ─────

def test_summer_more_steam_than_winter(scenarios_result):
    steam = scenarios_result.kpi("Steam generation t/h")
    assert steam["summer peak"] > steam["winter low load"], (
        f"summer steam {steam['summer peak']:.2f} not > winter {steam['winter low load']:.2f}")


def test_summer_more_power_than_winter(scenarios_result):
    """Even with derate at 40°C, 100% load beats 40% load at 5°C."""
    power = scenarios_result.kpi("GT actual power kW")
    assert power["summer peak"] > power["winter low load"]


def test_summer_more_water_than_winter(scenarios_result):
    water = scenarios_result.kpi("MED water m3day")
    assert water["summer peak"] > water["winter low load"]


# ── dict form ≡ Scenario-list form ───────────────────────────────────────────

def test_dict_form_and_list_form_equivalent(runner):
    dict_result = runner.run({"summer peak": _SUMMER})
    list_result = runner.run([Scenario("summer peak", _SUMMER)])
    assert dict_result.points[0].kpis == list_result.points[0].kpis


# ── fail-loud safety nets ────────────────────────────────────────────────────

def test_unknown_override_raises(runner):
    with pytest.raises(ValueError, match="Unknown override"):
        runner.run({"bogus": {"not_a_field": 1.0}})


def test_unknown_override_raises_before_solve(runner):
    """Validation must fire before any builder call. Wrap builder to track calls."""
    calls = []
    def tracking_builder(p):
        calls.append(p); return build_gt_system(p)
    r = ScenarioRunner(builder=tracking_builder, base_params=runner.base_params,
                      kpi_fn=summary)
    with pytest.raises(ValueError, match="Unknown override"):
        r.run({"bogus": {"load_pct": 50.0, "not_a_field": 1.0}})
    assert calls == [], "builder must not be called when an override key is invalid"


def test_duplicate_scenario_name_raises(runner):
    with pytest.raises(ValueError, match="Duplicate scenario name"):
        runner.run([Scenario("dup", {"load_pct": 80.0}),
                    Scenario("dup", {"load_pct": 90.0})])


# ── diff helper ──────────────────────────────────────────────────────────────

def test_diff_vs_base_zero_for_empty_overrides(runner):
    r = runner.run({"identity": {}})
    diffs = r.diff_vs_base("Steam generation t/h")
    assert diffs["identity"] == pytest.approx(0.0, abs=1e-9)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
