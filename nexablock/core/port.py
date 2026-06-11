"""
nexablock.core.port — Port and connection management.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .stream import Stream, StreamKind


@dataclass
class Port:
    """A block's inlet or outlet."""
    name:      str
    kind:      "StreamKind"
    direction: Literal["in", "out"]
    required:  bool             = True    # False = optional (e.g. bypass)
    stream:    Optional["Stream"] = field(default=None, repr=False)

    def is_connected(self) -> bool:
        return self.stream is not None

    def __repr__(self) -> str:
        connected = "✓" if self.is_connected() else "○"
        return f"Port({self.direction}:{self.name} {connected})"
