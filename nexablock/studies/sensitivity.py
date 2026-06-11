"""
nexablock.studies.sensitivity — one-at-a-time sensitivity.

Around a base parameter point, perturb each input with a central finite
difference and compute the effect on each chosen KPI. Returns raw dY/dX
plus a normalised elasticity (% change in KPI per % change in input) so
inputs are comparable and rankable tornado-style.

Reuses ParameterSweep under the hood — each perturbation is a 2-point
sweep over a single input.

    sens = OneAtATimeSensitivity(
        builder=build_gt_system, base_params=GTSystemParams(),
        kpi_fn=summary, rel_step=0.01,
        bounds={"load_pct": (10, 100), ...},
        step_override={"med_effects": 1.0},
    )
    result = sens.run(
        inputs=["load_pct", "gt_eff", "libr_frac", ...],
        kpis  =["Steam generation t/h", "MED water m3day", ...],
    )
"""
from __future__ import annotations
from dataclasses import dataclass, field, replace
from math import nan, isnan
from typing import Any, Callable

from .sweep import ParameterSweep


@dataclass
class SensitivityEntry:
    """One (input × KPI) pair."""
    input:      str
    kpi:        str
    base_input: float
    base_kpi:   float
    step:       float          # h requested (pre-clamp)
    span:       float          # X_high − X_low actually used (asymmetric near a bound)
    dY_dX:      float
    elasticity: float          # (dY/dX) × (X₀ / Y₀)   NaN if Y₀ == 0
    low_input:  float
    high_input: float
    low_kpi:    float
    high_kpi:   float
    error:      str | None = None


@dataclass
class SensitivityResult:
    base_params: Any
    base_kpis:   dict
    entries:     list = field(default_factory=list)

    def for_kpi(self, kpi: str) -> list:
        return [e for e in self.entries if e.kpi == kpi]

    def for_input(self, name: str) -> list:
        return [e for e in self.entries if e.input == name]

    def tornado(self, kpi: str) -> list:
        """Entries for one KPI sorted by |elasticity| descending. NaNs go last."""
        items = self.for_kpi(kpi)
        def key(e):
            v = e.elasticity
            return (-1 if isnan(v) else 0, -abs(v) if not isnan(v) else 0)
        return sorted(items, key=key)

    def as_dataframe(self):
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "SensitivityResult.as_dataframe requires pandas. "
                "Install with: pip install pandas") from e
        rows = [{
            "input":      e.input,
            "kpi":        e.kpi,
            "base_input": e.base_input,
            "base_kpi":   e.base_kpi,
            "dY_dX":      e.dY_dX,
            "elasticity": e.elasticity,
            "step":       e.step,
            "span":       e.span,
            "low_input":  e.low_input,
            "high_input": e.high_input,
            "low_kpi":    e.low_kpi,
            "high_kpi":   e.high_kpi,
            "error":      e.error,
        } for e in self.entries]
        return pd.DataFrame(rows)


class OneAtATimeSensitivity:
    """OAT central-difference sensitivity built on ParameterSweep.

    Args:
        builder:       (BaseParams) -> SolvedSystem
        base_params:   dataclass instance of base inputs
        kpi_fn:        (SolvedSystem) -> dict[str, float]
        rel_step:      relative perturbation around X₀ (default 1%)
        abs_step:      fallback when |X₀|·rel_step is ~0 (default 0.01)
        bounds:        {input_name: (lo, hi)} physical limits — optional
        step_override: {input_name: absolute_step} per-input override — optional
    """

    def __init__(self,
                 builder:       Callable[[Any], Any],
                 base_params:   Any,
                 kpi_fn:        Callable[[Any], dict],
                 rel_step:      float = 0.01,
                 abs_step:      float = 0.01,
                 bounds:        dict[str, tuple[float, float]] | None = None,
                 step_override: dict[str, float] | None = None) -> None:
        self.builder       = builder
        self.base_params   = base_params
        self.kpi_fn        = kpi_fn
        self.rel_step      = rel_step
        self.abs_step      = abs_step
        self.bounds        = bounds or {}
        self.step_override = step_override or {}
        self._sweep = ParameterSweep(builder, base_params, kpi_fn)

    def run(self, inputs: list, kpis: list) -> SensitivityResult:
        # Validate input names up front (reuse sweep's check).
        self._sweep._validate_fields(inputs)

        # Base solve, once.
        base_solved = self.builder(self.base_params)
        base_kpis   = self.kpi_fn(base_solved)
        result      = SensitivityResult(base_params=self.base_params, base_kpis=base_kpis)

        for name in inputs:
            X0 = float(getattr(self.base_params, name))
            h  = self._step_for(name, X0)
            lo, hi = self._clamp(name, X0 - h, X0 + h)

            sweep_pts = self._sweep.run({name: [lo, hi]}).points
            p_lo, p_hi = sweep_pts[0], sweep_pts[1]

            span = hi - lo
            for kpi in kpis:
                Y0 = float(base_kpis.get(kpi, nan))
                err = None

                if not (p_lo.converged and p_hi.converged):
                    err = (p_lo.error or "") + "; " + (p_hi.error or "")
                    Y_lo = Y_hi = dY = eps = nan
                elif span == 0.0:
                    err = "clamped both sides (span=0)"
                    Y_lo = float(p_lo.kpis.get(kpi, nan))
                    Y_hi = float(p_hi.kpis.get(kpi, nan))
                    dY = eps = nan
                else:
                    Y_lo = float(p_lo.kpis.get(kpi, nan))
                    Y_hi = float(p_hi.kpis.get(kpi, nan))
                    dY   = (Y_hi - Y_lo) / span
                    eps  = dY * (X0 / Y0) if Y0 not in (0.0, nan) and not isnan(Y0) else nan

                result.entries.append(SensitivityEntry(
                    input=name, kpi=kpi,
                    base_input=X0, base_kpi=Y0,
                    step=h, span=span,
                    dY_dX=dY, elasticity=eps,
                    low_input=lo, high_input=hi,
                    low_kpi=Y_lo, high_kpi=Y_hi,
                    error=err,
                ))
        return result

    # ── helpers ──────────────────────────────────────────────────────────────

    def _step_for(self, name: str, X0: float) -> float:
        if name in self.step_override:
            return float(self.step_override[name])
        rel = abs(X0) * self.rel_step
        return rel if rel > 0 else self.abs_step

    def _clamp(self, name: str, lo: float, hi: float) -> tuple[float, float]:
        if name not in self.bounds:
            return lo, hi
        b_lo, b_hi = self.bounds[name]
        return max(lo, b_lo), min(hi, b_hi)
