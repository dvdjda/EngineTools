"""
nexablock.validation.reference — Reference and TestCase dataclasses.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, TYPE_CHECKING

if TYPE_CHECKING:
    from ..core.stream import Stream


@dataclass
class Reference:
    source: str
    note:   str   = ""
    kind:   Literal["correlation","standard","manufacturer","oracle"] = "correlation"

    def __str__(self) -> str:
        return f"{self.source}" + (f" ({self.note})" if self.note else "")


@dataclass
class TestCase:
    """
    A block self-test. The validation runner instantiates the block,
    feeds inlets, calls compute(), and checks outputs against expected.
    """
    params:   dict                        # block constructor kwargs
    inlets:   dict[str, "Stream"]         # name → Stream
    expected: dict[str, float]            # result label → expected value
    tol:      float = 0.02                # relative tolerance (default 2%)
    note:     str   = ""
