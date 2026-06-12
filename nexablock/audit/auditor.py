"""
nexablock.audit.auditor — run the audit on a SolvedSystem.

Walks every block's audit_checks(), appends any system-level extras,
then sweeps two framework-generic safety nets (P12 no-negative-flows,
P13 finite kW values). Block check failures are caught defensively —
a bug in one check never silences the rest.
"""
from __future__ import annotations
import math

from .checks import CheckResult, pass_fail
from .status import AuditStatus


def audit(solved, extra_checks: list = None) -> AuditStatus:
    """Run every audit check against a SolvedSystem. Returns AuditStatus."""
    extra_checks = list(extra_checks or [])
    results: list = []

    # Per-block declared checks
    for block in solved.blocks:
        try:
            for check in block.audit_checks():
                results.append(_normalise(check))
        except Exception as e:
            results.append(CheckResult(
                name=f"{type(block).__name__}.audit_checks() raised",
                category="(framework)", passed=False,
                measure="pass/fail",
                detail=str(e), affects=[], error=str(e),
            ))

    # System-level extras
    for check in extra_checks:
        results.append(_normalise(check))

    # Framework generic checks
    results.extend(_generic_checks(solved))

    return AuditStatus(checks=results)


def _normalise(c) -> CheckResult:
    """Allow either CheckResult or a 0-arg callable returning CheckResult."""
    if isinstance(c, CheckResult):
        return c
    if callable(c):
        try:
            result = c()
            if isinstance(result, CheckResult):
                return result
        except Exception as e:
            return CheckResult(
                name="(check raised)", category="(framework)", passed=False,
                measure="pass/fail", detail=str(e), affects=[], error=str(e),
            )
    return CheckResult(
        name="(unknown check)", category="(framework)", passed=False,
        measure="pass/fail",
        detail=f"unknown check type: {type(c).__name__}", affects=[],
    )


def _generic_checks(solved) -> list:
    """Framework-level safety nets — apply to every block uniformly.
    Failures have empty affects so the renderer treats them as global
    flags rather than per-KPI flips."""
    results = []

    # P12 — no negative stream mass flows anywhere
    violations = []
    for block in solved.blocks:
        for name, port in {**block.inlets, **block.outlets}.items():
            s = port.stream
            if s is not None and s.mdot is not None and s.mdot < 0:
                violations.append(
                    f"{type(block).__name__}.{name}: ṁ={s.mdot:.3g} kg/s")
    results.append(pass_fail(
        name="P12: no negative flows",
        passed=not violations,
        detail=("all stream ṁ ≥ 0" if not violations
                else "violations: " + "; ".join(violations)),
        category="Plausibility",
        affects=[],
    ))

    # P13 — every kW result row holds a finite value
    non_finite = []
    for block in solved.blocks:
        for label, res in block.results.items():
            if res.unit in ("kW", "kWh"):
                if not math.isfinite(res.value):
                    non_finite.append(
                        f"{type(block).__name__}.{label}={res.value}")
    results.append(pass_fail(
        name="P13: finite kW values",
        passed=not non_finite,
        detail=("all kW values finite" if not non_finite
                else "non-finite: " + "; ".join(non_finite)),
        category="Plausibility",
        affects=[],
    ))

    return results
