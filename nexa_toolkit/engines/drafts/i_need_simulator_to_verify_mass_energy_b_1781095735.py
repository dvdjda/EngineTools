"""
Plant mass/energy balance example  —  DRAFT, status="draft", outputs unverified.

Screening-grade whole-plant integration check:
  Gas turbines  →  GPU data-centre  →  LiBr absorption chiller (waste-heat driven).

Logic built by Cody 2026-06-10.
Verify numbers against turbine manufacturer data and ChemCAD before any
engineering decision. Promote to trusted only after David's verification.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ...framework.contract import Engine, InputSpec, OutputSpec, register
from ...reporting.charts import NAVY, TEAL, AMBER, RED, GRID, INK


@register
class Draft_i_need_simulator_to_verify_mass_energy_b_1781095735(Engine):
    key      = "i_need_simulator_to_verify_mass_energy_b_1781095735"
    name     = "Plant mass/energy balance example"
    kind     = "simulator"
    status   = "draft"
    provenance = (
        "I need simulator to verify mass/energy balance of a example system of 8 gas turbines "
        "total maximum 10MW output, to supply energy to data center with total Immersed GPU IT "
        "power 6MW, the GPU cooling system and return cooling water to turbine pass through LiBr "
        "absorption chiller. Inputs: Generating maximum power, GPU IT power, auxiliary power "
        "consumption such as pumps and funs. Output - convergency of the planned system with "
        "mass/energy balance."
    )
    notes = (
        "Screening-grade whole-plant mass/energy balance. "
        "Three subsystems linked: (1) simple-cycle gas turbines supply electrical power and "
        "exhaust heat; (2) GPU data-centre converts IT power entirely to heat; "
        "(3) LiBr absorption chiller uses recovered exhaust heat to reject the GPU heat load. "
        "Two convergence indicators — power margin and heat-source margin — must both be ≥ 0 "
        "for the system to close. "
        "GT efficiency and exhaust recovery are screening inputs; "
        "verify against manufacturer data and ChemCAD before any engineering decision."
    )
    inputs = [
        InputSpec("n_turbines",   "Gas turbines in service",           "-",   8,    1,    8),
        InputSpec("p_turbine_kw", "Rated power per turbine",           "kW",  1250, 100,  2000),
        InputSpec("p_it_kw",      "GPU IT load  (total)",              "kW",  6000, 100,  20000),
        InputSpec("p_aux_kw",     "Auxiliary loads  (pumps/fans/misc)", "kW",  500,  0,    5000),
        InputSpec("gt_elec_eff",  "Gas turbine electrical efficiency",  "-",   0.33, 0.20, 0.45),
        InputSpec("exhaust_rec",  "Exhaust heat recovery fraction",     "-",   0.70, 0.30, 0.90),
        InputSpec("chiller_cop",  "LiBr chiller COP  (screening)",      "-",   0.70, 0.50, 0.85),
    ]

    def solve(self, v):
        # --- power generation ---
        p_total_kw      = v["n_turbines"] * v["p_turbine_kw"]
        p_demand_kw     = v["p_it_kw"] + v["p_aux_kw"]
        power_margin_kw = p_total_kw - p_demand_kw

        # --- exhaust / waste heat ---
        # fuel energy in = electrical out / efficiency
        fuel_input_kw    = p_total_kw / max(v["gt_elec_eff"], 1e-6)
        exhaust_total_kw = fuel_input_kw - p_total_kw       # heat not converted to electricity
        exhaust_avail_kw = exhaust_total_kw * v["exhaust_rec"]  # recoverable fraction

        # --- GPU heat load ---
        gpu_heat_kw = v["p_it_kw"]          # all IT power becomes heat (conservative)

        # --- LiBr chiller (screening: Q_cooling = COP × Q_generator) ---
        q_gen_kw           = gpu_heat_kw / max(v["chiller_cop"], 1e-6)
        q_cond_kw          = gpu_heat_kw + q_gen_kw     # condenser duty
        heat_src_margin_kw = exhaust_avail_kw - q_gen_kw

        return {
            "p_total_kw":         p_total_kw,
            "p_demand_kw":        p_demand_kw,
            "power_margin_kw":    power_margin_kw,
            "fuel_input_kw":      fuel_input_kw,
            "exhaust_total_kw":   exhaust_total_kw,
            "exhaust_avail_kw":   exhaust_avail_kw,
            "gpu_heat_kw":        gpu_heat_kw,
            "q_gen_kw":           q_gen_kw,
            "q_cond_kw":          q_cond_kw,
            "heat_src_margin_kw": heat_src_margin_kw,
        }

    def outputs(self, r):
        return [
            OutputSpec("Total turbine output",        r["p_total_kw"],         "kW", "screening", "{:.0f}"),
            OutputSpec("Total demand  (IT + aux)",     r["p_demand_kw"],        "kW", "input",     "{:.0f}"),
            OutputSpec("Power balance margin",         r["power_margin_kw"],    "kW", "screening", "{:+.0f}"),
            OutputSpec("Fuel input  (all turbines)",   r["fuel_input_kw"],      "kW", "screening", "{:.0f}"),
            OutputSpec("Exhaust heat  (total)",        r["exhaust_total_kw"],   "kW", "screening", "{:.0f}"),
            OutputSpec("Exhaust heat recovered",       r["exhaust_avail_kw"],   "kW", "screening", "{:.0f}"),
            OutputSpec("GPU heat load",                r["gpu_heat_kw"],        "kW", "input",     "{:.0f}"),
            OutputSpec("Chiller generator duty",       r["q_gen_kw"],           "kW", "screening", "{:.0f}"),
            OutputSpec("Chiller condenser duty",       r["q_cond_kw"],          "kW", "screening", "{:.0f}"),
            OutputSpec("Heat-source margin",           r["heat_src_margin_kw"], "kW", "screening", "{:+.0f}"),
        ]

    def highlights(self, r):
        return [
            OutputSpec("Power margin",       r["power_margin_kw"],    "kW", "screening", "{:+.0f}"),
            OutputSpec("Heat-source margin", r["heat_src_margin_kw"], "kW", "screening", "{:+.0f}"),
            OutputSpec("Turbine output",     r["p_total_kw"],         "kW", "screening", "{:.0f}"),
        ]

    def chart(self, r, path):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.5))
        fig.subplots_adjust(left=0.09, right=0.97, top=0.84, bottom=0.18, wspace=0.34)

        # left panel — power balance
        vals_p  = [r["p_total_kw"], r["p_demand_kw"]]
        labels_p = ["Turbine\noutput", "IT + Aux\ndemand"]
        a1.bar(labels_p, vals_p, color=[TEAL, NAVY], width=0.5, zorder=3)
        a1.set_title("Power balance (kW)")
        a1.yaxis.grid(True, color=GRID); a1.set_axisbelow(True)
        a1.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate(vals_p):
            a1.text(i, val, f"{val:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        m_col = TEAL if r["power_margin_kw"] >= 0 else RED
        a1.set_xlabel(f"margin  {r['power_margin_kw']:+.0f} kW",
                      color=m_col, fontsize=9.5, fontweight="bold")
        a1.set_ylim(0, max(vals_p) * 1.18)

        # right panel — heat balance
        vals_h  = [r["exhaust_avail_kw"], r["q_gen_kw"]]
        labels_h = ["Exhaust\nrecovered", "Chiller\ngenerator"]
        a2.bar(labels_h, vals_h, color=[AMBER, NAVY], width=0.5, zorder=3)
        a2.set_title("Heat balance (kW)")
        a2.yaxis.grid(True, color=GRID); a2.set_axisbelow(True)
        a2.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate(vals_h):
            a2.text(i, val, f"{val:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        h_col = TEAL if r["heat_src_margin_kw"] >= 0 else RED
        a2.set_xlabel(f"margin  {r['heat_src_margin_kw']:+.0f} kW",
                      color=h_col, fontsize=9.5, fontweight="bold")
        a2.set_ylim(0, max(vals_h) * 1.18)

        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        return path
