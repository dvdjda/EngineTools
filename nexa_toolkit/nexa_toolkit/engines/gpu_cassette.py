"""System 2: immersed-GPU cassette - mass and energy balance.

Single-phase immersion cooling. The heat to remove equals the electrical power into
the cassette; coolant flow follows from Q = m * cp * dT. This heat load is what the
LiBr chiller (system 1) has to meet - the integration link toward the whole-plant model.
"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ..framework.contract import Engine, InputSpec, OutputSpec, register
from ..reporting.charts import NAVY, TEAL, AMBER, GRID, INK


@register
class GpuCassette(Engine):
    key = "gpu_cassette"
    name = "Immersed-GPU cassette - mass and energy balance"
    notes = ("Energy balance: heat to remove = electrical power into the cassette "
             "(essentially all IT power becomes heat). Coolant flow from Q = m*cp*dT. "
             "The heat load sets the cooling duty handed to the chiller. Flow figures "
             "depend on the coolant properties entered.")
    inputs = [
        InputSpec("n_gpu", "GPUs per cassette", "-", 72, 1, 2000),
        InputSpec("p_gpu_kw", "Power per GPU", "kW", 1.0, 0.1, 5.0),
        InputSpec("aux_frac", "Non-GPU overhead", "frac", 0.15, 0.0, 1.0),
        InputSpec("coolant_cp", "Coolant specific heat", "kJ/kg.K", 2.10, 1.0, 5.0),
        InputSpec("coolant_rho", "Coolant density", "kg/m3", 780, 500, 1200),
        InputSpec("t_supply_c", "Coolant supply temp", "degC", 30, 10, 50),
        InputSpec("dt_coolant", "Coolant temperature rise", "K", 12, 2, 40),
    ]

    def solve(self, v):
        it_power = v["n_gpu"] * v["p_gpu_kw"]
        q = it_power * (1 + v["aux_frac"])
        m = q / (v["coolant_cp"] * v["dt_coolant"])
        vol_lpm = m / v["coolant_rho"] * 1000 * 60
        return {
            "it_power_kw": it_power,
            "heat_load_kw": q,
            "coolant_mass_flow_kgps": m,
            "coolant_vol_flow_lpm": vol_lpm,
            "t_supply_c": v["t_supply_c"],
            "t_return_c": v["t_supply_c"] + v["dt_coolant"],
        }

    def outputs(self, r):
        return [
            OutputSpec("IT power (GPUs)", r["it_power_kw"], "kW", "verified", "{:.1f}"),
            OutputSpec("Heat load to remove", r["heat_load_kw"], "kW", "verified", "{:.1f}"),
            OutputSpec("Coolant mass flow", r["coolant_mass_flow_kgps"], "kg/s", "input", "{:.2f}"),
            OutputSpec("Coolant volume flow", r["coolant_vol_flow_lpm"], "L/min", "input", "{:.0f}"),
            OutputSpec("Coolant supply temp", r["t_supply_c"], "degC", "input", "{:.1f}"),
            OutputSpec("Coolant return temp", r["t_return_c"], "degC", "input", "{:.1f}"),
        ]

    def highlights(self, r):
        return [
            OutputSpec("Heat load", r["heat_load_kw"], "kW", "verified", "{:.0f}"),
            OutputSpec("Coolant flow", r["coolant_vol_flow_lpm"], "L/min", "input", "{:.0f}"),
            OutputSpec("Return temp", r["t_return_c"], "degC", "input", "{:.1f}"),
        ]

    def chart(self, r, path):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.5))
        fig.subplots_adjust(left=0.10, right=0.97, top=0.84, bottom=0.14, wspace=0.32)
        a1.bar(["IT power", "Heat load"], [r["it_power_kw"], r["heat_load_kw"]],
               color=[NAVY, TEAL], width=0.5, zorder=3)
        a1.set_title("Cassette heat (kW)")
        a1.yaxis.grid(True, color=GRID); a1.set_axisbelow(True)
        a1.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate([r["it_power_kw"], r["heat_load_kw"]]):
            a1.text(i, val, f"{val:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
        a1.set_ylim(0, r["heat_load_kw"] * 1.18)
        a2.bar(["Supply", "Return"], [r["t_supply_c"], r["t_return_c"]],
               color=[TEAL, AMBER], width=0.5, zorder=3)
        a2.set_title(f"Coolant temps (degC)  -  {r['coolant_vol_flow_lpm']:.0f} L/min")
        a2.yaxis.grid(True, color=GRID); a2.set_axisbelow(True)
        a2.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate([r["t_supply_c"], r["t_return_c"]]):
            a2.text(i, val, f"{val:.1f}", ha="center", va="bottom", fontsize=9, color=INK)
        a2.set_ylim(0, r["t_return_c"] * 1.25)
        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        return path
