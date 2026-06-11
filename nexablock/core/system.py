"""
nexablock.core.system — System: add(), connect(), solve().
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .block  import Block
    from .stream import Stream


@dataclass
class Connection:
    src_block:  "Block"
    src_port:   str
    dst_block:  "Block"
    dst_port:   str


class System:
    """
    Declarative wiring of Block instances.

    Usage::
        sys = System("GT System")
        gt   = sys.add(GasTurbine(...))
        hrsg = sys.add(HRSG(...))
        sys.connect(gt.outlets["exhaust"], hrsg.inlets["exhaust"])
        result = sys.solve()
    """

    def __init__(self, name: str = "System") -> None:
        self.name:        str              = name
        self._blocks:     list["Block"]    = []
        self._connections: list[Connection] = []

    # ── building ──────────────────────────────────────────────────────────────

    def add(self, block: "Block") -> "Block":
        """Register a block and return it (for chaining)."""
        self._blocks.append(block)
        return block

    def connect(self, src_port, dst_port) -> None:
        """
        Wire src_port (outlet) to dst_port (inlet).
        Accepts Port objects directly.
        """
        # Find which block owns each port
        src_block, src_name = self._find_port(src_port, "out")
        dst_block, dst_name = self._find_port(dst_port, "in")
        self._connections.append(
            Connection(src_block, src_name, dst_block, dst_name))

    # ── solving ───────────────────────────────────────────────────────────────

    def solve(self) -> "SolvedSystem":
        """Solve the system and return a SolvedSystem."""
        from .solver import Solver
        solver = Solver(self._blocks, self._connections)
        solver.run()
        return SolvedSystem(self, solver.convergence_info)

    # ── internal helpers ──────────────────────────────────────────────────────

    def _find_port(self, port, direction: str):
        """Return (block, port_name) for a Port object."""
        for block in self._blocks:
            ports = block.outlets if direction == "out" else block.inlets
            for name, p in ports.items():
                if p is port:
                    return block, name
        raise ValueError(
            f"Port {port!r} not found in any registered block "
            f"(direction={direction!r})")

    def _adjacency(self) -> dict["Block", list["Block"]]:
        """Directed adjacency list: src_block → [dst_block]."""
        adj: dict["Block", list["Block"]] = {b: [] for b in self._blocks}
        for c in self._connections:
            adj[c.src_block].append(c.dst_block)
        return adj

    @property
    def blocks(self) -> list["Block"]:
        return list(self._blocks)

    @property
    def connections(self) -> list[Connection]:
        return list(self._connections)


@dataclass
class SolvedSystem:
    """Result of System.solve() — carries the wired system + convergence info."""
    system:           System
    convergence_info: dict = field(default_factory=dict)

    @property
    def blocks(self):
        return self.system.blocks

    @property
    def connections(self):
        return self.system.connections
