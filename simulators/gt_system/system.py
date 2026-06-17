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
from nexablock.blocks       import (GasTurbine, HRSG, LiBrChiller,
                                     DoubleEffectLiBrChiller, MED,
                                     GPUCassette, Radiator, SteamSplitter,
                                     Calorifier, Mixer)


@dataclass
class GTSystemParams:
    # Gas Turbine
    p_rated_kW:   float = 10_000.0
    load_pct:     float = 85.0
    gt_eff:       float = 0.35
    t_ambient_C:  float = 25.0
    t_exhaust_C:  float = 530.0
    # HRSG.  fw_t_C is the feedwater / loop return set-point (the radiator + MED
    # bypass blend the cooling loop back to this temperature).
    hrsg_eff_pct: float = 85.0
    steam_p_bar:  float = 10.0
    fw_t_C:       float = 80.0       # HRSG feedwater return set-point
    # LiBr chiller + GPU dielectric-coolant loop.  All HRSG steam → LiBr (no splitter).
    # chiller_effect selects the absorption-chiller type:
    #   "single" — single-effect (COP ~0.7, low-grade heat) — the default
    #   "double" — double-effect (COP ~1.2, needs ~8-10 bar / ~170°C+ steam)
    chiller_effect: str = "single"
    # steam_split_mode: "off" (all steam → LiBr) or "auto" (LiBr-priority — feed
    # the chiller only the steam it needs to cool the GPU, route the surplus
    # through a calorifier to the MED hot-water loop, so the chiller is never
    # over-fed when GPU demand drops).
    steam_split_mode: str = "off"
    libr_cop:     float = 0.70
    gpu_t_in_C:   float = 30.0     # dielectric coolant supply to the cassette tank
    gpu_t_out_C:  float = 42.0     # dielectric coolant return (ΔT 12 K)
    coolant_cp:   float = 2100.0   # dielectric fluid specific heat  (J/kg·K) — NOT water
    coolant_rho:  float = 780.0    # dielectric fluid density (kg/m³) — single-phase immersion
    libr_reject_t_C:  float = 95.0   # LiBr heat-rejection (hot cooling-loop) temperature
    # GPU data centre
    gpu_it_kW:    float = 5_000.0
    cassette_pue: float = 1.05       # cassette overhead = IT × (cassette_pue − 1)
    # MED (rejection-driven) + radiator
    med_effects:  int   = 8
    sw_t_C:       float = 28.0
    # MED 3-way bypass.  mode "manual" uses med_bypass_frac directly. mode "auto"
    # cascades with the radiator: MED captures heat toward its real cold-end
    # (seawater + med_cold_pinch_K, below the HRSG set-point); the bypass auto-
    # opens just enough to keep the loop return at the HRSG feedwater set-point
    # (fw_t_C) instead of over-cooling it.
    med_bypass_mode:   str   = "manual"
    med_bypass_frac:   float = 0.0   # manual 3-way: fraction of rejection routed around MED
    med_cold_pinch_K:  float = 15.0  # MED cold-end approach above seawater (auto mode)
    radiator_approach_K: float = 15.0  # radiator cold-branch approach to ambient
    # Plant aux loads (electrical, kW = fraction × base)
    gt_aux_frac:    float = 0.010    # GT aux as fraction of derated GT capacity (internal derate → GT net)
    libr_pump_frac: float = 0.015    # (legacy) LiBr pump as fraction of cooling
    ct_fan_frac:    float = 0.015    # (legacy) radiator fan as fraction of rejected heat
    bop_frac:       float = 0.010    # (legacy) plant BoP as fraction of GT power
    # ── Plant-electrical model (IT/flow-driven) ───────────────────────────────
    pump_eta:        float = 0.70    # pump efficiency (fraction), all pumps
    dp_diel_bar:     float = 1.5     # dielectric-coolant loop head
    dp_libr_bar:     float = 2.0     # LiBr internal solution/refrigerant head
    dp_loop_bar:     float = 3.0     # cooling-water loop circulation head
    dp_bfp_bar:      float = 9.0     # HRSG boiler feed-water pump head (to steam pressure)
    dp_sw_bar:       float = 2.0     # seawater intake head
    dp_med_feed_bar: float = 2.0     # MED feed head
    dp_brine_bar:    float = 2.0     # brine reject head
    dp_dist_bar:     float = 2.0     # distillate head
    dp_cond_bar:     float = 2.0     # condensate return head
    libr_circ_ratio: float = 12.0    # LiBr solution circulation ratio (× refrigerant flow)
    fan_rated_frac:  float = 0.015   # dry-cooler fan power at full duty (fraction of Q_cond)
    containers_per_MW: float = 3.0   # 40' containers per MW IT (1 GPU + 2 aux/other)
    container_area_m2: float = 70.0  # 40' container external surface
    container_U:       float = 0.5   # envelope U-value (W/m²·K, standard insulation)
    container_inside_C:float = 27.0  # container inside set-point
    lights_frac:       float = 0.25  # lights as fraction of HVAC
    # ── Operating + control modes ────────────────────────────────────────────
    operating_mode:    str   = "island"     # "island" | "grid_tied"
    gt_power_mode:     str   = "auto"       # "auto" | "manual"  — auto: follow electrical demand
    external_load_kW:  float = 0.0          # island: user-entered; grid_tied: ignored (auto-export)


