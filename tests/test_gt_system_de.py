"""
tests/test_gt_system_de.py — the double-effect GT System engine (gt_system_v2_de).

Verifies the new engine is a faithful copy of the single-effect one with a
double-effect chiller swapped in, that it does NOT disturb the trusted
single-effect engine, and that the double-effect physics behave (more cooling
and more rejection-driven MED per unit steam, plus the steam-grade check).
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
import nexa_toolkit.engines                       # noqa: registers engines
from nexa_toolkit.framework import get
from nexablock.blocks import LiBrChiller, DoubleEffectLiBrChiller


def test_de_engine_registered_and_trusted():
    e = get("gt_system_v2_de")
    assert e.name == "GT System v2 — nexablock (GT + HRSG + 2xLiBr + GPU + MED)"
    assert e.status == "trusted"                   # promoted by David


def test_de_default_cop_is_double_effect_band():
    e = get("gt_system_v2_de")
    cop = next(i.default for i in e.inputs if i.key == "libr_cop")
    assert cop == pytest.approx(1.20)


def test_de_uses_double_effect_block_subclassing_libr():
    e = get("gt_system_v2_de")
    s = e.solve(e.defaults())["solved"]
    ch = next(b for b in s.blocks if isinstance(b, LiBrChiller))  # subclass matches
    assert isinstance(ch, DoubleEffectLiBrChiller)
    assert abs(ch.results["COP achieved"].value - 1.20) < 1e-6
    assert ch.results["Number of effects"].value == 2.0
    assert ch.results["Second-effect cooling gain"].value > 0


def test_de_delivers_more_cooling_and_more_med_than_single_effect():
    """Same scenario (grid-tied): double-effect (COP 1.2) gives more cooling and
    more rejection-driven MED water than single-effect (COP 0.7) from the GT."""
    se = get("gt_system_v2"); de = get("gt_system_v2_de")
    ks = se.solve(dict(se.defaults(), operating_mode=1))["kpis"]
    kd = de.solve(dict(de.defaults(), operating_mode=1))["kpis"]
    assert kd["LiBr cooling kW"] > 1.4 * ks["LiBr cooling kW"]   # ~1.7× ideal
    assert kd["MED water m3day"] > ks["MED water m3day"]


def test_de_has_steam_grade_check_and_passes_at_10bar():
    e = get("gt_system_v2_de")
    a = e.solve(e.defaults())["audit"]
    names = [c.name for c in a.checks]
    assert any(n.startswith("T11") for n in names)       # double-effect steam-grade check
    assert a.passed                                       # 10 bar steam is hot enough


def test_de_flags_low_grade_steam():
    """Drop steam pressure so the HTG steam is too cool — T11 must fail."""
    e = get("gt_system_v2_de")
    a = e.solve(dict(e.defaults(), steam_p_bar=1))["audit"]
    t11 = next(c for c in a.checks if c.name.startswith("T11"))
    assert not t11.passed


def test_de_results_itemise_pumps_and_fan_with_two_libr_pumps():
    """Sizing rows: every pump + the fan appear as kW result rows, and the
    double-effect chiller shows TWO solution pumps (HT + LT), not one."""
    e = get("gt_system_v2_de")
    r = e.solve(e.defaults())
    labels = [o.label for o in e.outputs(r)]
    assert any("LiBr HT solution pump" in l for l in labels)
    assert any("LiBr LT solution pump" in l for l in labels)
    assert not any("LiBr chiller pump" in l for l in labels)   # not the single-effect label
    for pump in ("Dielectric coolant pump", "Cooling-loop pump", "HRSG feed-water pump",
                 "Seawater intake pump", "Dry-cooler fan (VSD)", "Plant aux TOTAL"):
        assert any(pump in l for l in labels), pump


def test_de_auto_med_bypass_holds_hrsg_return_setpoint():
    """Auto MED-bypass mode: the MED loop-out (cooling-loop temp into the
    radiator/HRSG return) is held at the feedwater set-point fw_t_C, by opening
    the bypass when MED would otherwise over-cool below it."""
    from nexablock.blocks import MED
    e = get("gt_system_v2_de")
    for fw in (60.0, 80.0):
        v = dict(e.defaults(), operating_mode=1, med_bypass_mode=1, fw_t_C=fw)
        s = e.solve(v)["solved"]
        med = next(b for b in s.blocks if isinstance(b, MED))
        assert abs(med.results["MED loop-out temp"].value - fw) < 1.0, fw
        assert 0.0 < med.results["MED bypass"].value < 100.0   # bypass actively engaged


def test_de_manual_med_bypass_still_works():
    from nexablock.blocks import MED
    e = get("gt_system_v2_de")
    v = dict(e.defaults(), operating_mode=1, med_bypass_mode=0, med_bypass_frac=0.3)
    s = e.solve(v)["solved"]
    med = next(b for b in s.blocks if isinstance(b, MED))
    assert abs(med.results["MED bypass"].value - 30.0) < 1.0


def test_single_effect_med_unchanged_by_auto_mode():
    """The trusted single-effect engine never sets the auto mode → its MED runs
    manual with loop-cold = fw (unchanged)."""
    from simulators.gt_system.system import GTSystemParams
    p = GTSystemParams()
    assert p.med_bypass_mode == "manual"


def test_single_effect_engine_unchanged():
    """The trusted single-effect engine still uses the plain LiBrChiller (not the
    double-effect subclass) and its default COP is 0.70."""
    e = get("gt_system_v2")
    cop = next(i.default for i in e.inputs if i.key == "libr_cop")
    assert cop == pytest.approx(0.70)
    s = e.solve(e.defaults())["solved"]
    ch = next(b for b in s.blocks if isinstance(b, LiBrChiller))
    assert not isinstance(ch, DoubleEffectLiBrChiller)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
