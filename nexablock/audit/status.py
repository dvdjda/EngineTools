"""nexablock.audit.status — aggregate audit status + per-KPI coverage lookup."""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class AuditStatus:
    checks: list = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.passed for c in self.checks)

    def failed(self) -> list:
        return [c for c in self.checks if not c.passed]

    def by_category(self) -> dict:
        out: dict = {}
        for c in self.checks:
            out.setdefault(c.category, []).append(c)
        return out

    def coverage_for(self, kpi_label: str) -> str:
        """Return 'passed' | 'failed' | 'uncovered' for a given engine KPI label.

        Drives the per-row basis in the results table: a KPI vouched for by
        a check that passed gets to keep its engine-declared basis ("verified"
        typically). A KPI named by any failed check goes "unverified". A KPI
        no check ever names goes "screening" — honest about lack of coverage.
        """
        covering = [c for c in self.checks if kpi_label in c.affects]
        if not covering:
            return "uncovered"
        if all(c.passed for c in covering):
            return "passed"
        return "failed"

    def generic_failures(self) -> list:
        """Failed checks with no specific affects list — these flag the whole
        system as unverified (e.g. P12 negative-flow violations don't name a
        specific KPI but invalidate all of them)."""
        return [c for c in self.failed() if not c.affects]
