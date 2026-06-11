"""
simulators.gt_system.system — Compose the full GT + HRSG + LiBr + GPU + MED system.

Usage::
    from simulators.gt_system.system import build_gt_system, GTSystemParams
    p = GTSystemParams()
    solved = build_gt_system(p)
    print(solved.blocks[0].results)
"""
from __future__ import annotations
from dataclasses import dataclass, field
import sys, os

# Ensure EngineTools is on path
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from nexablock.core.stream  import Stream, StreamKind
from nexablock.core.system  import System, SolvedSystem
from nexablock.blocks       import (GasTurbine, HRSG, SteamSplitter,
                                     LiBrChiller, MED, GPUCassette, CoolingTower)


@dataclass
class GTSystemParams:
    # Gas Turbine
    p_rated_kW:   float = 10_000.0
    load_pct:     float = 85.0
    gt_eff:       float = 0.35
    t_ambient_C:  float = 25.0
    t_exhaust_C:  float = 530.0
    # HRSG
    hrsg_eff_pct: float = 85.0
    steam_p_bar:  float = 10.0
    fw_t_C:       float = 80.0
    # Steam split
    libr_frac:    float = 0.50
    # LiBr chiller
    libr_cop:     float = 0.70
    chw_sup_C:    float = 7.0
    chw_dt_K:     float = 6.0
    # GPU data centre
    gpu_it_kW:    float = 5_000.0
    gpu_pue:      float = 1.05
    # MED
    med_effects:  int   = 8
    sw_t_C:       float = 28.0
    # Cooling tower
    t_wb_C:       float = 25.0


def build_gt_system(p: GTSystemParams) -> SolvedSystem:
    """
    Instantiate and wire all blocks, return the solved system.
    GPU cassette params derived from gpu_it_kW + pue:
      n_gpu × p_gpu = gpu_it_kW  (single virtual cassette representing the DC)
    """
    sys = System("GT System — GT + HRSG + LiBr + GPU + MED")

    # ── Instantiate blocks ────────────────────────────────────────────────────
    gt      = sys.add(GasTurbine(
                p_rated_kW=p.p_rated_kW, load_pct=p.load_pct,
                gt_eff=p.gt_eff, t_ambient_C=p.t_ambient_C,
                t_exhaust_C=p.t_exhaust_C))

    hrsg    = sys.add(HRSG(
                hrsg_eff_pct=p.hrsg_eff_pct,
                steam_p_bar=p.steam_p_bar,
                fw_t_C=p.fw_t_C))

    splitter= sys.add(SteamSplitter(libr_frac=p.libr_frac))

    chiller = sys.add(LiBrChiller(
                cop=p.libr_cop, chw_sup_C=p.chw_sup_C, chw_dt_K=p.chw_dt_K))

    gpu     = sys.add(GPUCassette(
                n_gpu=1, p_gpu_kW=p.gpu_it_kW,   # 1 virtual cassette = whole DC
                aux_frac=p.gpu_pue - 1.0,
                coolant_cp=4187.0, coolant_rho=1000.0, dt_K=p.chw_dt_K))

    med     = sys.add(MED(
                n_effects=p.med_effects, sw_t_C=p.sw_t_C))

    ct      = sys.add(CoolingTower(t_wb_C=p.t_wb_C))

    # ── Feedwater seed stream (no upstream block — source) ────────────────────
    fw_seed = Stream.water_steam(
        mdot=20.0, T=p.fw_t_C + 273.15, P=p.steam_p_bar * 1e5,
        h=4.19 * p.fw_t_C * 1e3, label="Feedwater seed")
    hrsg.inlets["feedwater"].stream = fw_seed

    # Seawater seed
    sw_seed = Stream.fluid(
        mdot=100.0, T=p.sw_t_C + 273.15, P=1.5e5,
        cp=3900.0, rho=1020.0, label="Seawater")
    med.inlets["seawater"].stream = sw_seed

    # ── Wire connections ──────────────────────────────────────────────────────
    sys.connect(gt.outlets["exhaust"],        hrsg.inlets["exhaust_in"])
    sys.connect(hrsg.outlets["steam"],        splitter.inlets["steam_in"])
    sys.connect(splitter.outlets["to_libr"],  chiller.inlets["steam_in"])
    sys.connect(splitter.outlets["to_med"],   med.inlets["steam_in"])
    sys.connect(chiller.outlets["ct_water_out"], ct.inlets["heat_in"])
    sys.connect(chiller.outlets["chw_supply"], gpu.inlets["coolant_in"])

    # ── Solve ─────────────────────────────────────────────────────────────────
    return sys.solve()


def summary(solved: SolvedSystem) -> dict[str, float]:
    """Extract the top-level KPIs from a solved system."""
    kpis: dict[str, float] = {}

    def _get(block_cls, result_label: str) -> float | None:
        for b in solved.blocks:
            if isinstance(b, block_cls):
                r = b.results.get(result_label)
                if r: return r.value
        return None

    kpis["GT actual power kW"]     = _get(GasTurbine, "GT actual power")       or 0.0
    kpis["NG consumption Nm3h"]    = _get(GasTurbine, "NG consumption")        or 0.0
    kpis["Steam generation t/h"]   = _get(HRSG, "Steam generation")            or 0.0
    kpis["LiBr cooling kW"]        = _get(LiBrChiller, "Cooling capacity kW")  or 0.0
    kpis["GPU IT load kW"]         = _get(GPUCassette, "IT power")             or 0.0
    kpis["MED water m3day"]        = _get(MED, "Water production")             or 0.0
    return kpis
