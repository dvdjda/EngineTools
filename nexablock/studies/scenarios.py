"""
nexablock.studies.scenarios — named bundles of parameter overrides.

A Scenario is a partial override on the base params with a name and
optional description. ScenarioRunner.run([...]) solves every scenario
through the same builder + kpi_fn used by sweep/sensitivity and returns
a comparison table.

    runner = ScenarioRunner(build_gt_system, GTSystemParams(), summary)

    result = runner.run({
        "summer peak":     {"t_ambient_C": 40.0, "load_pct": 100.0},
        "winter low load": {"t_ambient_C":  5.0, "load_pct":  40.0},
    })
    # or equivalently:
    result = runner.run([
        Scenario("summer peak",     {"t_ambient_C": 40.0, "load_pct": 100.0}),
        Scenario("winter low load", {"t_ambient_C":  5.0, "load_pct":  40.0}),
    ])

Override keys are validated against the base dataclass fields **before
any solve runs** — a typo'd field raises ValueError, never silently
ignored.
"""
from __future__ import annotations
from dataclasses import dataclass, field, fields, replace
from typing import Any, Callable, Iterable


@dataclass
class Scenario:
    """Named bundle of overrides on the base params."""
    name:        str
    overrides:   dict
    description: str = ""


@dataclass
class ScenarioPoint:
    """One solved scenario."""
    name:        str
    description: str
    overrides:   dict
    kpis:        dict
    converged:   bool = True
    error:       str | None = None


@dataclass
class ScenarioResult:
    base_params: Any
    base_kpis:   dict
    points:      list = field(default_factory=list)

    def get(self, name: str) -> ScenarioPoint:
        for p in self.points:
            if p.name == name:
                return p
        raise KeyError(f"scenario {name!r} not in result")

    def kpi(self, name: str) -> dict:
        """{scenario_name: value} for the named KPI across all scenarios."""
        return {p.name: p.kpis.get(name) for p in self.points}

    def diff_vs_base(self, name: str) -> dict:
        """{scenario_name: (value − base_value)} for the named KPI."""
        base_v = self.base_kpis.get(name)
        if base_v is None:
            return {p.name: None for p in self.points}
        return {p.name: (p.kpis.get(name) - base_v if p.kpis.get(name) is not None else None)
                for p in self.points}

    def as_dataframe(self, include_base: bool = False):
        """Wide table: rows = scenarios (index), columns = KPIs + status.

        Lazy-imports pandas. Raises with an install hint if not available."""
        try:
            import pandas as pd
        except ImportError as e:
            raise ImportError(
                "ScenarioResult.as_dataframe requires pandas. "
                "Install with: pip install pandas") from e

        rows, index = [], []
        if include_base:
            index.append("base")
            rows.append({**self.base_kpis, "converged": True, "error": None})
        for p in self.points:
            index.append(p.name)
            rows.append({**p.kpis, "converged": p.converged, "error": p.error})
        return pd.DataFrame(rows, index=index)


class ScenarioRunner:
    """Solve a batch of named scenarios through the same builder + kpi_fn.

    Args:
        builder:     callable(BaseParams) -> SolvedSystem
        base_params: a dataclass instance — the reference point
        kpi_fn:      callable(SolvedSystem) -> dict[str, float]
    """

    def __init__(self,
                 builder:     Callable[[Any], Any],
                 base_params: Any,
                 kpi_fn:      Callable[[Any], dict]) -> None:
        self.builder     = builder
        self.base_params = base_params
        self.kpi_fn      = kpi_fn

    def run(self, scenarios) -> ScenarioResult:
        scenario_list = self._normalise(scenarios)
        self._check_duplicate_names(scenario_list)
        self._validate_overrides(scenario_list)

        base_solved = self.builder(self.base_params)
        base_kpis   = self.kpi_fn(base_solved)
        result      = ScenarioResult(base_params=self.base_params, base_kpis=base_kpis)

        for sc in scenario_list:
            try:
                params = replace(self.base_params, **sc.overrides)
                solved = self.builder(params)
                kpis   = self.kpi_fn(solved)
                result.points.append(ScenarioPoint(
                    name=sc.name, description=sc.description,
                    overrides=sc.overrides, kpis=kpis))
            except Exception as e:
                result.points.append(ScenarioPoint(
                    name=sc.name, description=sc.description,
                    overrides=sc.overrides, kpis={},
                    converged=False, error=str(e)))
        return result

    # ── helpers ──────────────────────────────────────────────────────────────

    def _normalise(self, scenarios) -> list:
        """Accept dict[str, dict] or Iterable[Scenario]; return list[Scenario]."""
        if isinstance(scenarios, dict):
            return [Scenario(name=k, overrides=dict(v)) for k, v in scenarios.items()]
        out = []
        for s in scenarios:
            if not isinstance(s, Scenario):
                raise TypeError(
                    f"Scenario list must contain Scenario instances, got {type(s).__name__}")
            out.append(s)
        return out

    def _check_duplicate_names(self, scenario_list) -> None:
        seen = set()
        dups = []
        for s in scenario_list:
            if s.name in seen:
                dups.append(s.name)
            seen.add(s.name)
        if dups:
            raise ValueError(f"Duplicate scenario name(s): {dups}")

    def _validate_overrides(self, scenario_list) -> None:
        """Fail loud on any override key that isn't a real base-params field."""
        valid = {f.name for f in fields(self.base_params)}
        bad = []   # (scenario_name, unknown_key)
        for s in scenario_list:
            for k in s.overrides:
                if k not in valid:
                    bad.append((s.name, k))
        if bad:
            details = ", ".join(f"{n!r}:{k!r}" for n, k in bad)
            raise ValueError(
                f"Unknown override(s) for {type(self.base_params).__name__}: "
                f"{details}. Valid fields: {sorted(valid)}")
