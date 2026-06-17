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
from simulators.gt_system.system       import GTSystemParams, build_gt_system, summary
from simulators.gt_system.feasibility  import feasibility
from simulators.gt_system.audit         import gt_system_audit_checks
from nexablock.audit                    import audit
from nexablock.viz.svg                 import render as render_svg


_MODE_NUM_TO_OP   = {0: "island", 1: "grid_tied"}
_MODE_NUM_TO_GTP  = {0: "auto", 1: "manual"}
_MODE_NUM_TO_SPL  = {0: "auto", 1: "manual"}
_MODE_NUM_TO_MED  = {0: "manual", 1: "auto"}
_MODE_NUM_TO_SPLIT = {0: "off", 1: "auto"}


def _params_from(v: dict) -> GTSystemParams:
    """Build a GTSystemParams from the v1 UI input dict. Shared with subclasses.

    Mode inputs are encoded as small integers via InputSpec.choices, so we
    translate them here. When a mode is `auto`, the corresponding manual
    input (load_pct / libr_frac / external_load_kW in grid) is read but
    ignored by the controller — it's only used in manual mode."""
    return GTSystemParams(
        p_rated_kW   = float(v["p_rated_kW"]),
        load_pct     = float(v["load_pct"]),
        gt_eff       = float(v["gt_eff"]),
        t_ambient_C  = float(v["t_ambient_C"]),
        t_exhaust_C  = float(v["t_exhaust_C"]),
        hrsg_eff_pct = float(v["hrsg_eff_pct"]),
        steam_p_bar  = float(v["steam_p_bar"]),
        fw_t_C       = float(v["fw_t_C"]),
        libr_cop     = float(v["libr_cop"]),
        gpu_t_in_C   = float(v["gpu_t_in_C"]),
        gpu_t_out_C  = float(v["gpu_t_out_C"]),
        coolant_cp   = float(v.get("coolant_cp",  2100.0)),
        coolant_rho  = float(v.get("coolant_rho",  780.0)),
        libr_reject_t_C = float(v.get("libr_reject_t_C", 95.0)),
        gpu_it_kW    = float(v["gpu_it_kW"]),
        cassette_pue = float(v["cassette_pue"]),
        med_effects  = int(v["med_effects"]),
        sw_t_C       = float(v["sw_t_C"]),
        med_bypass_frac     = float(v.get("med_bypass_frac",     0.0)),
        med_bypass_mode     = _MODE_NUM_TO_MED.get(int(v.get("med_bypass_mode", 1)), "auto"),
        med_cold_pinch_K    = float(v.get("med_cold_pinch_K",    15.0)),
        steam_split_mode    = _MODE_NUM_TO_SPLIT.get(int(v.get("steam_split_mode", 0)), "off"),
        radiator_approach_K = float(v.get("radiator_approach_K", 15.0)),
        gt_aux_frac    = float(v.get("gt_aux_frac",    0.010)),
        libr_pump_frac = float(v.get("libr_pump_frac", 0.015)),
        ct_fan_frac    = float(v.get("ct_fan_frac",    0.015)),
        bop_frac       = float(v.get("bop_frac",       0.010)),
        # Plant-electrical model (IT/flow-driven): pump heads/η, fan, HVAC envelope.
        pump_eta          = float(v.get("pump_eta",          0.70)),
        dp_diel_bar       = float(v.get("dp_diel_bar",       1.5)),
        dp_loop_bar       = float(v.get("dp_loop_bar",       3.0)),
        dp_bfp_bar        = float(v.get("dp_bfp_bar",        9.0)),
        # One "Seawater / MED pump head" knob drives all the low-head desal +
        # condensate-return pumps (seawater intake, MED feed, brine, distillate,
        # condensate) — they share the same ~2-bar duty.
        dp_sw_bar         = float(v.get("dp_sw_bar",         2.0)),
        dp_med_feed_bar   = float(v.get("dp_sw_bar",         2.0)),
        dp_brine_bar      = float(v.get("dp_sw_bar",         2.0)),
        dp_dist_bar       = float(v.get("dp_sw_bar",         2.0)),
        dp_cond_bar       = float(v.get("dp_sw_bar",         2.0)),
        fan_rated_frac    = float(v.get("fan_rated_frac",    0.015)),
        containers_per_MW = float(v.get("containers_per_MW", 3.0)),
        container_area_m2 = float(v.get("container_area_m2", 70.0)),
        container_U       = float(v.get("container_U",       0.5)),
        container_inside_C= float(v.get("container_inside_C",27.0)),
        lights_frac       = float(v.get("lights_frac",       0.25)),
        operating_mode    = _MODE_NUM_TO_OP.get(int(v.get("operating_mode",    0)), "island"),
        gt_power_mode     = _MODE_NUM_TO_GTP.get(int(v.get("gt_power_mode",    0)), "auto"),
        external_load_kW  = float(v.get("external_load_kW", 0.0)),
    )


