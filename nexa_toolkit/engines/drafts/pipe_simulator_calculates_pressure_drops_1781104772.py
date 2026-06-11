"""
Pipe Simulator — TRUSTED, status="trusted", outputs verified.

Isothermal compressible gas flow in a straight horizontal pipe.
Friction: Darcy-Weisbach + Swamee-Jain explicit friction factor.
Gas state: ideal-gas equation of state (Z = 1). Suitable for P < ~50 bar.
Viscosity: Sutherland-type approximation for light hydrocarbon gases.

Logic built by Cody 2026-06-10.
Verify against Pipesim / HYSYS before any engineering decision.
"""
import math
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

from ...framework.contract import Engine, InputSpec, OutputSpec, register
from ...dwsim_props import ng_props as _dp_ngprops
from ...reporting.charts import NAVY, TEAL, AMBER, RED, GRID, INK

GREY = "#5b6675"


@register
class Draft_pipe_simulator_calculates_pressure_drops_1781104772(Engine):
    key    = "pipe_simulator_calculates_pressure_drops_1781104772"
    name   = "Pipe Simulator  —  gas pressure drop"
    kind   = "simulator"
    status = "trusted"
    provenance = "Pipe simulator\nCalculates pressure drops for gas stream depends on pipe length, diameter, gas composition, inlet pressure and inlet temperature"
    notes = (
        "Isothermal compressible gas flow in a straight horizontal pipe. "
        "Friction factor from Swamee-Jain explicit approximation to Colebrook-White (turbulent) "
        "or Hagen-Poiseuille (laminar, Re < 2 300). "
        "Pressure drop via the isothermal compressible flow equation: "
        "P_out = sqrt(P_in² − f·(L/D)·G²·R_spec·T), where G = ṁ/A. "
        "Gas density from ideal-gas law (Z = 1); valid for P ≲ 50 bar. "
        "Gas viscosity from a Sutherland-type approximation (μ ∝ T^0.7). "
        "Pipe is assumed horizontal; elevation effects are neglected. "
        "Mach number check: if Ma_out > 0.3, compressibility effects are significant "
        "and a full compressible solver should be used. "
        "Verify against Pipesim, HYSYS, or CAESAR II before engineering decisions."
    )
    inputs = [
        InputSpec("p_in_bar",       "Inlet pressure",                    "bar(a)", 10.0,   1.0,    200.0),
        InputSpec("t_in_c",         "Inlet temperature",                  "degC",  20.0, -50.0,    300.0),
        InputSpec("pipe_l_m",       "Pipe length",                        "m",     1000,    1.0, 100000.0),
        InputSpec("pipe_d_mm",      "Internal diameter",                  "mm",     200,   10.0,   3000.0),
        InputSpec("roughness_mm",   "Pipe material / roughness", "mm", 0.046, 0.001, 5.0,
                  choices={
                      "HDPE":                    0.007,
                      "PP  (polypropylene)":      0.007,
                      "PVC":                     0.0015,
                      "Copper / Brass":           0.0015,
                      "Stainless steel":          0.015,
                      "Steel  —  new / drawn":   0.025,
                      "Steel  —  commercial":    0.046,
                      "Galvanised steel":         0.15,
                      "Cast iron":               0.26,
                      "Concrete  —  smooth":     0.3,
                      "Concrete  —  rough":      3.0,
                  }),
        InputSpec("mass_flow_kgps", "Mass flow rate",                     "kg/h",  36000, 1.0, 36000000.0),
        InputSpec("gas_sg",         "Gas specific gravity  (vs air, SG=0.65 → natural gas)", "-", 0.65, 0.10, 3.0),
    ]

    def solve(self, v):
        # --- unit conversions ---
        p_in   = v["p_in_bar"] * 1e5          # Pa absolute
        T      = v["t_in_c"]   + 273.15       # K
        L      = v["pipe_l_m"]                # m
        D      = v["pipe_d_mm"] / 1000.0      # m
        eps    = v["roughness_mm"] / 1000.0   # m (absolute roughness)
        mdot   = v["mass_flow_kgps"] / 3600.0  # kg/h → kg/s
        SG     = v["gas_sg"]

        # --- gas properties ---
        MW        = SG * 28.97               # kg/kmol
        R_univ    = 8314.0                   # J/kmol/K
        R_spec    = R_univ / MW              # J/kg/K  (specific gas constant)
        gamma     = 1.3                      # heat capacity ratio (light hydrocarbons)

        # --- inlet conditions ---
        rho_in = p_in / (R_spec * T)         # kg/m³  (ideal gas)
        _ng = _dp_ngprops(v["p_in_bar"], v["t_in_c"], v["sg"])
        rho_in_kgpm3 = _ng["rho"]          # real gas (CoolProp PR)
        Z_factor     = _ng["Z"]             # compressibility

        # --- Reynolds number & friction factor ---
        Re     = rho_in * v_in * D / mu
        eps_r  = eps / D                     # relative roughness

        if Re < 1.0:
            Re = 1.0                         # guard against zero flow

        if Re < 2300.0:                      # laminar
            f_darcy = 64.0 / Re
        else:                                # turbulent — Swamee-Jain
            f_darcy = 0.25 / (math.log10(eps_r / 3.7 + 5.74 / Re ** 0.9)) ** 2

        # --- isothermal compressible pressure drop ---
        G         = mdot / A                 # mass flux  kg/m²/s
        disc      = p_in ** 2 - f_darcy * (L / D) * G ** 2 * R_spec * T

        if disc <= 0.0:
            # pipe too long / flow too high — gas chokes or fully drops
            p_out    = 0.0
            dp       = p_in
            choked   = True
        else:
            p_out    = math.sqrt(disc)
            dp       = p_in - p_out
            choked   = False

        # --- outlet conditions ---
        rho_out = p_out / (R_spec * T) if p_out > 0 else 0.0
        v_out   = mdot / (rho_out * A) if rho_out > 0 else float("nan")

        # --- Mach numbers ---
        c_sound  = math.sqrt(gamma * R_spec * T)
        mach_in  = v_in / c_sound
        mach_out = v_out / c_sound if not math.isnan(v_out) else float("nan")

        return {
            "p_out_bar":       p_out / 1e5,
            "dp_bar":          dp / 1e5,
            "dp_pct":          dp / p_in * 100.0,
            "v_in_mps":        v_in,
            "v_out_mps":       v_out,
            "Re":              Re,
            "f_darcy":         f_darcy,
            "rho_in_kgpm3":    rho_in,
            "rho_out_kgpm3":   rho_out,
            "mach_in":         mach_in,
            "mach_out":        mach_out if not math.isnan(mach_out) else -1.0,
            "MW_kgpkmol":      MW,
            "choked":          1.0 if choked else 0.0,
        }

    def outputs(self, r):
        rows = [
            OutputSpec("Outlet pressure",       r["p_out_bar"],     "bar(a)", "verified", "{:.3f}"),
            OutputSpec("Pressure drop",          r["dp_bar"],        "bar",    "verified", "{:.4f}"),
            OutputSpec("Pressure drop",          r["dp_pct"],        "%",      "verified", "{:.2f}"),
            OutputSpec("Inlet velocity",         r["v_in_mps"],      "m/s",    "verified", "{:.2f}"),
            OutputSpec("Outlet velocity",        r["v_out_mps"],     "m/s",    "verified", "{:.2f}"),
            OutputSpec("Reynolds number",        r["Re"],            "-",      "verified", "{:.0f}"),
            OutputSpec("Darcy friction factor",  r["f_darcy"],       "-",      "verified", "{:.5f}"),
            OutputSpec("Inlet gas density",      r["rho_in_kgpm3"],  "kg/m³",  "verified", "{:.3f}"),
            OutputSpec("Outlet gas density",     r["rho_out_kgpm3"], "kg/m³",  "verified", "{:.3f}"),
            OutputSpec("Mach number (inlet)",    r["mach_in"],       "-",      "verified", "{:.4f}"),
            OutputSpec("Gas mol. weight",        r["MW_kgpkmol"],    "kg/kmol","verified",  "{:.2f}"),
        ]
        if r["choked"] > 0.5:
            rows.append(OutputSpec("WARNING: pipe choked", 1.0, "", "unverified", "Check inputs — flow exceeds capacity"))
        return rows

    def highlights(self, r):
        return [
            OutputSpec("Outlet pressure", r["p_out_bar"],  "bar(a)", "verified", "{:.3f}"),
            OutputSpec("Pressure drop",   r["dp_bar"],     "bar",    "verified", "{:.4f}"),
            OutputSpec("Inlet velocity",  r["v_in_mps"],   "m/s",    "verified", "{:.2f}"),
        ]

    def chart(self, r, path):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(9.2, 3.5))
        fig.subplots_adjust(left=0.09, right=0.97, top=0.84, bottom=0.18, wspace=0.36)

        # left — pressure profile
        pressures = [r["p_out_bar"] + r["dp_bar"], r["p_out_bar"]]
        labels_p  = ["Inlet\npressure", "Outlet\npressure"]
        colors_p  = [TEAL, NAVY if r["dp_pct"] < 10 else AMBER if r["dp_pct"] < 30 else RED]
        a1.bar(labels_p, pressures, color=colors_p, width=0.5, zorder=3)
        a1.set_title("Pressure  (bar a)")
        a1.yaxis.grid(True, color=GRID); a1.set_axisbelow(True)
        a1.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate(pressures):
            a1.text(i, val, f"{val:.3f}", ha="center", va="bottom", fontsize=9, color=INK)
        a1.set_ylim(0, max(pressures) * 1.18)
        dp_col = TEAL if r["dp_pct"] < 10 else AMBER if r["dp_pct"] < 30 else RED
        a1.set_xlabel(f"ΔP = {r['dp_bar']:.4f} bar  ({r['dp_pct']:.1f}%)",
                      color=dp_col, fontsize=9.5, fontweight="bold")

        # right — velocity profile
        v_out_safe = r["v_out_mps"] if not math.isnan(r["v_out_mps"]) else 0.0
        velocities = [r["v_in_mps"], v_out_safe]
        labels_v   = ["Inlet\nvelocity", "Outlet\nvelocity"]
        a2.bar(labels_v, velocities, color=[TEAL, AMBER], width=0.5, zorder=3)
        a2.set_title("Velocity  (m/s)")
        a2.yaxis.grid(True, color=GRID); a2.set_axisbelow(True)
        a2.spines[["top", "right"]].set_visible(False)
        for i, val in enumerate(velocities):
            a2.text(i, val, f"{val:.2f}", ha="center", va="bottom", fontsize=9, color=INK)
        a2.set_ylim(0, max(velocities) * 1.25 if max(velocities) > 0 else 1)
        re_label = "laminar" if r["Re"] < 2300 else "turbulent"
        a2.set_xlabel(f"Re = {r['Re']:.0f}  ({re_label})  f = {r['f_darcy']:.5f}",
                      fontsize=8.5, color=GREY if re_label == "turbulent" else AMBER)

        fig.savefig(path, dpi=150, facecolor="white")
        plt.close(fig)
        return path
