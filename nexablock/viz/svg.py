"""
nexablock.viz.svg — SVG renderer for System / SolvedSystem.

Reads only the public contract:
    Block.label, Block.category, Block.render_ports()
    System.blocks, System.connections
    Port.kind  (for stroke colour)

Layout
------
Blocks are placed left→right by longest-path rank from the sources.
Within a rank, blocks stack vertically. No edge-crossing minimisation —
sufficient for the GT-system topology.

Ports
-----
If Block.render_ports() supplies a relative (x,y) for the port (each
component in [0,1] of the block box), use it. Otherwise distribute
inlets evenly on the left edge and outlets on the right.

Styling
-------
Block fill keyed off Block.category; connection stroke keyed off the
source outlet Port.kind (StreamKind).
"""
from __future__ import annotations


BLOCK_W  = 140
BLOCK_H  = 80
RANK_GAP = 200
ROW_GAP  = 30
MARGIN   = 40

_CATEGORY_FILL = {
    "Power":        "#FFD479",
    "HeatExchange": "#FFB07A",
    "Cooling":      "#7FC4E5",
    "Utility":      "#C7C7C7",
    "DataCenter":   "#B19CD9",
    "Desalination": "#7FE5C4",
    "Generic":      "#E0E0E0",
}

_STREAM_STROKE = {
    "WATER_STEAM":   "#1F77B4",
    "ENERGY":        "#D62728",
    "ELECTRICAL":    "#FFB000",
    "GENERIC_FLUID": "#17BECF",
}


def render(system_or_solved) -> str:
    """Return a self-contained SVG string for a System or SolvedSystem."""
    sys_ = system_or_solved.system if hasattr(system_or_solved, "system") \
                                   else system_or_solved
    blocks      = sys_.blocks
    connections = sys_.connections
    positions   = _layout(blocks, connections)

    width  = max((x for x, _ in positions.values()), default=0) + BLOCK_W + MARGIN
    height = max((y for _, y in positions.values()), default=0) + BLOCK_H + MARGIN

    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" '
        f'width="{width}" height="{height}" viewBox="0 0 {width} {height}">',
        '<style>.block-label{font-family:sans-serif;font-size:12px;'
        'text-anchor:middle;fill:#222}</style>',
    ]
    for c in connections:
        out.append(_render_connection(c, positions))
    for b in blocks:
        out.append(_render_block(b, positions[b]))
    out.append('</svg>')
    return '\n'.join(out)


def _layout(blocks, connections) -> dict:
    rank = _ranks(blocks, connections)
    by_rank: dict = {}
    for b in blocks:
        by_rank.setdefault(rank[b], []).append(b)

    positions: dict = {}
    for r, bs in by_rank.items():
        x = MARGIN + r * (BLOCK_W + RANK_GAP)
        for i, b in enumerate(bs):
            y = MARGIN + i * (BLOCK_H + ROW_GAP)
            positions[b] = (x, y)
    return positions


def _ranks(blocks, connections) -> dict:
    outgoing: dict = {b: [] for b in blocks}
    in_deg:   dict = {b: 0  for b in blocks}
    for c in connections:
        outgoing[c.src_block].append(c.dst_block)
        in_deg[c.dst_block] += 1

    rank: dict = {b: 0 for b in blocks if in_deg[b] == 0}
    queue = [b for b in blocks if in_deg[b] == 0]
    while queue:
        b = queue.pop(0)
        for nxt in outgoing[b]:
            rank[nxt] = max(rank.get(nxt, 0), rank[b] + 1)
            in_deg[nxt] -= 1
            if in_deg[nxt] == 0:
                queue.append(nxt)
    if any(b not in rank for b in blocks):
        fallback = max(rank.values(), default=0) + 1
        for b in blocks:
            rank.setdefault(b, fallback)
    return rank


def _render_block(block, position) -> str:
    x, y     = position
    fill     = _CATEGORY_FILL.get(block.category, _CATEGORY_FILL["Generic"])
    cls_name = type(block).__name__
    label    = _xml_escape(block.label or cls_name)
    return (
        f'<g class="block" data-block="{cls_name}" data-label="{label}">'
        f'<rect x="{x}" y="{y}" width="{BLOCK_W}" height="{BLOCK_H}" '
        f'rx="6" ry="6" fill="{fill}" stroke="#333" stroke-width="1.5"/>'
        f'<text class="block-label" '
        f'x="{x + BLOCK_W / 2}" y="{y + BLOCK_H / 2 + 4}">{label}</text>'
        f'</g>'
    )


def _render_connection(conn, positions) -> str:
    sx, sy = positions[conn.src_block]
    dx, dy = positions[conn.dst_block]
    prx, pry = _port_anchor(conn.src_block, conn.src_port, "out")
    plx, ply = _port_anchor(conn.dst_block, conn.dst_port, "in")

    x1 = sx + prx * BLOCK_W
    y1 = sy + pry * BLOCK_H
    x2 = dx + plx * BLOCK_W
    y2 = dy + ply * BLOCK_H

    kind   = conn.src_block.outlets[conn.src_port].kind.name
    stroke = _STREAM_STROKE.get(kind, "#888")
    src_id = f"{type(conn.src_block).__name__}.{conn.src_port}"
    dst_id = f"{type(conn.dst_block).__name__}.{conn.dst_port}"

    cx1 = x1 + (x2 - x1) * 0.4
    cx2 = x1 + (x2 - x1) * 0.6
    d = f"M{x1:.1f},{y1:.1f} C{cx1:.1f},{y1:.1f} {cx2:.1f},{y2:.1f} {x2:.1f},{y2:.1f}"

    return (
        f'<path class="connection" '
        f'data-src="{src_id}" data-dst="{dst_id}" data-kind="{kind}" '
        f'd="{d}" stroke="{stroke}" stroke-width="2" fill="none"/>'
    )


def _port_anchor(block, port_name, direction) -> tuple:
    overrides = block.render_ports() or {}
    if port_name in overrides:
        return overrides[port_name]
    ports = block.inlets if direction == "in" else block.outlets
    names = list(ports.keys())
    i = names.index(port_name)
    n = len(names)
    rel_x = 0.0 if direction == "in" else 1.0
    rel_y = (i + 1) / (n + 1)
    return rel_x, rel_y


def _xml_escape(s: str) -> str:
    return (s.replace("&", "&amp;")
             .replace("<", "&lt;")
             .replace(">", "&gt;")
             .replace('"', "&quot;"))
