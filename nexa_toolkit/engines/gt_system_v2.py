"""
GT System v2 — adapter that runs the GT system through the nexablock v2
framework (Block / System / Solver) instead of the v1 trusted tool.

Reuses the existing nexablock GT System composition; exposes it through
the v1 Engine contract so the EngineTools UI can drive it. The flowsheet
chart is rendered by the §7.5 SVG renderer.

Status: draft. Physics match the v1 trusted GT tool within ±2% per
tests/test_gt_system.py, but the v2 framework itself is pre-promotion.
"""
from __future__ import annotations
import sys, os

# Ensure repo root on path so 'nexablock' and 'simulators' resolve.
_HERE = os.path.dirname(__file__)
_ROOT = os.path.normpath(os.path.join(_HERE, "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from nexa_toolkit.framework.contract import Engine, InputSpec, OutputSpec, register
from simulators.gt_system.system  import GTSystemParams, build_gt_system, summary
from nexablock.viz.svg            import render as render_svg


def _params_from(v: dict) -> GTSystemParams:
    """Build a GTSystemParams from the v1 UI input dict. Shared with subclasses."""
    return GTSystemParams(
        p_rated_kW   = float(v["p_rated_kW"]),
        load_pct     = float(v["load_pct"]),
        gt_eff       = float(v["gt_eff"]),
        t_ambient_C  = float(v["t_ambient_C"]),
        t_exhaust_C  = float(v["t_exhaust_C"]),
        hrsg_eff_pct = float(v["hrsg_eff_pct"]),
        steam_p_bar  = float(v["steam_p_bar"]),
        fw_t_C       = float(v["fw_t_C"]),
        libr_frac    = float(v["libr_frac"]),
        libr_cop     = float(v["libr_cop"]),
        chw_sup_C    = float(v["chw_sup_C"]),
        chw_dt_K     = float(v["chw_dt_K"]),
        gpu_it_kW    = float(v["gpu_it_kW"]),
        gpu_pue      = float(v["gpu_pue"]),
        med_effects  = int(v["med_effects"]),
        sw_t_C       = float(v["sw_t_C"]),
        t_wb_C       = float(v["t_wb_C"]),
    )


@register
class GTSystemV2(Engine):
    key          = "gt_system_v2"
    name         = "GT System v2 — nexablock (GT + HRSG + LiBr + GPU + MED)"
    kind         = "simulator"
    status       = "draft"
    provenance   = "v1 GT system migrated onto Nexa Block v2; flowsheet via §7.5 SVG renderer"
    notes = (
        "Runs the nexablock v2 composition (simulators/gt_system/system.py). "
        "Chart slot shows the §7.5 SVG flowsheet, not a bar chart. "
        "Block-level KPIs cross-check vs the v1 trusted GT tool within ±2% "
        "(tests/test_gt_system.py); v2 framework promotion is still pending."
    )
    chart_format = "svg"   # tells chart_src to emit SVG MIME

    inputs = [
        InputSpec("p_rated_kW",   "GT rated power",         "kW",  10_000.0,  100,    500_000),
        InputSpec("load_pct",     "GT load",                "%",   85.0,      10,     100),
        InputSpec("gt_eff",       "GT efficiency",          "-",   0.35,      0.15,   0.45),
        InputSpec("t_ambient_C",  "Ambient temperature",    "°C",  25.0,     -20,     55),
        InputSpec("t_exhaust_C",  "Exhaust temperature",    "°C",  530.0,     300,    700),
        InputSpec("hrsg_eff_pct", "HRSG effectiveness",     "%",   85.0,      50,     95),
        InputSpec("steam_p_bar",  "Steam pressure",         "bar", 10.0,      1,      40),
        InputSpec("fw_t_C",       "Feedwater temperature",  "°C",  80.0,      20,     150),
        InputSpec("libr_frac",    "Steam fraction to LiBr", "-",   0.50,      0.05,   0.95),
        InputSpec("libr_cop",     "LiBr COP",               "-",   0.70,      0.5,    0.85),
        InputSpec("chw_sup_C",    "CHW supply temp",        "°C",  7.0,       4,      15),
        InputSpec("chw_dt_K",     "CHW ΔT",                 "K",   6.0,       2,      15),
        InputSpec("gpu_it_kW",    "GPU IT load",            "kW",  5_000.0,   100,    200_000),
        InputSpec("gpu_pue",      "GPU PUE",                "-",   1.05,      1.0,    2.0),
        InputSpec("med_effects",  "MED effects",            "-",   8.0,       1,      16),
        InputSpec("sw_t_C",       "Seawater temp",          "°C",  28.0,      0,      45),
        InputSpec("t_wb_C",       "Cooling tower wet-bulb", "°C",  25.0,     -5,      38),
    ]

    def solve(self, v: dict) -> dict:
        solved = build_gt_system(_params_from(v))
        return {"solved": solved, "kpis": summary(solved)}

    def outputs(self, r: dict) -> list:
        k = r["kpis"]
        return [
            OutputSpec("GT actual power",       k["GT actual power kW"],   "kW",     "screening", "{:.0f}"),
            OutputSpec("NG consumption",        k["NG consumption Nm3h"],  "Nm³/h",  "screening", "{:.0f}"),
            OutputSpec("Steam generation",      k["Steam generation t/h"], "t/h",    "screening", "{:.2f}"),
            OutputSpec("LiBr cooling capacity", k["LiBr cooling kW"],      "kW",     "screening", "{:.0f}"),
            OutputSpec("GPU IT load",           k["GPU IT load kW"],       "kW",     "screening", "{:.0f}"),
            OutputSpec("MED water production",  k["MED water m3day"],      "m³/day", "screening", "{:.0f}"),
        ]

    def highlights(self, r: dict) -> list:
        outs = self.outputs(r)
        return [outs[0], outs[2], outs[5]]   # GT power, steam, water

    def chart(self, r: dict, path: str) -> str:
        with open(path, "w", encoding="utf-8") as f:
            f.write(render_svg(r["solved"]))
        return path

    def study_hooks(self) -> dict:
        """Plumbing the studies layer (sweep / sensitivity / scenarios) needs.

        Anything the v1 UI surfaces as a "Run study" button reads this:
          builder + make_params → produce a SolvedSystem from input dict v
          kpi_fn                → extract the named KPIs from the solved system
          kpis                  → which KPIs to plot by default
          sensitivity_inputs    → inputs to perturb (OAT)
          sweep_inputs          → inputs offered in the sweep picker dropdown
          bounds                → physical limits, used for sensitivity clamp and sweep range
          step_override         → per-input absolute sensitivity step (integer-flavoured fields)
          scenarios             → built-in named bundles for the scenarios button
        """
        return {
            "builder":      build_gt_system,
            "make_params":  _params_from,
            "kpi_fn":       summary,
            "kpis":         ["GT actual power kW", "Steam generation t/h",
                             "LiBr cooling kW",    "MED water m3day"],
            "sensitivity_inputs": ["load_pct", "gt_eff", "libr_frac", "libr_cop",
                                   "hrsg_eff_pct", "med_effects", "t_ambient_C"],
            "sweep_inputs": ["load_pct", "gt_eff", "libr_frac", "libr_cop",
                             "hrsg_eff_pct", "t_ambient_C"],
            "bounds": {
                "load_pct":     (10.0, 100.0),
                "gt_eff":       (0.15,  0.45),
                "libr_frac":    (0.05,  0.95),
                "libr_cop":     (0.5,   0.85),
                "hrsg_eff_pct": (50.0,  95.0),
                "t_ambient_C":  (-10.0, 55.0),
            },
            "step_override": {"med_effects": 1.0},
            "scenarios": {
                "summer peak":     {"t_ambient_C": 40.0, "load_pct": 100.0, "t_wb_C": 30.0},
                "winter low load": {"t_ambient_C":  5.0, "load_pct":  40.0, "t_wb_C": 10.0},
            },
        }
