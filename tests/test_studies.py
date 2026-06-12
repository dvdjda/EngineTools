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


# ══════════════════════════════════════════════════════════════════════════════
# §7.9 — Chart helpers
# ══════════════════════════════════════════════════════════════════════════════

import matplotlib.pyplot as _plt
from nexablock.studies.charts import (
    tornado_chart, sweep_chart, scenarios_chart, sweep_contour,
    _tornado_figure, _sweep_figure, _scenarios_figure,
)

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _assert_valid_png(path):
    with open(path, "rb") as f:
        head = f.read(8)
    assert head == _PNG_MAGIC, f"not a PNG: header={head!r}"
    assert os.path.getsize(path) > 1024, f"PNG too small: {os.path.getsize(path)} bytes"


# ── tornado ──────────────────────────────────────────────────────────────────

def test_tornado_chart_writes_png(sens, tmp_path):
    p = tmp_path / "tornado.png"
    tornado_chart(sens, str(p), kpi="MED water m3day")
    _assert_valid_png(p)


def test_tornado_figure_one_bar_per_input(sens):
    """sens fixture varies 7 inputs → 7 bars per KPI tornado."""
    fig = _tornado_figure(sens, kpi="MED water m3day")
    try:
        ax = fig.axes[0]
        assert len(ax.patches) == 7, f"expected 7 bars, got {len(ax.patches)}"
    finally:
        _plt.close(fig)


def test_tornado_top_n_truncates(sens):
    fig = _tornado_figure(sens, kpi="MED water m3day", top_n=3)
    try:
        ax = fig.axes[0]
        assert len(ax.patches) == 3
    finally:
        _plt.close(fig)


def test_tornado_drop_zero_filters_zero_elasticity_bars(sens):
    """drop_zero=True hides inputs that don't move the chosen KPI so the
    chart doesn't read as broken when most bars are zero-length."""
    full   = _tornado_figure(sens, kpi="MED water m3day")
    pruned = _tornado_figure(sens, kpi="MED water m3day", drop_zero=True)
    try:
        # libr_cop has ε=0 for MED water → pruned bar count drops by 1.
        assert len(pruned.axes[0].patches) < len(full.axes[0].patches)
        assert len(pruned.axes[0].patches) >= 1
    finally:
        _plt.close(full); _plt.close(pruned)


# ── sweep ────────────────────────────────────────────────────────────────────

def test_sweep_chart_writes_png(load_sweep, tmp_path):
    p = tmp_path / "sweep.png"
    sweep_chart(load_sweep, str(p),
                kpis=["Steam generation t/h", "MED water m3day"])
    _assert_valid_png(p)


def test_sweep_figure_one_line_per_kpi(load_sweep):
    kpis = ["Steam generation t/h", "MED water m3day", "GT actual power kW"]
    fig = _sweep_figure(load_sweep, kpis=kpis)
    try:
        ax = fig.axes[0]
        assert len(ax.lines) == len(kpis)
    finally:
        _plt.close(fig)


def test_sweep_figure_subplots_gives_one_axes_per_kpi(load_sweep):
    """subplots=True draws each KPI on its own axes so a 'flat-at-zero'
    small-scale line (steam t/h next to GT kW) becomes visible again."""
    kpis = ["Steam generation t/h", "MED water m3day", "GT actual power kW"]
    fig = _sweep_figure(load_sweep, kpis=kpis, subplots=True)
    try:
        assert len(fig.axes) == len(kpis)
        for ax in fig.axes:
            assert len(ax.lines) == 1
    finally:
        _plt.close(fig)


def test_sweep_chart_2d_raises(base):
    sweep = ParameterSweep(build_gt_system, base, summary)
    r2d   = sweep.run({"load_pct": [70, 90], "libr_frac": [0.3, 0.7]})
    with pytest.raises(ValueError, match="1-D only"):
        _sweep_figure(r2d, kpis=["Steam generation t/h"])


# ── scenarios ────────────────────────────────────────────────────────────────

def test_scenarios_chart_writes_png(scenarios_result, tmp_path):
    p = tmp_path / "scenarios.png"
    scenarios_chart(scenarios_result, str(p),
                    kpis=["Steam generation t/h", "MED water m3day"])
    _assert_valid_png(p)


def test_scenarios_figure_has_expected_bars(scenarios_result):
    """2 scenarios × 3 KPIs = 6 bars."""
    kpis = ["Steam generation t/h", "MED water m3day", "GT actual power kW"]
    fig  = _scenarios_figure(scenarios_result, kpis=kpis)
    try:
        ax = fig.axes[0]
        assert len(ax.patches) == 2 * len(kpis)
    finally:
        _plt.close(fig)


