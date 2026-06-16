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
    """Defaults pinned to manual GT power so the load_pct=85 override takes
    effect — the feasibility tests target the original v1-trusted operating
    point semantics. (The steam splitter is gone; all steam → LiBr.)"""
    v = engine.defaults()
    v["gt_power_mode"]     = 1     # manual
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

def test_manual_island_excess_power(engine):
    """Manual island operating point (load_pct=85): GT produces ~7905 kW
    but NEXA only consumes ~5797 kW — ~2100 kW of excess electrical with
    no sink in island. Power balance flags as 'didn't close' (excess >
    tolerance). With all steam → LiBr the chiller is now oversized at
    load_pct=85, so cooling is feasible — the excess-power finding is the
    one that stands."""
    f = engine.solve(_manual_defaults(engine))["feasibility"]
    power   = f.by("Power")
    cooling = f.by("Cooling capacity")
    # Power: not feasible because supply > demand and there's no sink (island).
    assert not power.feasible
    assert power.balance > 0                    # excess
    assert power.shortfall > 1000               # |excess| ≈ 2100 kW
    # Cooling: all steam → LiBr, oversized at this load → feasible.
    assert cooling.feasible
    assert cooling.supply > cooling.demand
    assert f.feasible is False                  # power excess fails aggregate


# ── all steam → LiBr keeps cooling comfortably above GPU heat ───────────────

def test_manual_island_cooling_supply_exceeds_demand(engine):
    """All HRSG steam drives the chiller, so cooling supply sits well above
    GPU heat demand → cooling balance feasible.
    NOTE: aggregate.feasible is still False in manual island because of the
    power-bus excess (load_pct=85 produces more than NEXA consumes);
    cooling is the assertion of interest here."""
    f = engine.solve(_manual_defaults(engine))["feasibility"]
    assert f.by("Cooling capacity").feasible
    assert f.by("Cooling capacity").supply > f.by("Cooling capacity").demand


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

def test_power_breakdown_uses_actual_supply_and_lists_every_consumer(engine):
    """The breakdown shows GT actual power as supply, derated capacity as
    info, every demand component including the cassette overhead split-out
    from silicon, and an External load line in island mode."""
    p = engine.solve(_manual_defaults(engine))["feasibility"].by("Power")
    for k in (
        "GT actual power (supply)",
        "Derated capacity (max available)",
        "GPU silicon (IT power)",
        "Cassette overhead (pumps/ctl)",
        "MED electrical (pumps)",
        "LiBr pump electrical",
        "Radiator fan electrical",
        "GT auxiliaries",
        "Plant BoP (lights/HVAC)",
        "External load (island, manual)",
    ):
        assert k in p.breakdown, f"missing {k!r}"
        assert p.breakdown[k] is not None, f"{k} must be modelled"
    # Supply is actual, not derated.
    assert p.supply == p.breakdown["GT actual power (supply)"]
    assert p.breakdown["Derated capacity (max available)"] >= p.supply


def test_grid_mode_breakdown_has_grid_export_line(engine):
    """Grid mode: the external load line is replaced by 'Grid export
    (sent to grid)' which counts toward demand so the bus closes."""
    v = engine.defaults(); v["operating_mode"] = 1
    p = engine.solve(v)["feasibility"].by("Power")
    assert "Grid export (sent to grid)" in p.breakdown
    assert "External load (island, manual)" not in p.breakdown
    assert p.breakdown["Grid export (sent to grid)"] >= 0


def test_each_block_emits_its_own_aux_row(engine):
    from nexablock.blocks import GasTurbine, LiBrChiller, Radiator
    # Route some rejection around MED so the radiator actually sheds heat
    # (at med_bypass_frac=0 all rejection goes to MED → radiator fan = 0).
    v = engine.defaults(); v["med_bypass_frac"] = 0.3
    solved = engine.solve(v)["solved"]
    for cls, label in [
        (GasTurbine,   "GT aux electrical"),
        (LiBrChiller,  "LiBr pump electrical"),
        (Radiator,     "Radiator fan electrical"),
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
    """gpu_it_kW=10000 in MANUAL legacy island. NEXA demand exceeds
    GT actual power (load_pct=85 → ~7905 kW) → power deficit. LiBr
    undersized → cooling deficit. Both fail."""
    v = _manual_defaults(engine); v["gpu_it_kW"] = 10000.0
    f = engine.solve(v)["feasibility"]
    p = f.by("Power")
    c = f.by("Cooling capacity")
    assert not p.feasible
    assert not c.feasible
    # Power deficit: demand ~11050, supply 7905 → shortfall ~3140
    assert 2800 < p.shortfall < 3400
    # Cooling deficit: LiBr supply ~7179 vs demand 10500 → shortfall ~3320.
    assert 3000 < c.shortfall < 3600
    assert not f.feasible


# ── feasibility independent of convergence ──────────────────────────────────

def test_feasibility_is_independent_of_convergence(engine):
    """Acyclic GT system always converges; feasibility lives separately.

    At island/auto defaults (GPU 5 MW) the 1.9% cooling gap is within
    screening tolerance (2.5%) — both convergence and feasibility read
    clean. To exercise the cooling-DEFICIT path use GPU 10 MW.
    """
    r = engine.solve(engine.defaults())
    assert r["solved"].convergence.converged is True   # solver fine
    assert r["feasibility"].feasible is True           # within screening tolerance

    # Demonstrate the deficit path is still reached at real-shortfall sizes:
    v = engine.defaults(); v["gpu_it_kW"] = 10000.0
    r2 = engine.solve(v)
    assert r2["solved"].convergence.converged is True
    assert r2["feasibility"].feasible is False         # real 20% cooling deficit
