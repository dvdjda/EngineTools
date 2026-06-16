"""
tests/test_audit.py — universal post-solve audit layer.

Two layers of testing:
 1. Framework primitives — CheckResult helpers, AuditStatus.coverage_for,
    generic-failure global flagging.
 2. Per-block audits firing against the v2 GT system — count, content,
    coverage of every adapter KPI.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import nexa_toolkit.engines                              # noqa: registers
from nexa_toolkit.framework         import get
from nexablock.audit                import (audit, AuditStatus, CheckResult,
                                            mass_balance, energy_balance,
                                            pass_fail, bounds_check)


# ── framework primitives ─────────────────────────────────────────────────────

def test_mass_balance_passes_within_tol():
    c = mass_balance("test", supply=100.0, demand=100.001,
                     affects=["K"], tol_rel=1e-3)
    assert c.passed and c.measure == "supply/demand/balance"


def test_mass_balance_fails_outside_tol():
    c = mass_balance("test", supply=100.0, demand=99.0,
                     affects=["K"], tol_rel=1e-3)
    assert not c.passed


def test_energy_balance_helper():
    c = energy_balance("test", supply=5000, demand=4990,
                       affects=["P"], tol_rel=1e-2)
    assert c.passed and c.category == "Energy closure"


def test_pass_fail_helper():
    c = pass_fail("test", True, "ok", category="Plausibility", affects=["X"])
    assert c.passed and c.measure == "pass/fail"


def test_bounds_check_helper():
    ok  = bounds_check("test", 5, 0, 10, affects=["X"])
    bad = bounds_check("test", -1, 0, 10, affects=["X"])
    assert ok.passed and not bad.passed


def test_coverage_for_uncovered_returns_uncovered():
    s = AuditStatus(checks=[pass_fail("A", True, "", category="Test", affects=["x"])])
    assert s.coverage_for("y") == "uncovered"


def test_coverage_for_covered_passed():
    s = AuditStatus(checks=[pass_fail("A", True, "", category="Test", affects=["x"])])
    assert s.coverage_for("x") == "passed"


def test_coverage_for_covered_failed_flips_to_failed():
    s = AuditStatus(checks=[
        pass_fail("A", True,  "", category="Test", affects=["x"]),
        pass_fail("B", False, "", category="Test", affects=["x"]),
    ])
    assert s.coverage_for("x") == "failed"


def test_generic_failures_pulls_failed_with_no_affects():
    s = AuditStatus(checks=[
        pass_fail("global", False, "", category="Plausibility", affects=[]),
        pass_fail("local",  False, "", category="Test", affects=["k"]),
    ])
    g = s.generic_failures()
    assert len(g) == 1 and g[0].name == "global"


# ── per-block audit on v2 GT system ──────────────────────────────────────────

@pytest.fixture(scope="module")
def engine():
    return get("gt_system_v2")


@pytest.fixture(scope="module")
def default_audit(engine):
    return engine.solve(engine.defaults())["audit"]


def test_audit_emits_42_checks_in_island_auto_mode(default_audit):
    """Island + auto, post-rework (no steam splitter; radiator instead of
    cooling tower; MED rejection-driven): block checks + composition checks
    (E9 bus closure, F1 island balance, F2 external load non-neg, F3 derived
    load ≤100%) = 42 total."""
    assert len(default_audit.checks) == 42


def test_audit_categories_present(default_audit):
    cats = {c.category for c in default_audit.checks}
    assert {"Energy closure", "Mass closure", "Second law", "Plausibility"} <= cats


def test_audit_category_counts(default_audit):
    """Per-category counts after the cooling-loop rework."""
    by_cat = default_audit.by_category()
    assert len(by_cat["Energy closure"]) == 10
    assert len(by_cat["Mass closure"])   == 5
    assert len(by_cat["Second law"])     == 11
    assert len(by_cat["Plausibility"])   == 16


def test_default_audit_flags_electrically_pinned_cooling_gap(default_audit):
    """At island/auto defaults (GPU 5 MW) the GT is electrically pinned to
    ~60% load. With the itemised (lower) plant-aux model the GT runs cooler,
    so steam delivers ~3.4% less cooling than GPU heat — just past the 2.5%
    screening tolerance. The M7 coolant-flow check is the one that flags;
    everything else (energy/mass closure, second law, bus closure F1) passes."""
    failed = default_audit.failed()
    assert [c.name.split(":")[0] for c in failed] == ["M7"], \
        f"expected only M7 to fail, got {[c.name for c in failed]}"
    assert not default_audit.passed


def test_grid_default_audit_clean():
    """Grid mode at defaults: GT ramps to cool the GPU and exports surplus,
    so there is no cooling deficit — the audit reads fully clean."""
    import nexa_toolkit.engines                              # noqa
    from nexa_toolkit.framework import get
    e = get("gt_system_v2")
    v = e.defaults(); v["operating_mode"] = 1                # grid_tied
    a = e.solve(v)["audit"]
    assert a.passed, f"failures: {[c.name for c in a.failed()]}"


def test_audit_fails_loud_when_real_deficit_present():
    """GPU 10 MW in island/auto: cooling shortfall ~20% — well above the
    2.5% screening tolerance. M7 must fail, cooling-balance flagged."""
    import nexa_toolkit.engines                              # noqa
    from nexa_toolkit.framework import get
    e = get("gt_system_v2")
    v = e.defaults(); v["gpu_it_kW"] = 10000.0
    a = e.solve(v)["audit"]
    assert not a.passed
    assert any("M7" in c.name for c in a.failed())


def test_grid_mode_default_audit_fully_passes(engine):
    """In grid mode the GT can ramp to satisfy cooling — audit goes clean."""
    v = engine.defaults(); v["operating_mode"] = 1   # grid_tied
    a = engine.solve(v)["audit"]
    assert a.passed, f"failures: {[c.name for c in a.failed()]}"
    assert len(a.failed()) == 0


# ── per-KPI coverage ────────────────────────────────────────────────────────

def test_every_v2_kpi_is_covered_by_at_least_two_checks(engine, default_audit):
    """Coverage table from the design — every adapter output has ≥2 checks
    naming it in their `affects` list."""
    for label in ("GT actual power", "NG consumption", "Steam generation",
                  "LiBr cooling capacity", "GPU IT load", "MED water production"):
        covering = [c for c in default_audit.checks if label in c.affects]
        assert len(covering) >= 2, (
            f"KPI {label!r} covered by only {len(covering)} check(s); "
            f"need at least 2 for trustable verification.")


def test_grid_mode_every_kpi_passes_audit_coverage(engine):
    """In grid mode every KPI's covering checks all pass."""
    v = engine.defaults(); v["operating_mode"] = 1
    a = engine.solve(v)["audit"]
    for label in ("GT actual power", "NG consumption", "Steam generation",
                  "LiBr cooling capacity", "GPU IT load", "MED water production"):
        assert a.coverage_for(label) == "passed", (
            f"KPI {label!r} not covered/passed in grid mode "
            f"(failed: {[c.name for c in a.failed()]})")