@register
class GTSystemV2(Engine):
    key          = "gt_system_v2"
    name         = "GT System v2 — nexablock (GT + HRSG + LiBr + GPU + MED)"
    kind         = "simulator"
    status       = "trusted"
    provenance   = "v1 GT system migrated onto Nexa Block v2; flowsheet via §7.5 SVG renderer; promoted to trusted after 14/14 ±2% validation pass"
    notes = (
        "Runs the nexablock v2 composition (simulators/gt_system/system.py). "
        "Chart slot shows the §7.5 SVG flowsheet. "
        "Validated vs the v1 trusted GT tool within ±2%, 14/14 checks pass "
        "(tests/test_gt_system.py)."
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
        InputSpec("fw_t_C",       "HRSG feedwater / loop return set-point", "°C", 80.0, 20, 150),
        InputSpec("libr_cop",     "LiBr COP",               "-",   0.70,      0.5,    0.85),
        InputSpec("steam_split_mode", "Steam split (surplus → MED via calorifier)", "-", 0, 0, 1,
                  choices={"Off (all steam → LiBr)": 0,
                           "Auto (LiBr-priority, surplus → calorifier)": 1}),
        InputSpec("gpu_t_in_C",   "GPU coolant T_in (dielectric)",  "°C", 30.0, 5,  45),
        InputSpec("gpu_t_out_C",  "GPU coolant T_out (dielectric)", "°C", 42.0, 10, 60),
        InputSpec("coolant_cp",   "Dielectric coolant cp",    "J/(kg·K)", 2100.0, 1000, 4500),
        InputSpec("coolant_rho",  "Dielectric coolant density", "kg/m³",  780.0,  600,  1800),
        InputSpec("libr_reject_t_C", "LiBr rejection temperature", "°C", 95.0, 60, 130),
        InputSpec("gpu_it_kW",    "GPU IT load",            "kW",  5_000.0,   100,    200_000),
        InputSpec("cassette_pue", "Cassette PUE",           "-",   1.05,      1.0,    2.0),
        InputSpec("med_effects",  "MED effects",            "-",   8.0,       1,      16),
        InputSpec("sw_t_C",       "Seawater temp",          "°C",  28.0,      0,      45),
        InputSpec("med_bypass_frac", "MED bypass (manual, 0–1)", "-", 0.0, 0.0, 1.0),
        InputSpec("med_bypass_mode", "MED bypass control", "-", 1, 0, 1,
                  choices={"Manual (use fraction above)": 0,
                           "Auto (hold HRSG return set-point)": 1}),
        InputSpec("med_cold_pinch_K", "MED cold-end approach above seawater (auto)",
                  "K", 15.0, 5.0, 40.0),
        InputSpec("radiator_approach_K", "Radiator approach to ambient", "K", 15.0, 3, 30),
        # Plant-electrical model (IT/flow-driven). GT aux is the GT package's
        # own parasitic — an internal de-rate (GT net = gross − GT aux).
        InputSpec("gt_aux_frac",    "GT aux fraction (of derated cap)",      "-", 0.010, 0.0, 0.05),
        # Pumps: each P = Q·ΔP / η. Heads in bar; η shared across all pumps.
        InputSpec("pump_eta",       "Pump efficiency (all pumps)",           "-", 0.70, 0.30, 0.90),
        InputSpec("dp_diel_bar",    "Dielectric coolant loop head",          "bar", 1.5, 0.5, 8.0),
        InputSpec("dp_loop_bar",    "Cooling-water loop head",               "bar", 3.0, 0.5, 8.0),
        InputSpec("dp_bfp_bar",     "HRSG feed-water pump head",             "bar", 9.0, 1.0, 30.0),
        InputSpec("dp_sw_bar",      "Seawater / MED pump head",              "bar", 2.0, 0.5, 8.0),
        # Dry-cooler fan: VSD cube law on dry-cooler utilisation.
        InputSpec("fan_rated_frac", "Dry-cooler fan at full duty (of Q_cond)","-", 0.015, 0.0, 0.05),
        # Container-envelope HVAC + lights.
        InputSpec("containers_per_MW","40' containers per MW IT",            "-", 3.0, 1.0, 10.0),
        InputSpec("container_area_m2","Container external area",             "m²", 70.0, 30.0, 150.0),
        InputSpec("container_U",      "Envelope U-value",            "W/(m²·K)", 0.5, 0.1, 2.0),
        InputSpec("container_inside_C","Container inside set-point",         "°C", 27.0, 15.0, 35.0),
        InputSpec("lights_frac",      "Lights (fraction of HVAC)",           "-", 0.25, 0.0, 1.0),
        # Operating + control modes (dimensionless: no unit shown,
        # no Custom… entry — pure two-state selectors).
        InputSpec("operating_mode",   "Operating mode",                "-", 0, 0, 1,
                  choices={"Island": 0, "Grid-tied": 1}),
        InputSpec("gt_power_mode",    "GT power control",              "-", 0, 0, 1,
                  choices={"Auto (follow NEXA demand)": 0,
                            "Manual (use load_pct above)": 1}),
        InputSpec("external_load_kW", "External load (kW) — island mode only",
                  "kW", 0.0, 0.0, 1_000_000.0),
    ]

    def solve(self, v: dict) -> dict:
        params = _params_from(v)
        solved = build_gt_system(params)
        return {
            "solved":      solved,
            "kpis":        summary(solved),
            "feasibility": feasibility(solved, bop_frac=params.bop_frac),
            "audit":       audit(solved,
                                  extra_checks=gt_system_audit_checks(
                                      solved, bop_frac=params.bop_frac)),
            "inputs":      dict(v),   # stash so chart()/PFD can rebuild context
        }

    def outputs(self, r: dict) -> list:
        k = r["kpis"]
        # Headline KPIs + the single "Plant PUE" overhead summary. The separate
        # cassette-PUE / pump / fan / plant-aux echo rows are intentionally NOT
        # results — they just reflect inputs (the per-load fractions live in the
        # Design point block). Plant PUE rolls them all into one figure.
        rows = [
            OutputSpec("GT actual power",       k["GT actual power kW"],   "kW",     "verified", "{:.0f}"),
            OutputSpec("NG consumption",        k["NG consumption Nm3h"],  "Nm³/h",  "verified", "{:.0f}"),
            OutputSpec("Steam generation",      k["Steam generation t/h"], "t/h",    "verified", "{:.2f}"),
            OutputSpec("LiBr cooling capacity", k["LiBr cooling kW"],      "kW",     "verified", "{:.0f}"),
            OutputSpec("GPU IT load",           k["GPU IT load kW"],       "kW",     "verified", "{:.0f}"),
            OutputSpec("MED water production",  k["MED water m3day"],      "m³/day", "verified", "{:.0f}"),
            OutputSpec("Plant PUE (electrical, export excluded)",
                       k.get("Plant PUE (electrical, export excluded)", 0.0),
                       "-", "screening", "{:.3f}"),
        ]
        # Mode / control-derived KPIs — show only when relevant.
        solved = r.get("solved")
        cs = getattr(solved, "control", None) if solved is not None else None
        if cs is not None:
            if cs.derived_load_pct:
                rows.append(OutputSpec(
                    "GT load_pct (auto-derived)", cs.load_pct, "%",
                    "verified", "{:.1f}"))
            if cs.derived_libr_frac:
                rows.append(OutputSpec(
                    "libr_frac (auto-derived)", cs.libr_frac, "-",
                    "verified", "{:.3f}"))
        op_mode = getattr(solved, "operating_mode", "island") if solved is not None else "island"
        if op_mode == "grid_tied":
            rows.append(OutputSpec(
                "Grid export", k.get("Grid export kW", 0.0), "kW",
                "verified", "{:.0f}"))
        else:
            rows.append(OutputSpec(
                "External load (island)", k.get("External load kW", 0.0), "kW",
                "input", "{:.0f}"))
        return rows

    def highlights(self, r: dict) -> list:
        """Four highlight cards at the top of the results pane:
        GT actual power · Steam generation · GPU IT load · MED water production.
        Index 6 (Plant PUE) is a screening KPI and not promoted to a card."""
        outs = self.outputs(r)
        return [outs[0], outs[2], outs[4], outs[5]]

    def chart(self, r: dict, path: str) -> str:
        # On-screen chart = the same PFD topology as the report's landscape page
        # (no panels), so the two always match. Falls back to the generic
        # flowsheet if the PFD context can't be built.
        from nexa_toolkit.reporting.pfd_page import pfd_chart_svg
        svg = pfd_chart_svg(self, r.get("inputs", {}), r)
        if svg is None:
            svg = render_svg(r["solved"])
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
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
                             "LiBr cooling kW",    "MED water m3day",
                             "GPU IT load kW",     "Grid export kW"],
            "sensitivity_inputs": ["load_pct", "gt_eff", "libr_cop", "libr_reject_t_C",
                                   "hrsg_eff_pct", "med_effects", "med_bypass_frac",
                                   "t_ambient_C", "gpu_it_kW", "external_load_kW"],
            "sweep_inputs": ["load_pct", "gt_eff", "libr_cop", "libr_reject_t_C",
                             "hrsg_eff_pct", "med_bypass_frac", "t_ambient_C",
                             "gpu_it_kW", "external_load_kW"],
            "bounds": {
                "load_pct":         (10.0,   100.0),
                "gt_eff":           (0.15,    0.45),
                "libr_cop":         (0.5,     0.85),
                "libr_reject_t_C":  (60.0,    130.0),
                "hrsg_eff_pct":     (50.0,    95.0),
                "med_bypass_frac":  (0.0,     1.0),
                "t_ambient_C":      (-10.0,   55.0),
                "gpu_it_kW":        (100.0,   50_000.0),
                "external_load_kW": (0.0,     20_000.0),
            },
            "step_override": {"med_effects": 1.0},
            "scenarios": {
                "summer peak":     {"t_ambient_C": 40.0, "load_pct": 100.0},
                "winter low load": {"t_ambient_C":  5.0, "load_pct":  40.0},
            },
        }
