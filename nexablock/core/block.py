"""
nexablock.core.block — Block base class (THE CONTRACT).

Every block in the library implements exactly this interface.
The framework touches nothing else.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .port    import Port
    from .quantity import Param, Result
    from ..validation.reference import Reference, TestCase


class Block(ABC):
    """Abstract base for every process block.

    Subclass must implement:
        params()     → dict[str, Param]
        inlets()     → dict[str, Port]
        outlets()    → dict[str, Port]
        compute()    → None   (fills outlet streams and self.results)

    Optionally override:
        references() → list[Reference]
        test_cases() → list[TestCase]
        label        (string shown on SVG / report)
        category     (used for SVG colouring)
    """

    # ── class-level metadata (override in subclass) ───────────────────────────
    category: str = "Generic"
    label:    str = ""

    # ── instance state ────────────────────────────────────────────────────────
    def __init__(self) -> None:
        self.results: dict[str, "Result"] = {}
        self._inlets:  dict[str, "Port"] | None = None
        self._outlets: dict[str, "Port"] | None = None
        self._params:  dict[str, "Param"] | None = None

    # ── required interface ────────────────────────────────────────────────────

    @abstractmethod
    def _build_params(self) -> dict[str, "Param"]:
        """Return the parameter dict. Called once and cached."""

    @abstractmethod
    def _build_inlets(self) -> dict[str, "Port"]:
        """Return inlet port dict. Called once and cached."""

    @abstractmethod
    def _build_outlets(self) -> dict[str, "Port"]:
        """Return outlet port dict. Called once and cached."""

    @abstractmethod
    def compute(self) -> None:
        """Execute physics. Read inlet streams + params; set outlet streams;
        populate self.results (dict[str, Result])."""

    # ── optional interface ────────────────────────────────────────────────────

    def references(self) -> list:
        return []

    def test_cases(self) -> list:
        return []

    def render_ports(self) -> dict[str, tuple[float, float]]:
        """Relative (x,y) anchor per port for SVG layout. Default: auto."""
        return {}

    # ── accessors (lazy, cached) ──────────────────────────────────────────────

    @property
    def params(self) -> dict[str, "Param"]:
        if self._params is None:
            self._params = self._build_params()
        return self._params

    @property
    def inlets(self) -> dict[str, "Port"]:
        if self._inlets is None:
            self._inlets = self._build_inlets()
        return self._inlets

    @property
    def outlets(self) -> dict[str, "Port"]:
        if self._outlets is None:
            self._outlets = self._build_outlets()
        return self._outlets

    # ── helpers ───────────────────────────────────────────────────────────────

    def _p(self, name: str) -> float:
        """Return param value by name (SI). Raises KeyError if missing."""
        return self.params[name].value

    def _in(self, name: str):
        """Return inlet stream. Raises RuntimeError if not connected."""
        port = self.inlets.get(name)
        if port is None:
            raise KeyError(f"{type(self).__name__}: unknown inlet '{name}'")
        if port.stream is None:
            if port.required:
                raise RuntimeError(
                    f"{type(self).__name__}.{name} inlet not connected")
            return None
        return port.stream

    def _out_set(self, name: str, stream) -> None:
        """Set outlet stream. Raises KeyError if port not found."""
        if name not in self.outlets:
            raise KeyError(f"{type(self).__name__}: unknown outlet '{name}'")
        self.outlets[name].stream = stream

    def _result(self, label: str, value: float, unit: str,
                basis: str = "screening", ref: str = "") -> "Result":
        from .quantity import Result
        if label in self.results:
            prev = self.results[label]
            raise ValueError(
                f"{type(self).__name__}: duplicate result label {label!r} "
                f"(previous: {prev.value:g} {prev.unit}, "
                f"new: {value:g} {unit}). "
                f"Use distinct labels (e.g. {label + ' ' + unit!r})."
            )
        r = Result(value=value, unit=unit, basis=basis, label=label, reference=ref)
        self.results[label] = r
        return r

    def __repr__(self) -> str:
        return (f"{type(self).__name__}("
                f"label={self.label!r}, "
                f"in={list(self.inlets)}, "
                f"out={list(self.outlets)})")