# ── specific check identities ───────────────────────────────────────────────

def test_p11_actual_le_derated_passes(default_audit):
    """P11 — GT actual power must not exceed derated capacity."""
    p11 = next(c for c in default_audit.checks if c.name.startswith("P11"))
    assert p11.passed


def test_e7_cassette_energy_closure_passes(default_audit):
    """E7 — Heat_load = IT_power + Cassette_overhead at the new split."""
    e7 = next(c for c in default_audit.checks if c.name.startswith("E7"))
    assert e7.passed
    assert e7.measure == "supply/demand/balance"


def test_p12_no_negative_flows_passes(default_audit):
    """P12 (generic, framework-level)."""
    p12 = next(c for c in default_audit.checks if c.name.startswith("P12"))
    assert p12.passed and p12.affects == []   # generic → empty affects


def test_p13_finite_kw_values_passes(default_audit):
    p13 = next(c for c in default_audit.checks if c.name.startswith("P13"))
    assert p13.passed


# ── basis re-wiring sanity ──────────────────────────────────────────────────

def test_basis_data_driven_from_coverage():
    """A KPI covered by a failed check goes 'unverified'; covered+passed
    keeps engine-declared; uncovered becomes 'screening'."""
    s = AuditStatus(checks=[
        pass_fail("ok",   True,  "", category="Test", affects=["a"]),
        pass_fail("bad",  False, "", category="Test", affects=["b"]),
    ])
    assert s.coverage_for("a") == "passed"
    assert s.coverage_for("b") == "failed"
    assert s.coverage_for("c") == "uncovered"
