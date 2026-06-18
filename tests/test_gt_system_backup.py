"""
tests/test_gt_system_backup.py — the Tier-3 Backup engine (gt_system_v2_de_backup).

Diesel standby prime mover (GT-failure switch), wet cooling tower in place of the
radiator, LiBr-failure switch, and the resilience KPIs (autonomy / ride-through).
The two existing engines must stay byte-identical (covered by the other suites).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import nexa_toolkit.engines                       # noqa: registers engines
from nexa_toolkit.framework import get
from nexablock.blocks import (GasTurbine, DieselGenset, Radiator,
                              CoolingTowerLoop, DoubleEffectLiBrChiller)


@pytest.fixture(scope="module")
def e():
    return get("gt_system_v2_de_backup")


def test_backup_engine_registered_draft(e):
    assert e.name.endswith("+ Backup)")
    assert e.status == "draft"


def test_normal_uses_gt_and_cooling_tower(e):
    """Default (no failures): GT prime mover, but the dry radiator is replaced by
    the wet cooling tower, and the chiller is double-effect."""
    s = e.solve(dict(e.defaults(), operating_mode=1))["solved"]
    pm = next(b for b in s.blocks if isinstance(b, GasTurbine))
    rj = next(b for b in s.blocks if isinstance(b, Radiator))
    assert not isinstance(pm, DieselGenset)        # GT
    assert isinstance(rj, CoolingTowerLoop)        # tower, not dry radiator
    assert any(isinstance(b, DoubleEffectLiBrChiller) for b in s.blocks)


def test_gt_failure_switches_to_diesel(e):
    v = dict(e.defaults(), operating_mode=1, gpu_it_kW=1000, gt_status=1)
    r = e.solve(v); s = r["solved"]
    pm = next(b for b in s.blocks if isinstance(b, GasTurbine))
    assert isinstance(pm, DieselGenset)            # diesel took over
    assert s.convergence.converged
    assert r["resilience"]["on_diesel"]
    # diesel exhaust drives the DE chiller but only partly → tower must top up
    assert r["resilience"]["tower_topup_kW"] > 0


def test_libr_failure_loads_tower_with_full_gpu_heat(e):
    v = dict(e.defaults(), operating_mode=1, gpu_it_kW=1000, libr_status=1)
    b = e.solve(v)["resilience"]
    assert b["libr_cooling_kW"] == 0.0
    assert abs(b["tower_topup_kW"] - b["gpu_heat_kW"]) < 1.0   # tower carries it all


def test_resilience_kpis_present_and_flag_targets(e):
    # small fuel tank → autonomy below the 72 h target should be flagged
    v = dict(e.defaults(), operating_mode=1, gpu_it_kW=1000, gt_status=1,
             diesel_tank_m3=10.0, backup_hours_target=72.0)
    b = e.solve(v)["resilience"]
    assert b["diesel_autonomy_h"] < 72.0 and not b["fuel_target_met"]
    # UPS + accumulator ride-through computed and positive
    assert b["ups_ride_min"] > 0 and b["thermal_bridge_min"] > 0


def test_tower_direct_cooling_infeasible_at_high_wetbulb(e):
    """At a high wet-bulb the tower can't cool the dielectric to 30 °C directly."""
    v = dict(e.defaults(), operating_mode=1, libr_status=1,
             tower_wetbulb_C=33.0, tower_approach_K=5.0)   # supply 38 > 30
    b = e.solve(v)["resilience"]
    assert not b["tower_direct_ok"]


def test_backup_failure_modes_keep_m7_closed(e):
    """Fixed-flow dielectric pump + cooling-tower top-up: the GPU coolant mass
    balance (M7) stays closed in every failure mode (regression — it used to fail
    -59% when the diesel-LiBr was short and the tower wasn't in the loop)."""
    for ov in ({"gt_status": 1}, {"libr_status": 1}, {"gt_status": 1, "libr_status": 1}):
        r = e.solve(dict(e.defaults(), operating_mode=1, gpu_it_kW=1000, **ov))
        fails = [c.name for c in r["audit"].failed()]
        assert not any(n.startswith("M7") for n in fails), (ov, fails)
        assert r["feasibility"].feasible


def test_resilience_kpis_always_finite(e):
    """Autonomy / water-buffer are backup DESIGN metrics → always finite, even in
    normal operation (regression: they used to return inf and trip the non-finite
    output guard / 'balances do not close' alert)."""
    import math
    for ov in ({}, {"gt_status": 1}, {"libr_status": 1}):
        r = e.solve(dict(e.defaults(), operating_mode=1, **ov))
        for o in e.outputs(r):
            assert not (isinstance(o.value, float) and math.isinf(o.value)), o.label
        b = r["resilience"]
        assert math.isfinite(b["diesel_autonomy_h"])
        assert math.isfinite(b["water_buffer_days"])


def test_backup_cooling_balance_closes_via_tower(e):
    """In a GT failure the diesel-LiBr alone is short, but the cooling tower
    top-up closes the cooling balance (feasible), so the run isn't flagged as a
    non-closing balance."""
    r = e.solve(dict(e.defaults(), operating_mode=1, gpu_it_kW=1000, gt_status=1))
    cb = r["feasibility"].by("Cooling capacity")
    assert cb.feasible and "Cooling-tower top-up" in cb.breakdown
    assert cb.breakdown["Cooling-tower top-up"] > 0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
