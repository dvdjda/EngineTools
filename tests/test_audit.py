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


def test_audit_emits_39_checks(default_audit):
    """9 energy (E1-E8 + M6 via energy_balance helper) + 7 mass + 10 second-law
    + 13 plausibility = 39. M6 is the NG-fuel → GT-power closure; it's
    arithmetically an energy-balance equation even though the spec listed
    it under Mass closure, so the helper puts it in Energy closure."""
    assert len(default_audit.checks) == 39


def test_audit_categories_present(default_audit):
    cats = {c.category for c in default_audit.checks}
    assert {"Energy closure", "Mass closure", "Second law", "Plausibility"} <= cats


def test_audit_category_counts(default_audit):
    """Verify the documented per-category counts hold."""
    by_cat = default_audit.by_category()
    assert len(by_cat["Energy closure"]) == 9
    assert len(by_cat["Mass closure"])   == 7
    assert len(by_cat["Second law"])     == 10
    assert len(by_cat["Plausibility"])   == 13


def test_default_audit_almost_passes(default_audit):
    """At defaults the cooling deficit produces ONE expected failure (M7
    inlet supply < cassette demand). Every other check passes."""
    failed = default_audit.failed()
    assert len(failed) == 1
    assert "M7" in failed[0].name


def test_balanced_design_audit_fully_passes(engine):
    """libr_frac=0.85 closes the cooling deficit. M7 also clears. 39/39."""
    v = engine.defaults(); v["libr_frac"] = 0.85
    a = engine.solve(v)["audit"]
    assert a.passed
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


def test_balanced_design_every_kpi_passes_audit_coverage(engine):
    """At libr_frac=0.85 every KPI's covering checks all pass."""
    v = engine.defaults(); v["libr_frac"] = 0.85
    a = engine.solve(v)["audit"]
    for label in ("GT actual power", "NG consumption", "Steam generation",
                  "LiBr cooling capacity", "GPU IT load", "MED water production"):
        assert a.coverage_for(label) == "passed", (
            f"KPI {label!r} not covered/passed at balanced design")


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
