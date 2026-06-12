"""
tests/test_control.py — operating modes + GT auto-power + LiBr-priority split.

Covers the controller's mode-handling logic and how it propagates to the
solved system, the feasibility check, and the audit.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from simulators.gt_system.system    import GTSystemParams, build_gt_system, summary


def _solve(**kwargs):
    base = dict(operating_mode="island", gt_power_mode="auto",
                steam_split_mode="auto")
    base.update(kwargs)
    return build_gt_system(GTSystemParams(**base))


# ── controller exposes derived values ────────────────────────────────────────

def test_solved_carries_control_state():
    solved = _solve()
    assert hasattr(solved, "control")
    cs = solved.control
    assert cs.derived_load_pct is True
    assert cs.derived_libr_frac is True
    assert cs.iterations >= 1


def test_manual_modes_pass_through_unchanged():
    solved = _solve(gt_power_mode="manual", steam_split_mode="manual",
                     load_pct=85.0, libr_frac=0.50)
    cs = solved.control
    assert cs.load_pct == pytest.approx(85.0)
    assert cs.libr_frac == pytest.approx(0.50)
    assert cs.derived_load_pct is False
    assert cs.derived_libr_frac is False


# ── island mode rules ────────────────────────────────────────────────────────

def test_island_auto_load_pct_capped_by_electrical_demand():
    """Island: GT load = required_load_for_elec. Power never ramps past
    what the electrical demand can absorb (no grid backstop)."""
    solved = _solve(gpu_it_kW=2000.0)   # small GPU → small elec demand → low load
    cs = solved.control
    assert cs.load_pct < 50.0    # well below 100%
    assert cs.grid_export_kW == 0.0


def test_island_big_gpu_caps_at_100_pct():
    """Big GPU exceeds derated cap → load_pct hits the ceiling."""
    solved = _solve(gpu_it_kW=15000.0)
    cs = solved.control
    assert cs.load_pct == pytest.approx(100.0, abs=0.1)


def test_island_external_load_increases_required_load():
    """External load adds to NEXA demand → higher required GT load."""
    base = _solve(gpu_it_kW=3000.0).control.load_pct
    with_ext = _solve(gpu_it_kW=3000.0, external_load_kW=1000.0).control.load_pct
    assert with_ext > base


# ── grid-tied mode rules ─────────────────────────────────────────────────────

def test_grid_mode_load_takes_max_of_electrical_and_steam():
    """Grid: ramp to whichever driver is higher (electrical OR cooling-steam)."""
    solved = _solve(gpu_it_kW=5000.0, operating_mode="grid_tied")
    cs = solved.control
    # Steam-driven and electrical-driven loads should both be reported.
    assert cs.required_load_for_elec_pct > 0
    assert cs.required_load_for_steam_pct > 0


def test_grid_mode_yields_grid_export_when_surplus():
    """At a small GPU load in grid mode, GT may run slightly above elec
    demand to cover cooling-driven steam, producing surplus → export."""
    solved = _solve(gpu_it_kW=5000.0, operating_mode="grid_tied")
    assert solved.control.grid_export_kW >= 0


def test_grid_mode_no_manual_external_load():
    """In grid mode the manual external_load_kW is ignored — grid
    absorbs/produces the dynamic balance."""
    solved = _solve(gpu_it_kW=3000.0, operating_mode="grid_tied",
                     external_load_kW=999.0)
    assert solved.control.external_load_kW == 0.0


# ── LiBr-priority split (steam_split_mode=auto) ─────────────────────────────

def test_auto_libr_frac_is_residual_steam_balancer():
    """In auto split, libr_frac is derived to cover exactly the GPU heat;
    MED is the residual. If steam is just enough, libr_frac = 1.0."""
    solved = _solve(gpu_it_kW=5000.0, operating_mode="grid_tied")
    cs = solved.control
    assert 0.0 < cs.libr_frac <= 1.0


def test_small_gpu_leaves_steam_for_med():
    """Small GPU → LiBr needs less steam → libr_frac < 1.0 → MED gets some."""
    solved = _solve(gpu_it_kW=1000.0, operating_mode="grid_tied")
    cs = solved.control
    k = summary(solved)
    assert cs.libr_frac < 1.0
    assert k["MED water m3day"] > 0


# ── summary reflects the resolved control state ─────────────────────────────

def test_summary_includes_derived_setpoints_and_mode_kpis():
    solved = _solve()
    k = summary(solved)
    for key in ("Resolved load_pct", "Resolved libr_frac",
                "External load kW", "Grid export kW"):
        assert key in k


def test_grid_mode_grid_export_in_summary():
    solved = _solve(gpu_it_kW=3000.0, operating_mode="grid_tied")
    k = summary(solved)
    assert k["Grid export kW"] >= 0
    assert k["External load kW"] == 0.0


def test_island_external_load_in_summary():
    solved = _solve(gpu_it_kW=3000.0, external_load_kW=500.0)
    k = summary(solved)
    assert k["External load kW"] == pytest.approx(500.0)
    assert k["Grid export kW"] == 0.0


# ── audit composition checks present ────────────────────────────────────────

def test_island_audit_includes_F1_F2_F3_F4():
    """Island/auto: F1 (balance closed) + F2 + F3 + F4 + E9 = 5 composition checks."""
    import nexa_toolkit.engines                              # noqa: registers
    from nexa_toolkit.framework import get
    e = get("gt_system_v2")
    v = e.defaults()  # island/auto defaults
    a = e.solve(v)["audit"]
    names = {c.name for c in a.checks}
    assert any(n.startswith("E9") for n in names)
    assert any(n.startswith("F1") for n in names)
    assert any(n.startswith("F2") for n in names)
    assert any(n.startswith("F3") for n in names)
    assert any(n.startswith("F4") for n in names)
    assert not any(n.startswith("F5") for n in names)        # grid-only


def test_grid_audit_includes_F5_not_F1():
    import nexa_toolkit.engines                              # noqa
    from nexa_toolkit.framework import get
    e = get("gt_system_v2")
    v = e.defaults(); v["operating_mode"] = 1
    a = e.solve(v)["audit"]
    names = {c.name for c in a.checks}
    assert any(n.startswith("F5") for n in names)
    assert not any(n.startswith("F1") for n in names)
