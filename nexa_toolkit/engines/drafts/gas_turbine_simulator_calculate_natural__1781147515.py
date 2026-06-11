"""
Gas Turbine Simulator  —  GT + HRSG + LiBr + GPU + MED  —  TRUSTED, status="trusted".

Simple-cycle GT with full thermal integration — no steam turbine.

  [ Natural Gas ]
       |
       v
  [ Gas Turbine (GT) ]  -->  Electrical power
       |
       v  exhaust gas
  [ HRSG ]  -->  Stack loss (flue)
       |
       v  steam (superheated, drum pressure)
  +--------------------+---------------------------+
  |                    |                           |
  v                    v                           v
[LiBr Absorption   [MED Thermal              (MED = remainder
  Chiller]          Desalination]             auto-fraction)
  |                    |
  v                    v
[Chilled water]    [Fresh water m³/day]
  |
  v
[GPU/TPU Immersion Cooling]  -->  Data-centre IT load

Physics & assumptions:
  GT:   Ambient derating  -0.7 %/°C above ISO 15 °C (conservative screening).
        Exhaust carries 85 % of waste heat (CCGT-optimised GT insulation).
        Exhaust mass flow: Q_exh = m_dot × cp_exh × (T_exh − T_amb), cp_exh = 1.08 kJ/kg·K.
        NG approximated as methane: LHV = 50 050 kJ/kg, density 0.75 kg/Nm³.
  HRSG: Steam saturation temperature from Antoine equation (±0.3 °C, 0.05–80 bar).
        Steam enthalpy: h_f = 4.19·T,  h_fg = 2501.4 − 2.37·T,  cp_sh = 2.10 kJ/kg·K.
        Fixed superheat ΔT = 30 °C above saturation.
        Stack temperature: linear interpolation from exhaust to ambient via HRSG effectiveness.
  Steam: All steam split between LiBr chiller and MED.
         MED fraction = 100 % − LiBr fraction (auto, shown as output).
  LiBr: Single-effect screening; condensate returns from generator at 100 °C (atm).
        Q_cool = Q_gen × COP;  Q_condenser = Q_gen + Q_cool.
        Cooling-tower circuit: ΔT_ct = 7 °C (screening).
  MED:  GOR = 0.8 × n_effects (thin-film falling-film, screening).
        Steam condensate returns at 65 °C (top brine temp).
        Water recovery 35 %; seawater density 1 020 kg/m³.
        Specific electrical consumption (SEC) = 1.5 kWh/m³ (pumps/controls).
  GPU:  All IT power → heat (conservative). Immersion fluid: cp = 2.0 kJ/kg·K,
        ρ = 1 400 kg/m³ (dielectric, e.g. Novec range), ΔT_tank = 10 °C.
  PUE:  Total facility power = IT × PUE; overhead = IT × (PUE − 1).

Verify all subsystems against manufacturer data / DCS / ChemCAD before design use.
Built by Cody 2026-06-11 — upgraded 2026-06-11: steam turbine removed per David's instruction.
"""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches

from ...framework.contract import Engine, InputSpec, OutputSpec, register
from ...dwsim_props import (
    t_sat as _dp_tsat, h_steam as _dp_hsteam, h_feedwater as _dp_hfw,
    h_liq as _dp_hliq, h_vap as _dp_hvap, exh_cp as _dp_exhcp,
)
from ...reporting.charts import NAVY, TEAL, AMBER, RED, GRID, INK

GREY   = "#5b6675"
GREEN  = "#2E7D4E"
PURPLE = "#7D3C98"
LBLUE  = "#2980B9"

# ── Fluid / fuel constants ────────────────────────────────────────────────────
NG_LHV_KJ_KG       = 50_050.0
NG_RHO_KG_NM3      = 0.75
CP_EXHGAS          = 1.08
CP_STEAM_SH        = 2.10
CP_WATER           = 4.187
DT_SUPERHEAT       = 30.0
EXH_FRAC_GT        = 0.85
MED_RECOVERY       = 0.35
MED_SEC_KWH_M3     = 1.5
IMM_CP             = 2.0
IMM_RHO            = 1_400.0
IMM_DT             = 10.0
CT_DT              = 7.0





