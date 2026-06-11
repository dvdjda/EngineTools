"""
nexablock.studies.sweep — parameter sweep over a System builder.

The primitive: given a (builder, base_params, kpi_fn) triple, run the
builder on every combination of overridden inputs in a grid and collect
the KPIs into a SweepResult.

    sweep  = ParameterSweep(build_gt_system, GTSystemParams(), summary)
    result = sweep.run({"load_pct": [70, 80, 90, 100]})           # 1D
    result = sweep.run({"load_pct": [70,100], "libr_frac":[0.3,0.7]})  # N-D

Knows nothing about GT, blocks or the solver. Composes builder × params
× kpis. Any system that follows the builder + summary pattern gets
sweeps for free.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields, replace
from itertools import product
from typing import Any, Callable, Iterable


@dataclass
class SweepPoint:
    """One point in a sweep: the overrides, the KPIs, plus status."""
    inputs:    dict
    kpis:      dict
    converged: bool          = True
    error:     str | None    = None


@dataclass
class SweepResult:
    """All points + a few extraction helpers. Pandas is optional."""
    base_params: Any
    varied:      list
    points:      list = field(default_factory=list)

    def kpi(self, name: str) -> list:
        """Return the named KPI series across points (NaN on miss)."""
        return [p.kpis.get(name, float("nan")) for p in self.points]

    def input(self, name: str) -> list:
        """Return the named input series across points."""
        return [p.inputs.get(name) for p in self.points]

    def as_dataframe(self):
        """Return a wide DataFrame: one row per point, columns = inputs + KPIs + status.

        Lazy-imports pandas. Raises with an install hint if not available."""
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "SweepResult.as_dataframe requires pandas. "
                "Install with: pip install pandas") from e
        rows = []
        for p in self.points:
            row = {**{f"in.{k}": v for k, v in p.inputs.items()},
                   **{f"kpi.{k}": v for k, v in p.kpis.items()},
                   "converged": p.converged,
                   "error":     p.error}
            rows.append(row)
        return pd.DataFrame(rows)


class ParameterSweep:
    """Sweep a builder over a grid of input overrides.

    Args:
        builder:     callable(BaseParams) -> SolvedSystem (or anything kpi_fn understands).
        base_params: a dataclass instance whose fields will be overridden per point.
        kpi_fn:      callable(SolvedSystem) -> dict[str, float] — extracts the KPIs.
    """

    def __init__(self,
                 builder:     Callable[[Any], Any],
                 base_params: Any,
                 kpi_fn:      Callable[[Any], dict]) -> None:
        self.builder     = builder
        self.base_params = base_params
        self.kpi_fn      = kpi_fn

    def run(self, grid: dict[str, Iterable]) -> SweepResult:
        """Run the sweep. grid maps param-name → iterable of values."""
        self._validate_fields(grid.keys())
        names  = list(grid.keys())
        result = SweepResult(base_params=self.base_params, varied=names)

        for combo in product(*(list(grid[n]) for n in names)):
            overrides = dict(zip(names, combo))
            try:
                point_params = replace(self.base_params, **overrides)
                solved       = self.builder(point_params)
                kpis         = self.kpi_fn(solved)
                result.points.append(SweepPoint(inputs=overrides, kpis=kpis))
            except Exception as e:
                result.points.append(SweepPoint(
                    inputs=overrides, kpis={}, converged=False, error=str(e)))
        return result

    def _validate_fields(self, names) -> None:
        """Fail fast on a typo'd param name rather than during replace()."""
        valid = {f.name for f in fields(self.base_params)}
        unknown = [n for n in names if n not in valid]
        if unknown:
            raise ValueError(
                f"Unknown parameter(s) for {type(self.base_params).__name__}: "
                f"{unknown}. Valid fields: {sorted(valid)}")
