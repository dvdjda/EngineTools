"""
tests/test_feasibility.py — system-level resource balances.

Each resource (Power, Cooling) is its own ResourceBalance; the aggregate
FeasibilityStatus is feasible only if every balance is. Strictly separate
from solver convergence.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import nexa_toolkit.engines                                  # noqa: registers
from nexa_toolkit.framework import get
from simulators.gt_system.feasibility   import (
    feasibility, FeasibilityStatus, ResourceBalance)


@pytest.fixture(scope="module")
def engine():
    return get("gt_system_v2")


def _manual_defaults(engine):
    """Defaults pinned to manual modes so libr_frac / load_pct overrides
    take effect — the feasibility tests target the original v1-trusted
    operating point semantics."""
    v = engine.defaults()
    v["gt_power_mode"]     = 1     # manual
    v["steam_split_mode"]  = 1     # manual
    v["operating_mode"]    = 0     # island
    return v


# ── shape ────────────────────────────────────────────────────────────────────

def test_feasibility_carries_two_balances(engine):
    f = engine.solve(engine.defaults())["feasibility"]
    assert isinstance(f, FeasibilityStatus)
    names = [b.resource for b in f.balances]
    assert "Power" in names
    assert "Cooling capacity" in names


def test_aggregate_feasible_iff_every_balance_passes():
    a = ResourceBalance("A", "kW", True,  100, 50,  +50, 0,   "", {})
    b = ResourceBalance("B", "kW", True,  100, 50,  +50, 0,   "", {})
    c = ResourceBalance("C", "kW", False,  50, 100, -50, 50,  "", {})
    assert FeasibilityStatus([a, b]).feasible is True
    assert FeasibilityStatus([a, c]).feasible is False


# ── defaults reveal a real cooling deficit ───────────────────────────────────

def test_manual_legacy_power_feasible_cooling_deficit(engine):
    """v1-legacy manual operating point (load_pct=85, libr_frac=0.5,
    island): GT supplies enough kW but LiBr undersized for 5 MW GPU
    cooling demand — the original ~1660 kW cooling gap."""
    f = engine.solve(_manual_defaults(engine))["feasibility"]
    power   = f.by("Power")
    cooling = f.by("Cooling capacity")
    assert power.feasible
    assert power.balance > 0
    assert not cooling.feasible
    assert 1500 < cooling.shortfall < 1800, (
        f"cooling shortfall {cooling.shortfall:.0f} kW outside ~1660 band")
    assert f.feasible is False


# ── higher LiBr split closes the cooling gap ────────────────────────────────

def test_higher_libr_split_makes_cooling_feasible(engine):
    """libr_frac=0.85 sends most steam to the chiller. Cooling supply jumps
    above the GPU heat demand and the aggregate becomes feasible."""
    v = _manual_defaults(engine); v["libr_frac"] = 0.85
    f = engine.solve(v)["feasibility"]
    assert f.by("Cooling capacity").feasible
    assert f.by("Cooling capacity").supply > f.by("Cooling capacity").demand
    assert f.feasible


def test_grid_mode_default_feasible(engine):
    """Grid mode at defaults: GT auto-ramps to cool GPU; export covers excess."""
    v = engine.defaults(); v["operating_mode"] = 1   # grid_tied
    f = engine.solve(v)["feasibility"]
    assert f.feasible
    assert f.by("Cooling capacity").feasible


# ── cooling-balance contents are auditable ──────────────────────────────────

def test_cooling_breakdown_lists_silicon_overhead_and_libr(engine):
    """Cassette overhead is split out so the report shows that the cooling
    side must absorb BOTH silicon heat AND in-cassette overhead (pumps,
    controls etc)."""
    c = engine.solve(_manual_defaults(engine))["feasibility"].by("Cooling capacity")
    assert set(c.breakdown.keys()) == {
        "LiBr cooling capacity", "GPU silicon heat", "Cassette overhead heat"}
    assert c.unit == "kW"
    assert c.breakdown["GPU silicon heat"] > 0
    assert c.breakdown["Cassette overhead heat"] > 0
    assert c.breakdown["LiBr cooling capacity"] > 0
    # Total demand equals silicon + overhead.
    assert abs(c.demand - (c.breakdown["GPU silicon heat"]
                           + c.breakdown["Cassette overhead heat"])) < 1e-6


def test_cooling_assumption_text_present(engine):
    c = engine.solve(_manual_defaults(engine))["feasibility"].by("Cooling capacity")
    assert "immersion" in c.assumption.lower()
    assert "libr" in c.assumption.lower()


def test_power_assumption_reflects_operating_mode(engine):
    """Island and grid get different assumption strings — the report should
    never read as if the mode could be misinterpreted."""
    island = engine.solve(_manual_defaults(engine))["feasibility"].by("Power")
    v = engine.defaults(); v["operating_mode"] = 1
    grid = engine.solve(v)["feasibility"].by("Power")
    assert "island" in island.assumption.lower()
    assert "grid" in grid.assumption.lower() and "export-only" in grid.assumption.lower()


# ── power balance: structure still itemised at screening fidelity ───────────

def test_power_breakdown_itemises_supply_info_and_every_demand(engine):
    """Breakdown shows derated supply ceiling, current operating point + headroom
    (info-only rows), and every demand component including the cassette overhead
    split-out from silicon. In island mode, an External load line is present."""
    p = engine.solve(_manual_defaults(engine))["feasibility"].by("Power")
    for k in (
        "GT derated capacity (available)",
        "GT current output (info)",
        "Operating headroom (info)",
        "GPU silicon (IT power)",
        "Cassette overhead (pumps/ctl)",
        "MED electrical (pumps)",
        "LiBr pump electrical",
        "Cooling tower fan electrical",
        "GT auxiliaries",
        "Plant BoP (lights/HVAC)",
        "External load (island, manual)",
    ):
        assert k in p.breakdown, f"missing {k!r}"
        assert p.breakdown[k] is not None, f"{k} must be modelled"
    assert p.supply == p.breakdown["GT derated capacity (available)"]
    assert p.supply > p.breakdown["GT current output (info)"]


def test_grid_mode_breakdown_has_grid_export_line(engine):
    """Grid mode: the external load line is replaced by Grid export
    (computed, positive-only)."""
    v = engine.defaults(); v["operating_mode"] = 1
    p = engine.solve(v)["feasibility"].by("Power")
    assert "Grid export (computed, export-only)" in p.breakdown
    assert "External load (island, manual)" not in p.breakdown
    assert p.breakdown["Grid export (computed, export-only)"] >= 0


def test_each_block_emits_its_own_aux_row(engine):
    from nexablock.blocks import GasTurbine, LiBrChiller, CoolingTower
    solved = engine.solve(engine.defaults())["solved"]
    for cls, label in [
        (GasTurbine,   "GT aux electrical"),
        (LiBrChiller,  "LiBr pump electrical"),
        (CoolingTower, "CT fan electrical"),
    ]:
        b = next(b for b in solved.blocks if isinstance(b, cls))
        assert label in b.results
        assert b.results[label].value > 0


def test_bop_frac_zeroes_facility_load(engine):
    v = engine.defaults(); v["bop_frac"] = 0.0
    f = engine.solve(v)["feasibility"]
    assert f.by("Power").breakdown["Plant BoP (lights/HVAC)"] == 0.0


# ── high-GPU case fails BOTH balances ───────────────────────────────────────

def test_high_gpu_load_fails_both_power_and_cooling(engine):
    """gpu_it_kW=10000 in MANUAL mode at the v1-legacy operating point
    (load_pct=85, libr_frac=0.5): both balances fail. With derated as
    supply, the power shortfall is smaller (~1630 kW vs ~3000 kW at
    operating point)."""
    v = _manual_defaults(engine); v["gpu_it_kW"] = 10000.0
    f = engine.solve(v)["feasibility"]
    p = f.by("Power")
    c = f.by("Cooling capacity")
    assert not p.feasible
    assert not c.feasible
    assert 1500 < p.shortfall < 1800
    assert 6500 < c.shortfall < 7200
    assert not f.feasible


# ── feasibility independent of convergence ──────────────────────────────────

def test_feasibility_is_independent_of_convergence(engine):
    """Acyclic GT system always converges; feasibility lives separately."""
    r = engine.solve(engine.defaults())
    assert r["solved"].convergence.converged is True   # solver fine
    assert r["feasibility"].feasible is False          # cooling deficit
