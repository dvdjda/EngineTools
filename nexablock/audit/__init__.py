"""Nexa Block v2 — universal post-solve audit layer."""
from .checks  import (CheckResult, mass_balance, energy_balance,
                      pass_fail, bounds_check)
from .status  import AuditStatus
from .auditor import audit

__all__ = [
    "CheckResult", "AuditStatus", "audit",
    "mass_balance", "energy_balance", "pass_fail", "bounds_check",
]
