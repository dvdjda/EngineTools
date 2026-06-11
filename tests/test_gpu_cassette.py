"""
tests/test_gpu_cassette.py — Step 2 §7.2 verification.

Runs the GPUCassette block standalone and via its embedded test_cases().
All expected values within ±2% per §8 acceptance spec.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from nexablock.blocks.gpu_cassette import GPUCassette
from nexablock.core.stream import Stream, StreamKind


# ── helpers ───────────────────────────────────────────────────────────────────

def _run(block: GPUCassette, T_sup_C: float = 30.0) -> dict:
    """Wire a supply inlet, compute, return results dict."""
    supply = Stream.fluid(mdot=0.1, T=T_sup_C + 273.15, P=3e5,
                          cp=block._coolant_cp, rho=block._coolant_rho,
                          label="supply")
    block.inlets["coolant_in"].stream = supply
    block.compute()
    return {k: v.value for k, v in block.results.items()}


# ── §8.1 baseline fixture ─────────────────────────────────────────────────────

def test_baseline_it_power():
    b = GPUCassette(n_gpu=72, p_gpu_kW=1.0)
    r = _run(b)
    assert abs(r["IT power"] - 72.0) / 72.0 < 0.02

def test_baseline_heat_load():
    b = GPUCassette(n_gpu=72, p_gpu_kW=1.0, aux_frac=0.15)
    r = _run(b)
    expected = 72.0 * 1.15
    assert abs(r["Heat load"] - expected) / expected < 0.02

def test_baseline_return_temp():
    b = GPUCassette(n_gpu=72, p_gpu_kW=1.0, aux_frac=0.15, dt_K=12.0)
    r = _run(b, T_sup_C=30.0)
    assert abs(r["Return temp"] - 42.0) < 0.5   # °C

def test_baseline_coolant_flow():
    """Coolant flow = Q / (cp × ΔT) / rho × unit conversion."""
    b = GPUCassette(n_gpu=72, p_gpu_kW=1.0, aux_frac=0.15,
                    coolant_cp=2100.0, coolant_rho=780.0, dt_K=12.0)
    r = _run(b)
    q = 72 * 1000 * 1.15          # W
    mdot = q / (2100.0 * 12.0)    # kg/s
    expected_Lpm = mdot / 780.0 * 1000 * 60
    assert abs(r["Coolant vol flow"] - expected_Lpm) / expected_Lpm < 0.02


# ── outlet streams ────────────────────────────────────────────────────────────

def test_outlets_set():
    b = GPUCassette()
    _run(b)
    assert b.outlets["coolant_out"].stream is not None
    assert b.outlets["heat"].stream is not None
    assert b.outlets["heat"].stream.kind == StreamKind.ENERGY

def test_heat_outlet_matches_result():
    b = GPUCassette(n_gpu=72, p_gpu_kW=1.0, aux_frac=0.15)
    _run(b)
    heat_stream_kW = b.outlets["heat"].stream.power / 1e3
    result_kW = b.results["Heat load"].value
    assert abs(heat_stream_kW - result_kW) < 0.01


# ── embedded TestCase runner ──────────────────────────────────────────────────

def test_embedded_test_cases():
    """Run all TestCases from block.test_cases() and check within tol."""
    b = GPUCassette()
    cases = b.test_cases()
    assert len(cases) > 0, "GPUCassette has no test cases"

    for tc in cases:
        # Build fresh block from params
        p = tc.params
        block = GPUCassette(
            n_gpu=p["n_gpu"], p_gpu_kW=p["p_gpu_kW"],
            aux_frac=p["aux_frac"], coolant_cp=p["coolant_cp"],
            coolant_rho=p["coolant_rho"], dt_K=p["dt_K"],
        )
        for port_name, stream in tc.inlets.items():
            block.inlets[port_name].stream = stream
        block.compute()

        for label, expected in tc.expected.items():
            got = block.results[label].value
            rel = abs(got - expected) / max(abs(expected), 1e-9)
            assert rel < tc.tol, (
                f"TestCase {tc.note!r}: {label} = {got:.3g} "
                f"(expected {expected:.3g}, tol={tc.tol:.0%})")


# ── scaling sanity ────────────────────────────────────────────────────────────

def test_scales_linearly_with_gpus():
    b4  = GPUCassette(n_gpu=4,   p_gpu_kW=1.0)
    b8  = GPUCassette(n_gpu=8,   p_gpu_kW=1.0)
    r4  = _run(b4)
    r8  = _run(b8)
    assert abs(r8["IT power"] / r4["IT power"] - 2.0) < 0.001
    assert abs(r8["Heat load"] / r4["Heat load"] - 2.0) < 0.001


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
