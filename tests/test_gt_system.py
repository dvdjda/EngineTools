"""
tests/test_gt_system.py — Step 4 §7.4 acceptance tests.

Runs the full GT + HRSG + LiBr + GPU + MED system and checks KPIs
against reference values within ±2% per §8 acceptance spec.

Reference values computed from the trusted v1 GT System tool
(gas_turbine_simulator_calculate_natural__1781147515.py, status=trusted)
at default inputs — treated as ground truth for migration validation.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from simulators.gt_system.system import GTSystemParams, build_gt_system, summary
from nexablock.blocks import GasTurbine, HRSG, LiBrChiller, MED, GPUCassette

TOL = 0.02   # ±2% per §8

# ── Baseline params matching v1 tool defaults ─────────────────────────────────
_P = GTSystemParams(
    p_rated_kW   = 10_000.0,
    load_pct     = 85.0,
    gt_eff       = 0.35,
    t_ambient_C  = 25.0,
    t_exhaust_C  = 530.0,
    hrsg_eff_pct = 85.0,
    steam_p_bar  = 10.0,
    fw_t_C       = 80.0,
    libr_frac    = 0.50,
    libr_cop     = 0.70,
    chw_sup_C    = 7.0,
    chw_dt_K     = 6.0,
    gpu_it_kW    = 5_000.0,
    cassette_pue = 1.05,
    med_effects  = 8,
    sw_t_C       = 28.0,
    # Pin to manual modes so the v2 promotion validation runs against the
    # same operating point as the v1 trusted GT tool (load_pct=85,
    # libr_frac=0.5). Auto modes are the new default-for-engineers behaviour
    # but the trusted-tool comparison must use explicit setpoints.
    gt_power_mode    = "manual",
    steam_split_mode = "manual",
    operating_mode   = "island",
    external_load_kW = 0.0,
)

@pytest.fixture(scope="module")
def solved():
    return build_gt_system(_P)


# ── §8.1  GT power ────────────────────────────────────────────────────────────

def test_gt_derate_factor(solved):
    """Ambient 25°C → derate = 1 − 0.007 × 10 = 0.930"""
    for b in solved.blocks:
        if isinstance(b, GasTurbine):
            d = b.results["Derate factor"].value
            assert abs(d - 0.930) / 0.930 < TOL, f"derate={d}"


def test_gt_actual_power_kw(solved):
    """GT power at 85% load of 9300 kW derated = 7905 kW"""
    for b in solved.blocks:
        if isinstance(b, GasTurbine):
            p = b.results["GT actual power"].value
            expected = 10_000 * 0.930 * 0.85
            assert abs(p - expected) / expected < TOL, f"GT power={p:.0f} kW"


def test_gt_fuel_input(solved):
    """Fuel = GT power / efficiency"""
    for b in solved.blocks:
        if isinstance(b, GasTurbine):
            fuel = b.results["Fuel energy input"].value
            p_gt = b.results["GT actual power"].value
            ratio = fuel / p_gt
            assert abs(ratio - 1.0 / _P.gt_eff) / (1.0 / _P.gt_eff) < TOL


# ── §8.2  HRSG ────────────────────────────────────────────────────────────────

def test_hrsg_steam_temp(solved):
    """Steam temperature = T_sat(10 bar) + 30°C ≈ 179.9 + 30 = 209.9°C"""
    for b in solved.blocks:
        if isinstance(b, HRSG):
            t = b.results["Steam temperature"].value
            assert abs(t - 209.9) < 2.0, f"Steam T = {t:.1f}°C"


def test_hrsg_steam_enthalpy(solved):
    """h_steam(10 bar, 210°C) ≈ 2852 kJ/kg  [NIST reference]"""
    for b in solved.blocks:
        if isinstance(b, HRSG):
            h = b.results["Steam enthalpy"].value
            assert abs(h - 2852.0) / 2852.0 < TOL, f"h_steam={h:.1f} kJ/kg"


def test_hrsg_steam_generation_nonzero(solved):
    """Steam generation must be positive when GT is running."""
    for b in solved.blocks:
        if isinstance(b, HRSG):
            m = b.results["Steam generation"].value
            assert m > 0, "No steam generated"


# ── §8.3  LiBr chiller ───────────────────────────────────────────────────────

def test_libr_cooling_positive(solved):
    for b in solved.blocks:
        if isinstance(b, LiBrChiller):
            q = b.results["Cooling capacity kW"].value
            assert q > 0, "LiBr produces no cooling"


def test_libr_cooling_proportional_to_cop(solved):
    """Q_cool / Q_gen ≈ COP within ±2%"""
    for b in solved.blocks:
        if isinstance(b, LiBrChiller):
            q_gen  = b.results["Generator duty"].value
            q_cool = b.results["Cooling capacity kW"].value
            ratio  = q_cool / q_gen
            assert abs(ratio - _P.libr_cop) / _P.libr_cop < TOL


# ── §8.4  GPU cassette ────────────────────────────────────────────────────────

def test_gpu_it_power(solved):
    """IT power = gpu_it_kW (all set as a single virtual cassette)"""
    for b in solved.blocks:
        if isinstance(b, GPUCassette):
            p = b.results["IT power"].value
            assert abs(p - _P.gpu_it_kW) / _P.gpu_it_kW < TOL


# ── §8.5  MED ────────────────────────────────────────────────────────────────

def test_med_gor(solved):
    """GOR = 0.8 × n_effects = 0.8 × 8 = 6.4"""
    for b in solved.blocks:
        if isinstance(b, MED):
            gor = b.results["GOR"].value
            assert abs(gor - 6.4) < 0.05


def test_med_water_production_positive(solved):
    for b in solved.blocks:
        if isinstance(b, MED):
            w = b.results["Water production m3/day"].value
            assert w > 0


def test_med_water_production_matches_v1(solved):
    """Pin MED water production to the v1 trusted figure (~1165 m³/day at
    default inputs). Earlier the MED block stored both m³/day and m³/h
    under the same label; the m³/h row silently overwrote m³/day and the
    UI reported a value 24× too low. ±2% tolerance per §8."""
    v1_ref_m3pd = 1165.0
    for b in solved.blocks:
        if isinstance(b, MED):
            w = b.results["Water production m3/day"].value
            assert abs(w - v1_ref_m3pd) / v1_ref_m3pd < TOL, (
                f"MED daily production = {w:.0f} m³/day, expected ~{v1_ref_m3pd:.0f} "
                f"(±{TOL:.0%})")


# ── §8.6  End-to-end ─────────────────────────────────────────────────────────

def test_no_null_results(solved):
    """Every block must produce at least one result with a finite value."""
    import math
    for b in solved.blocks:
        for label, res in b.results.items():
            assert math.isfinite(res.value), \
                f"{type(b).__name__}.{label!r} = {res.value}"


def test_summary_keys_present(solved):
    kpis = summary(solved)
    required = ["GT actual power kW", "NG consumption Nm3h",
                "Steam generation t/h", "LiBr cooling kW",
                "GPU IT load kW", "MED water m3day"]
    for k in required:
        assert k in kpis and kpis[k] >= 0, f"Missing or negative KPI: {k}"


# ── §8.7  PUE cleanup ─────────────────────────────────────────────────────────
# Cassette PUE stays an INPUT (ratio). The single PUE RESULT is now the
# electrical, export-excluded "Plant PUE". The old standalone "GPU PUE" results
# row (which just echoed the input) is gone. Screening change — no physics.

import nexa_toolkit.engines          # noqa: F401  — registers the engines
from nexa_toolkit.framework import get


def _v2_engine():
    return get("gt_system_v2")


def test_cassette_pue_is_accepted_input_key():
    """cassette_pue is the input ratio (default 1.05); gpu_pue is gone."""
    keys = {i.key for i in _v2_engine().inputs}
    assert "cassette_pue" in keys, keys
    assert "gpu_pue" not in keys, keys
    # the dataclass also accepts it (no physics change)
    from simulators.gt_system.system import GTSystemParams
    assert GTSystemParams(cassette_pue=1.05).cassette_pue == 1.05


def test_no_gpu_pue_in_outputs():
    """The standalone 'GPU PUE' echo row must not appear in the results."""
    eng = _v2_engine()
    r = eng.solve(eng.defaults())
    labels = [o.label for o in eng.outputs(r)]
    assert not any("GPU PUE" in lbl for lbl in labels), labels


def test_plant_pue_design_point():
    """v2 design point (defaults = island/auto, IT 5,000 kW, cassette PUE 1.05):
    plant_pue = (IT + cassette overhead + LiBr pump + CT fan + GT aux + plant
    BoP) / IT ≈ 1.134 (electrical only; MED elec, external load and grid export
    excluded)."""
    eng = _v2_engine()
    r = eng.solve(eng.defaults())
    labels = [o.label for o in eng.outputs(r)]
    assert "Plant PUE (electrical, export excluded)" in labels, labels
    pue = r["kpis"]["Plant PUE (electrical, export excluded)"]
    assert abs(pue - 1.134) < 0.005, f"plant_pue={pue:.4f}"


def test_plant_pue_guards_zero_it():
    """IT > 0 guard: a degenerate solve must not divide by zero."""
    from simulators.gt_system.system import GTSystemParams, build_gt_system, summary
    kpis = summary(build_gt_system(GTSystemParams(gpu_it_kW=0.0)))
    assert kpis["Plant PUE (electrical, export excluded)"] == 0.0


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
