"""
nexablock.core.quantity — typed result value with provenance.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal

Basis = Literal["input", "verified", "screening", "unverified"]


@dataclass
class Result:
    """A scalar simulation output with metadata."""
    value:     float
    unit:      str
    basis:     Basis = "screening"
    label:     str   = ""
    reference: str   = ""   # e.g. "CoolProp IAPWS-IF97", "ASHRAE ch.30"

    def __repr__(self) -> str:
        return f"Result({self.value:.4g} {self.unit}, basis={self.basis!r})"

    def formatted(self, fmt: str = "{:.4g}") -> str:
        return fmt.format(self.value)


@dataclass
class Param:
    """A block input parameter with bounds and units."""
    value:   float
    unit:    str
    default: float | None = None
    min:     float | None = None
    max:     float | None = None
    desc:    str          = ""

    def validate(self) -> None:
        if self.min is not None and self.value < self.min:
            raise ValueError(f"Param {self.desc!r}: {self.value} < min {self.min}")
        if self.max is not None and self.value > self.max:
            raise ValueError(f"Param {self.desc!r}: {self.value} > max {self.max}")