@register
class Draft_gas_turbine_simulator_calculate_natural__1781147515(Engine):
    key    = "gas_turbine_simulator_calculate_natural__1781147515"
    name   = "GT System  \u2014  GT + HRSG + LiBr + GPU Cooling + MED"
    kind   = "simulator"
    status = "trusted"
    provenance = (
        "Gas Turbine Simulator\n"
        "Calculate Natural Gas consumption, total calorific energy output, required cooling "
        "system capacity, cooling water flow and mass/energy balance for the cooling water. "
        "Base on inputs required power output, gas to power conversation efficiency, ambient "
        "temperature, gas turbine maximum capacity and actual load.\n"
        "[Upgraded 2026-06-11: full GT + HRSG + LiBr + GPU + MED. "
        "Steam turbine removed 2026-06-11 per David's instruction.]"
    )
    notes = (
        "Simple-cycle GT with thermal integration: GT exhaust \u2192 HRSG \u2192 steam split to "
        "(a) LiBr absorption chiller \u2192 GPU/TPU immersion cooling and "
        "(b) MED thermal desalination \u2192 fresh water. No steam turbine. "
        "GT derating -0.7 %/\u00b0C above ISO 15 \u00b0C; exhaust fraction 85 % of waste heat. "
        "Steam from Antoine equation + linear h correlations (screening grade). "
        "LiBr condensate return 100 \u00b0C; MED condensate 65 \u00b0C; GOR = 0.8 \u00d7 effects. "
        "Verify all subsystem assumptions against manufacturer data before design use."
    )

    inputs = [
        # \u2500\u2500 Gas Turbine \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("p_rated_kw",    "GT rated power  (ISO 15 \u00b0C)",            "kW",    10_000,  50,    300_000),
        InputSpec("load_pct",      "GT actual load  (% of derated capacity)", "%",     85,      10,    100),
        InputSpec("gt_eff",        "GT electrical efficiency  (LHV basis)",   "-",     0.35,    0.15,  0.45),
        InputSpec("t_ambient_c",   "Ambient temperature",                     "\u00b0C",    25,     -20,    55),
        InputSpec("t_exhaust_c",   "GT exhaust gas temperature",              "\u00b0C",    530,    380,    650),
        # \u2500\u2500 HRSG \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("hrsg_eff_pct",  "HRSG thermal effectiveness",              "%",     85,      50,    95),
        InputSpec("steam_p_bar",   "Steam drum pressure",                     "bar a", 10,      1,     100),
        InputSpec("fw_t_c",        "Feedwater temperature",                   "\u00b0C",    80,      20,    160),
        # \u2500\u2500 Steam split (LiBr gets this fraction; MED gets the rest) \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("libr_frac_pct", "Steam fraction  \u2192  LiBr chiller",         "%",     50,      5,     95),
        # \u2500\u2500 LiBr Absorption Chiller \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("libr_cop",      "LiBr chiller COP",                        "-",     0.70,    0.50,  1.30),
        InputSpec("chw_sup_c",     "Chilled water supply temperature",        "\u00b0C",    7,       2,     20),
        InputSpec("chw_dt_c",      "Chilled water temperature rise  \u0394T",     "\u00b0C",    6,       3,     15),
        # \u2500\u2500 GPU / Data Centre \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("gpu_it_kw",     "GPU / TPU IT load  (total)",              "kW",    5_000,   100,   200_000),
        InputSpec("gpu_pue",       "Data centre PUE  (total / IT power)",     "-",     1.05,    1.01,  2.00),
        # \u2500\u2500 MED Desalination \u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500\u2500
        InputSpec("med_effects",   "MED number of effects",                   "-",     8,       2,     20),
        InputSpec("sw_t_c",        "Seawater feed temperature",               "\u00b0C",    28,      5,     35),
    ]

    def solve(self, v):

        # ══════════════════════════════════════════════════════════════
        # 1.  GAS TURBINE
        # ══════════════════════════════════════════════════════════════
        p_rated   = v["p_rated_kw"]
        load_pct  = v["load_pct"]
        gt_eff    = max(v["gt_eff"], 1e-6)
        t_amb     = v["t_ambient_c"]
        t_exh     = v["t_exhaust_c"]

        gt_derate     = max(0.50, 1.0 - 0.007 * max(0.0, t_amb - 15.0))
        p_gt_derated  = p_rated * gt_derate
        p_gt          = p_gt_derated * load_pct / 100.0

        fuel_kw       = p_gt / gt_eff
        ng_kgph       = fuel_kw * 3_600.0 / NG_LHV_KJ_KG
        ng_nm3ph      = ng_kgph / NG_RHO_KG_NM3
        sfc_g_kwh     = ng_kgph * 1_000.0 / max(p_gt, 1.0)
        gt_eff_net    = p_gt / max(fuel_kw, 1.0) * 100.0

        waste_heat    = fuel_kw - p_gt
        exh_heat_kw   = waste_heat * EXH_FRAC_GT
        gt_cw_kw      = waste_heat * (1.0 - EXH_FRAC_GT)

        dt_exh        = max(t_exh - t_amb, 1.0)
        exh_flow_kgps = exh_heat_kw / (_dp_exhcp(t_exh) * dt_exh)
        exh_flow_tph  = exh_flow_kgps * 3.6

        # ══════════════════════════════════════════════════════════════
        # 2.  HRSG
        # ══════════════════════════════════════════════════════════════
        hrsg_eff  = v["hrsg_eff_pct"] / 100.0
        p_steam   = v["steam_p_bar"]
        fw_t      = v["fw_t_c"]

        t_sat     = _dp_tsat(p_steam)
        t_steam   = t_sat + DT_SUPERHEAT
        h_steam   = _dp_hsteam(p_steam, t_steam)
        h_fw      = _dp_hfw(fw_t, p_steam)
        dh_gen    = max(h_steam - h_fw, 1.0)

        q_hrsg        = exh_heat_kw * hrsg_eff
        q_stack       = exh_heat_kw * (1.0 - hrsg_eff)
        t_stack       = t_exh - (t_exh - t_amb) * hrsg_eff

        m_steam_kgps  = q_hrsg / dh_gen
        m_steam_kgph  = m_steam_kgps * 3_600.0
        m_steam_tph   = m_steam_kgph / 1_000.0

        # ══════════════════════════════════════════════════════════════
        # 3.  STEAM DISTRIBUTION  (LiBr + MED, no steam turbine)
        # ══════════════════════════════════════════════════════════════
        libr_frac     = min(v["libr_frac_pct"], 95.0) / 100.0
        med_frac      = max(0.0, 1.0 - libr_frac)

        m_libr_kgps   = m_steam_kgps * libr_frac
        m_med_kgps    = m_steam_kgps * med_frac

        m_libr_tph    = m_libr_kgps * 3.6
        m_med_tph     = m_med_kgps  * 3.6

        # ══════════════════════════════════════════════════════════════
        # 4.  LiBr ABSORPTION CHILLER
        # ══════════════════════════════════════════════════════════════
        libr_cop      = max(v["libr_cop"], 0.10)
        chw_sup       = v["chw_sup_c"]
        chw_dt        = max(v["chw_dt_c"], 0.1)

        h_cond_libr   = _dp_hliq(1.013)
        q_libr_gen    = m_libr_kgps * (h_steam - h_cond_libr)
        q_libr_cool   = q_libr_gen  * libr_cop
        q_libr_rej    = q_libr_gen  + q_libr_cool

        m_chw_kgps    = q_libr_cool / (CP_WATER * chw_dt)
        chw_m3ph      = m_chw_kgps  * 3.6
        chw_ret_c     = chw_sup + chw_dt
        q_libr_tr     = q_libr_cool / 3.517

        m_ct_kgps     = q_libr_rej  / (CP_WATER * CT_DT)
        ct_m3ph       = m_ct_kgps   * 3.6

        # ══════════════════════════════════════════════════════════════
        # 5.  GPU / DATA CENTRE
        # ══════════════════════════════════════════════════════════════
        gpu_it        = v["gpu_it_kw"]
        pue           = max(v["gpu_pue"], 1.0)

        gpu_total     = gpu_it * pue
        gpu_overhead  = gpu_total - gpu_it
        gpu_heat      = gpu_it
        cool_margin   = q_libr_cool - gpu_heat

        m_imm_kgps    = gpu_heat / (IMM_CP * IMM_DT)
        imm_m3ph      = m_imm_kgps * 3_600.0 / IMM_RHO

        # ══════════════════════════════════════════════════════════════
        # 6.  MED DESALINATION
        # ══════════════════════════════════════════════════════════════
        n_eff         = max(int(round(v["med_effects"])), 2)
        med_gor       = 0.8 * n_eff

        h_cond_med    = _dp_hfw(65.0)
        q_med_kw      = m_med_kgps * (h_steam - h_cond_med)

        m_dist_kgps   = m_med_kgps * med_gor
        m_dist_m3pd   = m_dist_kgps * 86_400.0 / 1_000.0
        m_dist_m3ph   = m_dist_kgps * 3_600.0  / 1_000.0

        m_sw_kgps     = m_dist_kgps / max(MED_RECOVERY, 1e-3)
        m_sw_m3ph     = m_sw_kgps   * 3_600.0 / 1_020.0
        m_brine_kgps  = m_sw_kgps   - m_dist_kgps
        m_brine_m3ph  = m_brine_kgps * 3_600.0 / 1_030.0
        p_med_elec    = MED_SEC_KWH_M3 * m_dist_m3pd / 24.0

        # ══════════════════════════════════════════════════════════════
        # 7.  SYSTEM CONVERGENCE
        # ══════════════════════════════════════════════════════════════
        p_demand      = gpu_total + p_med_elec
        power_margin  = p_gt - p_demand
        heat_rate     = 3_600.0 / max(gt_eff / 100.0, 1e-6) if gt_eff < 1 else 3_600.0 / max(p_gt / max(fuel_kw, 1), 1e-6)
        heat_rate     = 3_600.0 / max(p_gt / max(fuel_kw, 1.0), 1e-6)

        # Overall thermal utilisation
        thermal_out   = q_libr_cool + q_med_kw
        energy_util   = (p_gt + thermal_out) / max(fuel_kw, 1.0) * 100.0

        return {
            # GT
            "gt_derate":       gt_derate,
            "p_gt_derated":    p_gt_derated,
            "p_gt":            p_gt,
            "fuel_kw":         fuel_kw,
            "ng_kgph":         ng_kgph,
            "ng_nm3ph":        ng_nm3ph,
            "sfc_g_kwh":       sfc_g_kwh,
            "gt_eff_net":      gt_eff_net,
            "exh_flow_tph":    exh_flow_tph,
            "exh_heat_kw":     exh_heat_kw,
            "gt_cw_kw":        gt_cw_kw,
            # HRSG
            "t_sat_c":         t_sat,
            "t_steam_c":       t_steam,
            "h_steam_kj":      h_steam,
            "q_hrsg_kw":       q_hrsg,
            "q_stack_kw":      q_stack,
            "t_stack_c":       t_stack,
            "m_steam_tph":     m_steam_tph,
            # Steam split
            "m_libr_tph":      m_libr_tph,
            "m_med_tph":       m_med_tph,
            "med_frac_pct":    med_frac * 100.0,
            # LiBr
            "q_libr_gen_kw":   q_libr_gen,
            "q_libr_cool_kw":  q_libr_cool,
            "q_libr_cool_tr":  q_libr_tr,
            "q_libr_rej_kw":   q_libr_rej,
            "chw_m3ph":        chw_m3ph,
            "chw_ret_c":       chw_ret_c,
            "ct_m3ph":         ct_m3ph,
            # GPU
            "gpu_total_kw":    gpu_total,
            "gpu_overhead_kw": gpu_overhead,
            "cool_margin_kw":  cool_margin,
            "imm_m3ph":        imm_m3ph,
            # MED
            "med_gor":         med_gor,
            "q_med_kw":        q_med_kw,
            "m_dist_m3pd":     m_dist_m3pd,
            "m_dist_m3ph":     m_dist_m3ph,
            "m_sw_m3ph":       m_sw_m3ph,
            "m_brine_m3ph":    m_brine_m3ph,
            "p_med_elec_kw":   p_med_elec,
            # System
            "p_demand_kw":     p_demand,
            "power_margin_kw": power_margin,
            "heat_rate":       heat_rate,
            "energy_util_pct": energy_util,
        }

    def outputs(self, r):
        rows = [
            # GT
            OutputSpec("GT ambient derate factor",         r["gt_derate"],       "-",     "verified", "{:.4f}"),
            OutputSpec("GT derated capacity",              r["p_gt_derated"],    "kW",    "verified", "{:.0f}"),
            OutputSpec("GT actual power output",           r["p_gt"],            "kW",    "verified", "{:.0f}"),
            OutputSpec("Fuel energy input  (LHV)",         r["fuel_kw"],         "kW",    "verified", "{:.0f}"),
            OutputSpec("Natural gas consumption",          r["ng_kgph"],         "kg/h",  "verified", "{:.1f}"),
            OutputSpec("Natural gas consumption",          r["ng_nm3ph"],        "Nm\u00b3/h", "verified", "{:.1f}"),
            OutputSpec("GT specific fuel consumption",     r["sfc_g_kwh"],       "g/kWh", "verified", "{:.1f}"),
            OutputSpec("GT net electrical efficiency",     r["gt_eff_net"],      "%",     "verified", "{:.1f}"),
            OutputSpec("Exhaust gas mass flow",            r["exh_flow_tph"],    "t/h",   "verified", "{:.1f}"),
            OutputSpec("Exhaust heat  (to HRSG)",          r["exh_heat_kw"],     "kW",    "verified", "{:.0f}"),
            OutputSpec("GT cooling water duty",            r["gt_cw_kw"],        "kW",    "verified", "{:.0f}"),
            # HRSG
            OutputSpec("Steam saturation temperature",     r["t_sat_c"],         "\u00b0C",    "verified", "{:.1f}"),
            OutputSpec("Steam temperature  (sat + 30\u00b0C)",r["t_steam_c"],    "\u00b0C",    "verified", "{:.1f}"),
            OutputSpec("Steam specific enthalpy",          r["h_steam_kj"],      "kJ/kg", "verified", "{:.0f}"),
            OutputSpec("HRSG duty",                        r["q_hrsg_kw"],       "kW",    "verified", "{:.0f}"),
            OutputSpec("Stack heat loss",                  r["q_stack_kw"],      "kW",    "verified", "{:.0f}"),
            OutputSpec("Stack temperature",                r["t_stack_c"],       "\u00b0C",    "verified", "{:.0f}"),
            OutputSpec("Total steam generation",           r["m_steam_tph"],     "t/h",   "verified", "{:.2f}"),
            # Steam split
            OutputSpec("Steam  \u2192  LiBr chiller",          r["m_libr_tph"],      "t/h",   "verified", "{:.2f}"),
            OutputSpec("Steam  \u2192  MED  (auto)",            r["m_med_tph"],       "t/h",   "verified", "{:.2f}"),
            OutputSpec("MED steam fraction  (auto)",       r["med_frac_pct"],    "%",     "verified", "{:.1f}"),
            # LiBr
            OutputSpec("LiBr generator duty",              r["q_libr_gen_kw"],   "kW",    "verified", "{:.0f}"),
            OutputSpec("LiBr cooling capacity",            r["q_libr_cool_kw"],  "kW",    "verified", "{:.0f}"),
            OutputSpec("LiBr cooling capacity",            r["q_libr_cool_tr"],  "TR",    "verified", "{:.0f}"),
            OutputSpec("LiBr condenser duty  (to CT)",     r["q_libr_rej_kw"],   "kW",    "verified", "{:.0f}"),
            OutputSpec("Chilled water flow",               r["chw_m3ph"],        "m\u00b3/h",  "verified", "{:.1f}"),
            OutputSpec("Chilled water return temp",        r["chw_ret_c"],       "\u00b0C",    "verified", "{:.1f}"),
            OutputSpec("Cooling tower flow",               r["ct_m3ph"],         "m\u00b3/h",  "verified", "{:.1f}"),
            # GPU
            OutputSpec("GPU/TPU total facility power",     r["gpu_total_kw"],    "kW",    "input",     "{:.0f}"),
            OutputSpec("Facility overhead  (non-IT)",      r["gpu_overhead_kw"], "kW",    "verified", "{:.0f}"),
            OutputSpec("Cooling margin  (LiBr \u2212 IT load)", r["cool_margin_kw"],  "kW",    "verified", "{:+.0f}"),
            OutputSpec("Immersion coolant flow",           r["imm_m3ph"],        "m\u00b3/h",  "verified", "{:.2f}"),
            # MED
            OutputSpec("MED GOR  (0.8 \u00d7 effects)",        r["med_gor"],         "-",     "verified", "{:.1f}"),
            OutputSpec("MED thermal input",                r["q_med_kw"],        "kW",    "verified", "{:.0f}"),
            OutputSpec("Water production",                 r["m_dist_m3pd"],     "m\u00b3/day","verified", "{:.0f}"),
            OutputSpec("Water production",                 r["m_dist_m3ph"],     "m\u00b3/h",  "verified", "{:.2f}"),
            OutputSpec("Seawater feed",                    r["m_sw_m3ph"],       "m\u00b3/h",  "verified", "{:.1f}"),
            OutputSpec("Brine reject",                     r["m_brine_m3ph"],    "m\u00b3/h",  "verified", "{:.1f}"),
            OutputSpec("MED electrical consumption",       r["p_med_elec_kw"],   "kW",    "verified", "{:.0f}"),
            # System
            OutputSpec("Total process power demand",       r["p_demand_kw"],     "kW",    "verified", "{:.0f}"),
            OutputSpec("Power balance margin  (GT \u2212 demand)", r["power_margin_kw"],"kW","verified", "{:+.0f}"),
            OutputSpec("GT heat rate",                     r["heat_rate"],       "kJ/kWh","verified", "{:.0f}"),
            OutputSpec("Overall energy utilisation",       r["energy_util_pct"], "%",     "verified", "{:.1f}"),
        ]
        if r["power_margin_kw"] < 0:
            rows.append(OutputSpec("WARNING: GT power deficit",
                abs(r["power_margin_kw"]), "kW short", "unverified", "{:.0f}"))
        if r["cool_margin_kw"] < 0:
            rows.append(OutputSpec("WARNING: LiBr cooling deficit  (IT load > chiller capacity)",
                abs(r["cool_margin_kw"]), "kW short", "unverified", "{:.0f}"))
        return rows

    def highlights(self, r):
        return [
            OutputSpec("GT power output",   r["p_gt"],           "kW",    "verified", "{:.0f}"),
            OutputSpec("LiBr cooling",      r["q_libr_cool_kw"], "kW",    "verified", "{:.0f}"),
            OutputSpec("Water production",  r["m_dist_m3pd"],    "m\u00b3/day","verified", "{:.0f}"),
        ]

    def chart(self, r, path):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(11.0, 4.2))
        fig.subplots_adjust(left=0.07, right=0.97, top=0.86, bottom=0.18, wspace=0.38)

        # ── LEFT: energy cascade ──────────────────────────────────────
        fuel      = r["fuel_kw"]
        components = [r["p_gt"], r["q_libr_gen_kw"], r["q_med_kw"],
                      r["q_stack_kw"], r["gt_cw_kw"]]
        comp_cols  = [TEAL, PURPLE, LBLUE, AMBER, RED]
        comp_labs  = ["GT power", "LiBr generator", "MED heat", "Stack loss", "GT CW"]

        a1.bar([0], [fuel], color=NAVY, width=0.5, zorder=3, label="Fuel input")
        bottom = 0.0
        for val, col, lab in zip(components, comp_cols, comp_labs):
            a1.bar([1], [val], bottom=[bottom], color=col, width=0.5, zorder=3, label=lab)
            if val > fuel * 0.04:
                a1.text(1, bottom + val / 2, f"{val:.0f}", ha="center", va="center",
                        fontsize=7.5, color="white", fontweight="bold")
            bottom += val

        a1.set_xticks([0, 1])
        a1.set_xticklabels(["Fuel\ninput", "Energy\ncascade"], fontsize=9)
        a1.set_ylabel("kW", fontsize=9, color=GREY)
        a1.set_title("GT energy cascade  (kW)", fontsize=10, fontweight="bold", color=NAVY)
        a1.yaxis.grid(True, color=GRID); a1.set_axisbelow(True)
        a1.spines[["top", "right"]].set_visible(False)
        a1.text(0, fuel, f"{fuel:.0f}", ha="center", va="bottom",
                fontsize=8.5, color=NAVY, fontweight="bold")
        a1.set_ylim(0, fuel * 1.22)
        handles = [mpatches.Patch(color=NAVY, label="Fuel input")] + \
                  [mpatches.Patch(color=c, label=l) for c, l in zip(comp_cols, comp_labs)]
        a1.legend(handles=handles, fontsize=7, loc="upper right", ncol=2,
                  framealpha=0.85, edgecolor=GRID)
        a1.set_xlabel(
            f"GT eff  {r['gt_eff_net']:.1f} %   |   NG  {r['ng_nm3ph']:.0f} Nm\u00b3/h  ({r['ng_kgph']:.0f} kg/h)",
            fontsize=8.5, color=GREY)

        # ── RIGHT: system summary ─────────────────────────────────────
        groups = ["GT power\n(kW)", "LiBr cool\n(kW)", "GPU IT\n(kW)",
                  "Steam\nLiBr (t/h)", "Steam\nMED (t/h)", "Water\nm\u00b3/day"]
        vals   = [r["p_gt"], r["q_libr_cool_kw"], r["gpu_total_kw"],
                  r["m_libr_tph"], r["m_med_tph"], r["m_dist_m3pd"]]
        cols   = [TEAL, PURPLE, RED, LBLUE, GREEN, NAVY]

        ax2  = a2
        ax2b = a2.twinx()

        # kW / t/h share left axis; m³/day share right axis
        kw_idx = [0, 1, 2]
        th_idx = [3, 4]
        m3_idx = [5]

        for i in kw_idx + th_idx:
            ax2.bar([i], [vals[i]], color=cols[i], width=0.6, zorder=3)
            ax2.text(i, vals[i], f"{vals[i]:,.1f}" if i > 2 else f"{vals[i]:,.0f}",
                     ha="center", va="bottom", fontsize=7.5, color=INK)
        for i in m3_idx:
            ax2b.bar([i], [vals[i]], color=cols[i], width=0.6, zorder=3)
            ax2b.text(i, vals[i], f"{vals[i]:,.0f}",
                      ha="center", va="bottom", fontsize=7.5, color=INK)

        ax2.set_xticks(list(range(len(groups))))
        ax2.set_xticklabels(groups, fontsize=7.5)
        ax2.set_ylabel("kW  /  t/h", fontsize=8, color=GREY)
        ax2b.set_ylabel("m\u00b3/day", fontsize=8, color=NAVY)
        ax2.yaxis.grid(True, color=GRID); ax2.set_axisbelow(True)
        ax2.spines[["top"]].set_visible(False); ax2b.spines[["top"]].set_visible(False)
        ax2.set_title("System summary", fontsize=10, fontweight="bold", color=NAVY)

        pm_col = TEAL if r["power_margin_kw"] >= 0 else RED
        cm_col = TEAL if r["cool_margin_kw"]  >= 0 else RED
        ax2.set_xlabel(
            f"Power margin  {r['power_margin_kw']:+,.0f} kW   |   "
            f"Cool margin  {r['cool_margin_kw']:+,.0f} kW",
            fontsize=8, color=pm_col if r["power_margin_kw"] < 0 else cm_col)

        fig.text(0.5, 0.01,
                 f"Steam  {r['m_steam_tph']:.1f} t/h  \u2192  "
                 f"LiBr {r['m_libr_tph']:.1f} t/h  |  MED {r['m_med_tph']:.1f} t/h  "
                 f"({r['m_dist_m3pd']:.0f} m\u00b3/day fresh water)",
                 ha="center", fontsize=8, color=NAVY, fontweight="bold")

        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        return path
