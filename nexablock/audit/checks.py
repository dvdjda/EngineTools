"""
nexablock.audit.checks — CheckResult dataclass + helper constructors.

Each Block.audit_checks() returns a list of CheckResult — the framework
just collects them, so block authors don't have to think about a Check
protocol or callable wrapping.
"""
from __future__ import annotations
from dataclasses import dataclass, field


@dataclass
class CheckResult:
    """One audit check's outcome — supply/demand, pass/fail, or bounds."""
    name:      str
    category:  str                # "Energy closure" | "Mass closure" | "Second law" | "Plausibility"
    passed:    bool
    measure:   str                # "supply/demand/balance" | "pass/fail" | "bounds"
    supply:    float | None = None
    demand:    float | None = None
    balance:   float | None = None
    tolerance: float | None = None
    detail:    str = ""
    affects:   list = field(default_factory=list)
    error:     str | None = None


def mass_balance(name: str, supply: float, demand: float, *,
                 affects: list, tol_rel: float = 1e-4,
                 unit: str = "kg/s") -> CheckResult:
    """Relative-tolerance mass closure check."""
    balance = supply - demand
    denom   = max(abs(supply), abs(demand), 1e-12)
    passed  = abs(balance) / denom <= tol_rel
    return CheckResult(
        name=name, category="Mass closure", passed=passed,
        measure="supply/demand/balance",
        supply=supply, demand=demand, balance=balance, tolerance=tol_rel,
        detail=(f"in {supply:.4g} {unit}, out {demand:.4g} {unit}, "
                f"residual {balance:+.3g} {unit} "
                f"({abs(balance)/denom*100:.4f}%)"),
        affects=list(affects),
    )


def energy_balance(name: str, supply: float, demand: float, *,
                   affects: list, tol_rel: float = 1e-3,
                   unit: str = "kW") -> CheckResult:
    """Relative-tolerance energy closure check."""
    balance = supply - demand
    denom   = max(abs(supply), abs(demand), 1e-12)
    passed  = abs(balance) / denom <= tol_rel
    return CheckResult(
        name=name, category="Energy closure", passed=passed,
        measure="supply/demand/balance",
        supply=supply, demand=demand, balance=balance, tolerance=tol_rel,
        detail=(f"in {supply:.4g} {unit}, out {demand:.4g} {unit}, "
                f"residual {balance:+.3g} {unit} "
                f"({abs(balance)/denom*100:.4f}%)"),
        affects=list(affects),
    )


def pass_fail(name: str, passed: bool, detail: str, *,
              category: str, affects: list) -> CheckResult:
    """Boolean check — temperature feasibility, structural invariants."""
    return CheckResult(
        name=name, category=category, passed=passed,
        measure="pass/fail", detail=detail, affects=list(affects),
    )


def bounds_check(name: str, value: float, lo: float, hi: float, *,
                 unit: str = "", affects: list,
                 category: str = "Plausibility") -> CheckResult:
    """Value-in-range plausibility check."""
    passed = lo <= value <= hi
    return CheckResult(
        name=name, category=category, passed=passed,
        measure="bounds",
        balance=value,
        detail=f"value {value:.4g} {unit}, bounds [{lo:.4g}, {hi:.4g}] {unit}",
        affects=list(affects),
    )
