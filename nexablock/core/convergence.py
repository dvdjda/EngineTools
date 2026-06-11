"""
nexablock.core.convergence — per-loop convergence status + one-line summary.

LoopStatus carries everything needed to explain whether a single recycle
tear made it: name, blocks in the SCC, the torn connection, the iteration
count it took, the final residual, the tolerance it was held to, and a
reason if it failed.

ConvergenceStatus aggregates across the system: converged iff every loop
converged (or no loops). The acyclic case is trivially converged.

convergence_summary(status) produces the human-readable line that the
PDF / Excel / live UI all show.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class LoopStatus:
    name:           str                  # e.g. "Heater→Cooler→Recycle"
    blocks:         list                 # block class names in the SCC
    tear:           str                  # "Src.port → Dst.port"
    converged:      bool
    iterations:     int
    final_residual: float
    tolerance:      float
    reason:         str | None = None    # set when not converged


@dataclass
class ConvergenceStatus:
    converged: bool                       # all loops OK, or no loops at all
    loops:     list = field(default_factory=list)

    @property
    def acyclic(self) -> bool:
        return len(self.loops) == 0


def convergence_summary(status) -> tuple[str, bool]:
    """Return (one-line summary, ok flag). Caller uses the flag for styling.

    Acyclic:          "converged (no recycle loops)"
    All loops OK:     "converged in N iterations, residual X < tol Y"
    Any loop failed:  "NOT CONVERGED — loop <name>, residual X > tol Y after N iterations"
    """
    if status is None:
        return ("no convergence info", True)

    if status.acyclic:
        return ("converged (no recycle loops)", True)

    if status.converged:
        # All loops converged. Report the worst residual + iteration count.
        worst = max(status.loops, key=lambda L: L.final_residual)
        return (
            f"converged in {worst.iterations} iterations, "
            f"residual {worst.final_residual:.2e} < tol {worst.tolerance:.1e}",
            True,
        )

    # At least one loop failed. Name the first failure explicitly.
    bad = next(L for L in status.loops if not L.converged)
    return (
        f"NOT CONVERGED — loop {bad.name}, "
        f"residual {bad.final_residual:.2e} > tol {bad.tolerance:.1e} "
        f"after {bad.iterations} iterations"
        + (f" ({bad.reason})" if bad.reason else ""),
        False,
    )
