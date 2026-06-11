"""
tests/test_svg.py — Step 5 §7.5 SVG renderer acceptance.

Renders the full GT system and asserts every block and every connection
appears in the SVG output. Also checks the SVG is well-formed XML and
that an unsolved System renders too.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import xml.etree.ElementTree as ET
import pytest

from simulators.gt_system.system import GTSystemParams, build_gt_system
from nexablock.viz.svg import render


@pytest.fixture(scope="module")
def solved():
    return build_gt_system(GTSystemParams())


@pytest.fixture(scope="module")
def svg(solved):
    return render(solved)


def test_render_returns_str(svg):
    assert isinstance(svg, str)
    assert svg.startswith("<svg")
    assert svg.rstrip().endswith("</svg>")


def test_svg_is_well_formed_xml(svg):
    ET.fromstring(svg)


def test_every_block_appears(solved, svg):
    for b in solved.blocks:
        cls = type(b).__name__
        assert f'data-block="{cls}"' in svg, f"missing block group for {cls}"
        assert b.label in svg, f"missing block label {b.label!r}"


def test_every_connection_appears(solved, svg):
    for c in solved.connections:
        src_id = f"{type(c.src_block).__name__}.{c.src_port}"
        dst_id = f"{type(c.dst_block).__name__}.{c.dst_port}"
        assert f'data-src="{src_id}"' in svg, f"missing connection src {src_id}"
        assert f'data-dst="{dst_id}"' in svg, f"missing connection dst {dst_id}"


def test_connection_count_matches(solved, svg):
    n = svg.count('class="connection"')
    assert n == len(solved.connections), \
        f"SVG has {n} <path class=connection>, system has {len(solved.connections)}"


def test_render_unsolved_system():
    """Rendering must work without solving (no compute() calls touched)."""
    from nexablock.core.system import System
    from nexablock.blocks import GasTurbine, HRSG
    s = System("tiny")
    gt   = s.add(GasTurbine())
    hrsg = s.add(HRSG())
    s.connect(gt.outlets["exhaust"], hrsg.inlets["exhaust_in"])
    out = render(s)
    assert 'data-block="GasTurbine"' in out
    assert 'data-block="HRSG"' in out
    assert 'data-src="GasTurbine.exhaust"' in out


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
