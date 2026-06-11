"""
tests/test_core.py — Step 1 §7.1 verification.

Tests:
  1. Units: round-trip conversions.
  2. Props: steam properties against NIST reference values.
  3. Contract: a minimal concrete Block subclass.
  4. Recycle: a 2-block loop must converge.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from nexablock.core.units    import to_si, from_si, convert
from nexablock.core.quantity import Result, Param
from nexablock.core.stream   import Stream, StreamKind
from nexablock.core.port     import Port
from nexablock.core.block    import Block
from nexablock.core.system   import System
from nexablock.core.recycle  import Recycle
from nexablock.core import props


# ── 1. Units ──────────────────────────────────────────────────────────────────

def test_pressure_conversions():
    assert abs(to_si(10.0, "bar") - 1e6) < 1.0
    assert abs(from_si(1e5, "bar") - 1.0) < 1e-9
    assert abs(convert(1.0, "MPa", "bar") - 10.0) < 1e-9

def test_temperature_conversions():
    assert abs(to_si(100.0, "°C") - 373.15) < 1e-9
    assert abs(from_si(373.15, "°C") - 100.0) < 1e-9
    assert abs(to_si(0.0, "°C") - 273.15) < 1e-9

def test_massflow_conversions():
    assert abs(convert(1.0, "t/h", "kg/s") - 1000/3600) < 1e-9
    assert abs(convert(3600.0, "kg/h", "kg/s") - 1.0) < 1e-9


# ── 2. Props ──────────────────────────────────────────────────────────────────

def test_t_sat_10bar():
    """T_sat at 10 bar should be ~179.9°C = 453.05 K"""
    T = props.t_sat(10e5)
    assert abs(T - 453.03) < 1.0, f"T_sat(10bar) = {T:.2f} K"

def test_h_steam_10bar_210C():
    """h_steam at 10 bar, 210°C (NIST: 2852 kJ/kg = 2.852e6 J/kg)"""
    h = props.h_steam(10e5, 210 + 273.15)
    assert abs(h - 2.852e6) / 2.852e6 < 0.005, f"h_steam = {h/1e3:.1f} kJ/kg"

def test_h_water_80C():
    """h_water at 80°C, 10 bar (NIST: ~335 kJ/kg)"""
    h = props.h_water(10e5, 80 + 273.15)
    assert abs(h - 335e3) / 335e3 < 0.01, f"h_water = {h/1e3:.1f} kJ/kg"


# ── 3. Block contract ─────────────────────────────────────────────────────────

class Heater(Block):
    """Trivial block: heats a water stream by adding Q kW."""
    category = "Exchangers"; label = "Heater"

    def __init__(self, Q_kW: float = 1000.0):
        super().__init__()
        self._Q_kW = Q_kW

    def _build_params(self):
        return {"Q": Param(self._Q_kW * 1e3, "W", desc="duty")}

    def _build_inlets(self):
        return {"inlet": Port("inlet", StreamKind.WATER_STEAM, "in")}

    def _build_outlets(self):
        return {"outlet": Port("outlet", StreamKind.WATER_STEAM, "out")}

    _CP = 4187.0   # J/kg/K  water cp
    def compute(self):
        s = self._in("inlet")
        dh   = self._p("Q") / s.mdot
        h_out = (s.h or 0.0) + dh
        dT    = dh / self._CP
        out   = s.copy(); out.h = h_out; out.T = (s.T or 300.0) + dT
        self._out_set("outlet", out)
        self._result("Duty", self._p("Q") / 1e3, "kW", "verified")


class Cooler(Block):
    """Trivial block: cools a water stream by removing Q kW."""
    category = "Exchangers"; label = "Cooler"

    def __init__(self, Q_kW: float = 800.0):
        super().__init__()
        self._Q_kW = Q_kW

    def _build_params(self):
        return {"Q": Param(self._Q_kW * 1e3, "W", desc="duty")}

    def _build_inlets(self):
        return {"inlet": Port("inlet", StreamKind.WATER_STEAM, "in")}

    def _build_outlets(self):
        return {"outlet": Port("outlet", StreamKind.WATER_STEAM, "out")}

    _CP = 4187.0
    def compute(self):
        s   = self._in("inlet")
        dh  = self._p("Q") / s.mdot
        h_out = (s.h or 0.0) - dh
        dT    = dh / self._CP
        out   = s.copy(); out.h = h_out; out.T = (s.T or 300.0) - dT
        self._out_set("outlet", out)
        self._result("Duty removed", self._p("Q") / 1e3, "kW", "verified")


def test_block_contract():
    h = Heater(Q_kW=500.0)
    s = Stream.water_steam(mdot=2.0, T=300.0, P=2e5, h=1.2e5)
    h.inlets["inlet"].stream = s
    h.compute()
    out = h.outlets["outlet"].stream
    assert out is not None
    assert out.h > s.h
    assert "Duty" in h.results


def test_duplicate_result_label_raises():
    """Block._result must fail loud on duplicate labels.

    Root cause of the MED 24× bug (m3/day overwritten by m3/h) and the
    latent gas_turbine NG-consumption overwrite. Distinct labels per
    metric/unit pair is the convention; silent overwrites are not."""
    h = Heater(Q_kW=500.0)
    s = Stream.water_steam(mdot=2.0, T=300.0, P=2e5, h=1.2e5)
    h.inlets["inlet"].stream = s
    h.compute()                                              # registers "Duty"
    with pytest.raises(ValueError, match="duplicate result label"):
        h._result("Duty", 999.0, "kW", "verified")


# ── 4. 2-block recycle loop ────────────────────────────────────────────────────

def _build_recycle_loop(heater_kW: float = 100.0, cooler_kW: float = 100.0,
                         tol: float = 1e-4):
    """Heater → Cooler → Recycle → (back to Heater).
    Balanced (default) → fixed point exists. Imbalanced → diverges,
    used to force non-convergence in the failure-mode tests."""
    sys = System("recycle-test")
    heater  = sys.add(Heater(Q_kW=heater_kW))
    cooler  = sys.add(Cooler(Q_kW=cooler_kW))
    recycle = sys.add(Recycle(StreamKind.WATER_STEAM, tol=tol))
    seed = Stream.water_steam(mdot=2.0, T=300.0, P=2e5, h=1.2e5)
    recycle.inlets["inlet"].stream = seed                     # break the seed=src trick
    sys.connect(heater.outlets["outlet"],  cooler.inlets["inlet"])
    sys.connect(cooler.outlets["outlet"],  recycle.inlets["inlet"])
    sys.connect(recycle.outlets["outlet"], heater.inlets["inlet"])
    return sys, recycle


def test_recycle_converges():
    """Balanced loop must converge and report per-loop status."""
    sys, recycle = _build_recycle_loop(tol=1e-4)
    result = sys.solve()
    conv = result.convergence
    assert conv.converged
    assert not conv.acyclic
    assert len(conv.loops) == 1
    L = conv.loops[0]
    assert L.converged
    assert L.iterations >= 1
    assert L.iterations < 50
    assert L.final_residual < L.tolerance
    assert L.reason is None
    assert "Heater" in L.name and "Cooler" in L.name and "Recycle" in L.name
    res = recycle.results.get("Recycle residual")
    assert res is not None and res.value < 1e-4


def test_acyclic_system_reports_converged_no_loops():
    """No SCC → trivially converged, loops list empty."""
    sys = System("acyclic")
    heater = sys.add(Heater(Q_kW=100.0))
    heater.inlets["inlet"].stream = Stream.water_steam(
        mdot=2.0, T=300.0, P=2e5, h=1.2e5)
    result = sys.solve()
    conv = result.convergence
    assert conv.converged
    assert conv.acyclic
    assert conv.loops == []


def test_recycle_not_converged_imbalanced_loop_reports_failure():
    """Imbalanced duties (Heater=200, Cooler=50) → no fixed point. Solver
    must NOT raise; it returns with convergence.converged=False, reason
    naming max-iter, and the final forward pass still populates block
    results so the renderer can show them flagged-as-unreliable."""
    sys, _ = _build_recycle_loop(heater_kW=200.0, cooler_kW=50.0)
    result = sys.solve()                # default tol/max_iter
    conv = result.convergence
    assert not conv.converged
    assert len(conv.loops) == 1
    L = conv.loops[0]
    assert not L.converged
    assert L.iterations == 50            # hit max_iter
    assert L.final_residual > L.tolerance
    assert "max iter" in (L.reason or "").lower()
    h = next(b for b in result.blocks if isinstance(b, Heater))
    assert "Duty" in h.results           # final pass still ran


def test_convergence_summary_lines():
    """Pure unit tests of the helper that PDF/Excel/UI all consume."""
    from nexablock.core.convergence import (
        ConvergenceStatus, LoopStatus, convergence_summary)

    # Acyclic
    text, ok = convergence_summary(ConvergenceStatus(True, []))
    assert ok and "no recycle loops" in text

    # Converged with loop
    L_ok = LoopStatus(name="A→B", blocks=["A", "B"], tear="B.x → A.y",
                       converged=True, iterations=7,
                       final_residual=4.2e-5, tolerance=1e-4)
    text, ok = convergence_summary(ConvergenceStatus(True, [L_ok]))
    assert ok
    assert "converged in 7 iterations" in text
    assert "4.20e-05" in text or "4.2e-05" in text
    assert "1.0e-04" in text

    # Not converged
    L_bad = LoopStatus(name="X→Y", blocks=["X", "Y"], tear="Y.a → X.b",
                       converged=False, iterations=50,
                       final_residual=0.31, tolerance=1e-20,
                       reason="max iterations reached")
    text, ok = convergence_summary(ConvergenceStatus(False, [L_bad]))
    assert not ok
    assert "NOT CONVERGED" in text
    assert "X→Y" in text
    assert "after 50 iterations" in text
    assert "max iterations reached" in text


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