# ── 2-D contour placeholder ──────────────────────────────────────────────────

def test_sweep_contour_not_implemented(load_sweep, tmp_path):
    with pytest.raises(NotImplementedError, match="contour"):
        sweep_contour(load_sweep, str(tmp_path / "x.png"), kpi="any")


# ── engine wiring: GT load-sweep screening shows the chart in the chart slot ─

def test_gt_load_sweep_engine_chart_writes_png(tmp_path):
    import nexa_toolkit.engines              # noqa: registers
    from nexa_toolkit.framework import get
    e = get("gt_system_v2_loadsweep")
    r = e.solve(e.defaults())
    p = tmp_path / "gt_load_sweep.png"
    e.chart(r, str(p))
    _assert_valid_png(p)
    assert "sweep" in r and len(r["sweep"].points) == 11   # 50..100 step 5


# ══════════════════════════════════════════════════════════════════════════════
# §7.10 — Engine study_hooks() + UI study button pipe
# ══════════════════════════════════════════════════════════════════════════════

def _gt_v2_engine():
    """Load the v2 GT engine and return it."""
    import nexa_toolkit.engines               # noqa: registers
    from nexa_toolkit.framework import get
    return get("gt_system_v2")


def test_study_hooks_shape():
    e = _gt_v2_engine()
    h = e.study_hooks()
    for key in ("builder", "make_params", "kpi_fn", "kpis",
                "sensitivity_inputs", "sweep_inputs", "bounds",
                "step_override", "scenarios"):
        assert key in h, f"hooks missing key: {key}"
    # Callables really callable
    assert callable(h["builder"])
    assert callable(h["make_params"])
    assert callable(h["kpi_fn"])
    # KPIs are real keys produced by kpi_fn(SolvedSystem)
    solved = h["builder"](h["make_params"](e.defaults()))
    kpi_dict = h["kpi_fn"](solved)
    for k in h["kpis"]:
        assert k in kpi_dict, f"hook kpi {k!r} not produced by kpi_fn"


def test_study_hooks_inherited_by_loadsweep_subclass():
    import nexa_toolkit.engines
    from nexa_toolkit.framework import get
    e = get("gt_system_v2_loadsweep")
    assert hasattr(e, "study_hooks")
    h = e.study_hooks()
    assert "load_pct" in h["sweep_inputs"]


def test_study_pipe_sensitivity_via_hooks(tmp_path):
    """Mimic the UI sensitivity button: drive everything through study_hooks."""
    e = _gt_v2_engine()
    h = e.study_hooks()
    params = h["make_params"](e.defaults())
    sens = OneAtATimeSensitivity(
        builder=h["builder"], base_params=params, kpi_fn=h["kpi_fn"],
        bounds=h["bounds"], step_override=h["step_override"],
    ).run(inputs=h["sensitivity_inputs"], kpis=h["kpis"])
    p = tmp_path / "sens_via_hooks.png"
    tornado_chart(sens, str(p), kpi=h["kpis"][0])
    _assert_valid_png(p)


def test_study_pipe_sweep_via_hooks(tmp_path):
    """Mimic the UI sweep button (load_pct over its full bounds, 10 points)."""
    e = _gt_v2_engine()
    h = e.study_hooks()
    params = h["make_params"](e.defaults())
    lo, hi = h["bounds"]["load_pct"]
    N = 10
    values = [lo + (hi - lo) * i / (N - 1) for i in range(N)]
    swp = ParameterSweep(h["builder"], params, h["kpi_fn"]).run({"load_pct": values})
    p = tmp_path / "sweep_via_hooks.png"
    sweep_chart(swp, str(p), kpis=h["kpis"])
    _assert_valid_png(p)
    assert len(swp.points) == N


def test_study_pipe_scenarios_via_hooks(tmp_path):
    """Mimic the UI scenarios button using the engine's built-in scenarios."""
    e = _gt_v2_engine()
    h = e.study_hooks()
    params = h["make_params"](e.defaults())
    res = ScenarioRunner(h["builder"], params, h["kpi_fn"]).run(h["scenarios"])
    p = tmp_path / "scenarios_via_hooks.png"
    scenarios_chart(res, str(p), kpis=h["kpis"])
    _assert_valid_png(p)
    assert len(res.points) == len(h["scenarios"])


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
