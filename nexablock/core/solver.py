"""
nexablock.core.solver — Sequential-modular solver with recycle (Wegstein).

Algorithm:
  1. Build the directed block graph from connections.
  2. Detect loops (Tarjan SCC).
  3. If acyclic: solve in topological order.
  4. If loops: choose tear streams, iterate with Wegstein acceleration
     until all tear residuals < tol, then do one final topo pass.
"""
from __future__ import annotations
from typing import TYPE_CHECKING
import logging

if TYPE_CHECKING:
    from .block  import Block
    from .system import Connection

log = logging.getLogger(__name__)


class Solver:
    def __init__(self, blocks: list, connections: list,
                 tol: float = 1e-4, max_iter: int = 50) -> None:
        self.blocks      = blocks
        self.connections = connections
        self.tol         = tol
        self.max_iter    = max_iter
        self.convergence_info: dict = {}

    # ── public ────────────────────────────────────────────────────────────────

    def run(self) -> None:
        """Solve. Raises on unconnected required inlets or non-convergence."""
        # Propagate connections: outlet stream → inlet port
        self._wire_connections()
        # Check required inlets
        self._check_inlets()

        # Detect SCCs
        loops = self._find_loops()

        if not loops:
            order = self._topo_order(self.blocks, self.connections)
            self._forward_pass(order)
            self.convergence_info = {"loops": 0, "acyclic": True}
        else:
            self._solve_with_recycle(loops)

    # ── wiring ────────────────────────────────────────────────────────────────

    def _wire_connections(self) -> None:
        """Attach src outlet stream object to dst inlet port."""
        for c in self.connections:
            # The stream lives on the src outlet port
            # dst inlet port gets the same object reference
            dst_port = c.dst_block.inlets[c.dst_port]
            # For now attach a sentinel so the solver can fill it later
            # We'll update after compute() fills the outlet
            dst_port._src_conn = c   # type: ignore[attr-defined]

    def _check_inlets(self) -> None:
        """Raise on any required inlet that has no connection or pre-set stream."""
        connected_dst = {(c.dst_block, c.dst_port) for c in self.connections}
        for block in self.blocks:
            for name, port in block.inlets.items():
                already_seeded = port.stream is not None
                if port.required and (block, name) not in connected_dst and not already_seeded:
                    raise RuntimeError(
                        f"{type(block).__name__}.{name} inlet not connected")

    # ── topology ──────────────────────────────────────────────────────────────

    def _adjacency(self):
        adj: dict = {b: [] for b in self.blocks}
        for c in self.connections:
            adj[c.src_block].append(c.dst_block)
        return adj

    def _topo_order(self, blocks, connections) -> list:
        """Kahn's algorithm topological sort."""
        adj = {b: [] for b in blocks}
        in_deg = {b: 0 for b in blocks}
        for c in connections:
            if c.src_block in adj and c.dst_block in adj:
                adj[c.src_block].append(c.dst_block)
                in_deg[c.dst_block] += 1
        queue = [b for b in blocks if in_deg[b] == 0]
        order = []
        while queue:
            node = queue.pop(0)
            order.append(node)
            for nxt in adj[node]:
                in_deg[nxt] -= 1
                if in_deg[nxt] == 0:
                    queue.append(nxt)
        if len(order) != len(blocks):
            # Has cycles — return partial order for the acyclic portion
            remaining = [b for b in blocks if b not in order]
            order += remaining
        return order

    def _find_loops(self) -> list[list]:
        """Return list of SCCs with >1 block (Tarjan's algorithm)."""
        adj = self._adjacency()
        index_counter = [0]
        stack = []
        lowlink: dict = {}
        index: dict   = {}
        on_stack: dict = {}
        sccs = []

        def strongconnect(v):
            index[v]   = index_counter[0]
            lowlink[v] = index_counter[0]
            index_counter[0] += 1
            stack.append(v)
            on_stack[v] = True
            for w in adj.get(v, []):
                if w not in index:
                    strongconnect(w)
                    lowlink[v] = min(lowlink[v], lowlink[w])
                elif on_stack.get(w):
                    lowlink[v] = min(lowlink[v], index[w])
            if lowlink[v] == index[v]:
                scc = []
                while True:
                    w = stack.pop()
                    on_stack[w] = False
                    scc.append(w)
                    if w is v:
                        break
                if len(scc) > 1:
                    sccs.append(scc)

        for v in self.blocks:
            if v not in index:
                strongconnect(v)
        return sccs

    # ── forward pass ─────────────────────────────────────────────────────────

    def _forward_pass(self, order: list) -> None:
        """Run compute() in topological order, propagating streams."""
        for block in order:
            # Attach inlet streams from connected outlet ports
            for c in self.connections:
                if c.dst_block is block:
                    src_stream = c.src_block.outlets[c.src_port].stream
                    block.inlets[c.dst_port].stream = src_stream
            block.results.clear()      # idempotent compute (recycle re-invokes)
            block.compute()
            log.debug("Computed %s", type(block).__name__)

    # ── recycle solver ────────────────────────────────────────────────────────

    def _solve_with_recycle(self, loops: list) -> None:
        """Wegstein iteration for recycle loops."""
        # Choose tear: one connection per loop (the first intra-loop connection)
        tears = self._choose_tears(loops)
        log.info("Recycle loops detected. Tears: %s", tears)

        # Seed tears with initial guesses (zero/default stream)
        from .stream import Stream, StreamKind
        for tear_conn in tears:
            if tear_conn.dst_block.inlets[tear_conn.dst_port].stream is None:
                # seed with a zero-ish copy of the source outlet if available
                src_s = tear_conn.src_block.outlets[tear_conn.src_port].stream
                guess = src_s.copy() if src_s is not None else \
                        Stream(kind=StreamKind.WATER_STEAM, mdot=1.0,
                               T=400.0, P=1e6, h=2.8e6)
                tear_conn.dst_block.inlets[tear_conn.dst_port].stream = guess

        # Build acyclic order excluding tear connections
        non_tear_conns = [c for c in self.connections if c not in tears]
        order = self._topo_order(self.blocks, non_tear_conns)

        # Wegstein state — keyed by id(conn) since Connection is not hashable
        prev_x: dict = {}   # id(tear_conn) → previous assumed stream
        prev_fx: dict = {}  # id(tear_conn) → previous computed stream

        loop_info = []
        for iteration in range(self.max_iter):
            # Forward pass with current tear guesses
            for block in order:
                for c in self.connections:
                    if c.dst_block is block and c not in tears:
                        src_s = c.src_block.outlets[c.src_port].stream
                        block.inlets[c.dst_port].stream = src_s
                block.results.clear()      # idempotent compute per iteration
                block.compute()

            # Check tear residuals; update using Wegstein
            max_res = 0.0
            for tc in tears:
                computed = tc.src_block.outlets[tc.src_port].stream
                assumed  = tc.dst_block.inlets[tc.dst_port].stream
                res = assumed.residual(computed) if assumed and computed else 1.0
                max_res = max(max_res, res)

                # Wegstein update for mdot, T, P
                if assumed and computed:
                    new_stream = computed.copy()
                    k = id(tc)
                    if k in prev_x and k in prev_fx:
                        new_stream = self._wegstein_update(
                            assumed, computed, prev_x[k], prev_fx[k])
                    prev_x[k]  = assumed.copy()
                    prev_fx[k] = computed.copy()
                    tc.dst_block.inlets[tc.dst_port].stream = new_stream

            loop_info.append(max_res)
            log.debug("Recycle iter %d  max_res=%.4e", iteration + 1, max_res)
            if max_res < self.tol:
                break
        else:
            raise RuntimeError(
                f"Recycle did not converge after {self.max_iter} iterations. "
                f"Final residual: {max_res:.4e}. History: {loop_info[-5:]}")

        # Final forward pass with converged tears
        self._forward_pass(order)
        self.convergence_info = {
            "loops": len(loops),
            "iterations": len(loop_info),
            "final_residual": loop_info[-1],
            "converged": loop_info[-1] < self.tol,
        }

    def _choose_tears(self, loops: list) -> list:
        """One tear connection per loop — pick the one with most downstream flow."""
        tears = []
        for loop in loops:
            loop_set = set(id(b) for b in loop)
            for c in self.connections:
                if id(c.src_block) in loop_set and id(c.dst_block) in loop_set:
                    tears.append(c)
                    break
        return tears

    def _wegstein_update(self, x, fx, px, pfx):
        """Bounded Wegstein update for a single stream."""
        new = fx.copy()
        for attr in ("mdot", "T", "P", "h", "power"):
            xv  = getattr(x,   attr)
            fxv = getattr(fx,  attr)
            pxv = getattr(px,  attr)
            pfxv= getattr(pfx, attr)
            if None in (xv, fxv, pxv, pfxv) or xv == pxv:
                if fxv is not None:
                    setattr(new, attr, fxv)
                continue
            q = (fxv - pfxv) / (xv - pxv)
            q = max(-5.0, min(0.0, q))   # bounded Wegstein
            updated = (1 - q) * fxv + q * xv if q != 0 else fxv
            setattr(new, attr, updated)
        return new