def build_gt_system(p: GTSystemParams) -> SolvedSystem:
    """Instantiate / wire / solve. When gt_power_mode or steam_split_mode
    is "auto", resolve load_pct / libr_frac through control_setpoints
    before instantiating blocks so the solve uses the auto-tuned setpoint.

    Stashes resolved control state on the SolvedSystem as `.control` for
    downstream renderers (feasibility, audit, reports).
    """
    from .control import control_setpoints, med_bypass_fraction, med_loop_cold_C
    cs = control_setpoints(p)

    sys = System("GT System — GT + HRSG + LiBr + GPU + MED")

    # ── Instantiate blocks ────────────────────────────────────────────────────
    gt      = sys.add(GasTurbine(
                p_rated_kW=p.p_rated_kW, load_pct=cs.load_pct,
                gt_eff=p.gt_eff, t_ambient_C=p.t_ambient_C,
                t_exhaust_C=p.t_exhaust_C, aux_frac=p.gt_aux_frac))

    hrsg    = sys.add(HRSG(
                hrsg_eff_pct=p.hrsg_eff_pct,
                steam_p_bar=p.steam_p_bar,
                fw_t_C=p.fw_t_C))

    _coolant_dt = max(0.1, p.gpu_t_out_C - p.gpu_t_in_C)   # K, dielectric loop ΔT
    _ChillerCls = (DoubleEffectLiBrChiller if p.chiller_effect == "double"
                   else LiBrChiller)
    chiller = sys.add(_ChillerCls(
                cop=p.libr_cop, chw_sup_C=p.gpu_t_in_C, chw_dt_K=_coolant_dt,
                chw_cp=p.coolant_cp, pump_frac=p.libr_pump_frac,
                reject_t_C=p.libr_reject_t_C, reject_return_C=p.fw_t_C))

    gpu     = sys.add(GPUCassette(
                n_gpu=1, p_gpu_kW=p.gpu_it_kW,   # 1 virtual cassette = whole DC
                aux_frac=p.cassette_pue - 1.0,
                coolant_cp=p.coolant_cp, coolant_rho=p.coolant_rho,
                dt_K=_coolant_dt))

    med     = sys.add(MED(
                n_effects=p.med_effects, sw_t_C=p.sw_t_C,
                bypass_frac=med_bypass_fraction(p),
                loop_cold_C=med_loop_cold_C(p)))

    rad     = sys.add(Radiator(
                t_ambient_C=p.t_ambient_C, approach_K=p.radiator_approach_K,
                t_return_C=p.fw_t_C, fan_frac=p.ct_fan_frac))

    # ── Feedwater seed (tear initialiser for the cooling-loop recycle) ────────
    fw_seed = Stream.water_steam(
        mdot=20.0, T=p.fw_t_C + 273.15, P=p.steam_p_bar * 1e5,
        h=4.19 * p.fw_t_C * 1e3, label="Feedwater seed")
    hrsg.inlets["feedwater"].stream = fw_seed

    # Seawater seed
    sw_seed = Stream.fluid(
        mdot=100.0, T=p.sw_t_C + 273.15, P=1.5e5,
        cp=3900.0, rho=1020.0, label="Seawater")
    med.inlets["seawater"].stream = sw_seed

    # ── Steam-split (LiBr-priority) blocks, only when enabled ─────────────────
    _split = p.steam_split_mode == "auto"
    if _split:
        splitter = sys.add(SteamSplitter(libr_frac=cs.libr_frac))
        calor    = sys.add(Calorifier(hot_t_C=p.libr_reject_t_C, return_t_C=p.fw_t_C))
        mixer    = sys.add(Mixer())

    # ── Wire connections ──────────────────────────────────────────────────────
    sys.connect(gt.outlets["exhaust"],     hrsg.inlets["exhaust_in"])
    if _split:
        # HRSG steam → 3-way: LiBr gets the steam it needs; surplus → calorifier.
        sys.connect(hrsg.outlets["steam"],      splitter.inlets["steam_in"])
        sys.connect(splitter.outlets["to_libr"], chiller.inlets["steam_in"])
        sys.connect(splitter.outlets["to_med"],  calor.inlets["steam_in"])
    else:
        sys.connect(hrsg.outlets["steam"],     chiller.inlets["steam_in"])   # all steam → LiBr
    sys.connect(chiller.outlets["chw_supply"], gpu.inlets["coolant_in"])
    sys.connect(gpu.outlets["coolant_out"], chiller.inlets["chw_return"])  # dielectric loop (recycle)
    # Cooling-water loop: LiBr rejection → MED (rejection-driven) → radiator.
    # The radiator trims the return to fw_t_C (the HRSG feedwater set-point), so
    # the loop closes back to the HRSG feedwater by the controlled-return ==
    # feedwater-temp coupling (the feedwater seed is at fw_t_C). It isn't a
    # graph cycle because the controlled return makes the feedwater temperature
    # fixed — no feedback to iterate. The dielectric chilled loop is the real
    # recycle (GPU heat → LiBr).
    if _split:
        # LiBr rejection + calorifier hot water → mixer → MED loop feed.
        sys.connect(chiller.outlets["reject_out"], mixer.inlets["in_a"])
        sys.connect(calor.outlets["hot_out"],      mixer.inlets["in_b"])
        sys.connect(mixer.outlets["out"],          med.inlets["loop_in"])
    else:
        sys.connect(chiller.outlets["reject_out"], med.inlets["loop_in"])
    sys.connect(med.outlets["loop_out"],       rad.inlets["loop_in"])

    # ── Solve ─────────────────────────────────────────────────────────────────
    solved = sys.solve()
    # Attach resolved control state for downstream consumers.
    solved.control = cs            # type: ignore[attr-defined]
    solved.operating_mode = p.operating_mode  # type: ignore[attr-defined]
    solved.bop_frac = p.bop_frac   # type: ignore[attr-defined]  # legacy
    solved.params = p              # type: ignore[attr-defined]  # for plant_loads in summary()/feasibility
    return solved


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
    kpis["NG consumption Nm3h"]    = _get(GasTurbine, "NG consumption Nm3/h") or 0.0
    kpis["Steam generation t/h"]   = _get(HRSG, "Steam generation")            or 0.0
    kpis["LiBr cooling kW"]        = _get(LiBrChiller, "Cooling capacity kW")  or 0.0
    kpis["GPU IT load kW"]         = _get(GPUCassette, "IT power")             or 0.0
    kpis["MED water m3day"]        = _get(MED, "Water production m3/day")      or 0.0
    # Control / mode reflection — exposed to study hooks + the report.
    cs = getattr(solved, "control", None)
    if cs is not None:
        kpis["Resolved load_pct"]    = cs.load_pct
        kpis["Resolved libr_frac"]   = cs.libr_frac
        kpis["External load kW"]     = cs.external_load_kW
        kpis["Grid export kW"]       = cs.grid_export_kW

    # Plant PUE (electrical, export excluded) — single screening KPI.
    # Numerator: IT + cassette overhead + itemised plant aux (pumps + dry-cooler
    # fan + HVAC + lights, from plant_loads) + GT aux derate. Excludes external
    # load and grid export. Electrical only — no fuel/thermal. Guard IT > 0.
    from .plant_loads import plant_loads
    it_kW       = kpis["GPU IT load kW"]
    overhead_kW = _get(GPUCassette, "Cassette overhead electrical") or 0.0
    gt_aux_kW   = _get(GasTurbine,  "GT aux electrical")            or 0.0
    p = getattr(solved, "params", None)
    plant_kW = plant_loads(solved, p)["total"] if p is not None else 0.0
    kpis["Plant aux electrical kW"] = plant_kW
    kpis["Plant PUE (electrical, export excluded)"] = (
        (it_kW + overhead_kW + plant_kW + gt_aux_kW) / it_kW
        if it_kW > 0 else 0.0)
    return kpis
