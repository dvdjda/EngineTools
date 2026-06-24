"""LiBr-H2O absorption chiller (single + double effect), on the engine contract.

Calibrated to the BROAD XII Non-Electric Chiller datasheet (1711), treated as the
verified design of record. A 'Cycle' switch selects single- or double-effect; at
the OEM rated condition each mode reproduces the nameplate COP and solution
concentration. An optional make-up gas burner tops up any generator-heat shortfall
and reports the natural-gas consumption for the requested cooling duty. Stays draft
until David verifies and promotes.
"""
from ..framework.contract import Engine, InputSpec, OutputSpec, register
from ..engine.libr_chiller import DesignPoint, solve as _solve
from ..reporting.charts import make_chart
from ..reporting.libr_pfd import libr_pfd_svg


_EFFECT = {0: "single", 1: "double"}


def _make_dp(v: dict) -> DesignPoint:
    """Build a DesignPoint from a UI input dict. Shared by solve() and the studies
    layer (study_hooks.make_params). Waste-heat input of 0 means 'uncapped'."""
    effect = _EFFECT.get(int(v.get("effect", 0)), "single")
    burner_on = bool(int(v.get("burner_on", 0)))
    avail = float(v.get("q_source_avail_kw", 0) or 0.0)
    avail = float("inf") if avail <= 0 else avail
    return DesignPoint(
        t_chw_out_c=v["t_chw_out_c"], t_cw_in_c=v["t_cw_in_c"],
        t_hot_c=v["t_hot_c"], q_evap_kw=v["q_evap_kw"],
        effect=effect, burner_on=burner_on, q_source_avail_kw=avail)


def _kpis(r: dict) -> dict:
    """KPI extractor for the studies layer (sensitivity / sweep)."""
    return {
        "COP": r["cop"],
        "Cooling capacity kW": r["q_evap_kw"],
        "Generator duty kW": r["q_gen_kw"],
        "Condenser duty kW": r["q_cond_kw"],
        "Absorber duty kW": r["q_abs_kw"],
        "Backup burner fuel Nm3/h": r["fuel_nm3h"],
        "Backup burner heat kW": r["burner_heat_kw"],
        "Cooling deficit kW": r["cooling_deficit_kw"],
        "Strong solution %": r["x_strong_pct"],
        "Crystallisation margin %": r["cryst_margin_pct"],
    }


@register
class LiBrChiller(Engine):
    key = "libr_chiller"
    name = "LiBr-H2O absorption chiller"
    status = "draft"
    provenance = ("David's request: rename to 'LiBr-H2O absorption chiller', model both "
                  "single- and double-effect cycles with a switch, add an optional make-up "
                  "gas burner (fuel-for-cooling), a GT-style process diagram and study "
                  "metrics — all calibrated to the BROAD XII Non-Electric Chiller datasheet "
                  "(1711) as the verified design of record (double-effect = direct-fired "
                  "COP 1.42 / 54%).")
    notes = ("Single- and double-effect LiBr-H2O absorption cycle, calibrated to the BROAD "
             "XII datasheet at the rated condition (chilled 7/14 degC, cooling 30/37 degC): "
             "single-effect COP 0.76 / ~43% LiBr (hot-water drive), double-effect COP 1.42 "
             "/ ~54% LiBr (direct-fired). Optional make-up gas burner covers any "
             "generator-heat shortfall and reports NG (Nm3/h) on the OEM 10 kWh/Nm3 basis "
             "(reproduces the DFA gas table for double-effect; screening for single-effect). "
             "OEM-anchored COP and nominal concentration are verified-basis; off-design COP, "
             "duties, weak/strong split, burner fuel and crystallisation are screening-grade. "
             "Water/steam properties from CoolProp (IAPWS). ChemCAD remains the system of "
             "record for certifiable numbers.")
    chart_format = "svg"   # primary chart is the SVG process flow diagram
    inputs = [
        InputSpec("effect", "Cycle", "-", 0, 0, 1,
                  choices={"Single effect": 0, "Double effect": 1}),
        InputSpec("t_chw_out_c", "Chilled-water supply", "degC", 7, 0, 20),
        InputSpec("t_cw_in_c", "Cooling-water inlet", "degC", 30, 15, 40),
        InputSpec("t_hot_c", "Heat source (≥150 °C for double-effect)", "degC", 150, 70, 180),
        InputSpec("q_evap_kw", "Cooling duty", "kW", 233, 1, 1_000_000),
        InputSpec("burner_on", "Backup burner", "-", 0, 0, 1,
                  choices={"Off": 0, "On": 1}),
        InputSpec("q_source_avail_kw", "Waste heat to generator (0 = uncapped)",
                  "kW", 0, 0, 1_000_000),
    ]

    def solve(self, v):
        return _solve(_make_dp(v))

    def outputs(self, r):
        # OEM-anchored nameplate values (COP, nominal concentration) are verified
        # basis; the derived band / duties / fuel / crystallisation are screening.
        rows = [
            OutputSpec("Cycle", r["effect_label"], "", "input", "{}"),
            OutputSpec("COP", r["cop"], "-", "verified", "{:.3f}"),
            OutputSpec("Nominal solution (OEM)", r["x_nominal_pct"], "% LiBr", "verified", "{:.1f}"),
            OutputSpec("Weak (dilute) solution", r["x_weak_pct"], "% LiBr", "screening", "{:.1f}"),
            OutputSpec("Strong (conc.) solution", r["x_strong_pct"], "% LiBr", "screening", "{:.1f}"),
            OutputSpec("Concentration swing", r["x_strong_pct"] - r["x_weak_pct"], "%", "screening", "{:.1f}"),
            OutputSpec("Circulation ratio", r["circulation_ratio"], "-", "screening", "{:.2f}"),
            OutputSpec("Cooling capacity", r["q_evap_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Condenser duty", r["q_cond_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Generator duty", r["q_gen_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Absorber duty", r["q_abs_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Crystallisation margin", r["cryst_margin_pct"], "%", "screening", "{:+.1f}"),
        ]
        # Backup-burner rows — only when the source is capped or the burner is on.
        if r.get("burner_on") or r.get("source_capped"):
            if r.get("source_capped"):
                rows.append(OutputSpec("Waste heat to generator", r["q_source_avail_kw"],
                                       "kW", "input", "{:.0f}"))
            rows.append(OutputSpec("Backup burner heat", r["burner_heat_kw"], "kW", "screening", "{:.0f}"))
            rows.append(OutputSpec("Backup burner fuel (NG)", r["fuel_nm3h"], "Nm³/h", "screening", "{:.1f}"))
            if r.get("cooling_deficit_kw", 0.0) > 0.1:
                rows.append(OutputSpec("Cooling deficit (no burner)", r["cooling_deficit_kw"],
                                       "kW", "screening", "{:.0f}"))
        return rows

    def highlights(self, r):
        rows = [
            OutputSpec("Cycle", r["effect_label"], "", "input", "{}"),
            OutputSpec("COP", r["cop"], "-", "verified", "{:.3f}"),
            OutputSpec("Generator duty", r["q_gen_kw"], "kW", "screening", "{:.0f}"),
        ]
        if r.get("burner_on") and r.get("fuel_nm3h", 0.0) > 0.0:
            rows.append(OutputSpec("Backup burner fuel (NG)", r["fuel_nm3h"], "Nm³/h", "screening", "{:.1f}"))
        else:
            rows.append(OutputSpec("Crystallisation margin", r["cryst_margin_pct"], "%", "screening", "{:+.1f}"))
        return rows

    def chart(self, r, path):
        # Primary chart = GT-style SVG process flow diagram with live tags + metrics
        # and the optional backup burner. The duties / crystallisation panel is drawn
        # natively in a footer band of the same SVG, so both views appear together.
        svg = libr_pfd_svg(self, r)
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg)
        return path

    def chart_secondary(self, r, path):
        # The original two-panel duties + crystallisation chart, kept available for
        # reports/tools that want the raster view alongside the flowsheet.
        return make_chart(r, path)

    def study_hooks(self):
        """Plumbing for the studies layer (sensitivity / sweep / scenarios)."""
        return {
            "builder":      _solve,
            "make_params":  _make_dp,
            "kpi_fn":       _kpis,
            "kpis": ["COP", "Cooling capacity kW", "Generator duty kW",
                     "Backup burner fuel Nm3/h", "Crystallisation margin %"],
            "sensitivity_inputs": ["t_hot_c", "q_evap_kw", "t_cw_in_c", "t_chw_out_c"],
            "sweep_inputs": ["t_hot_c", "q_evap_kw", "t_cw_in_c", "t_chw_out_c",
                             "q_source_avail_kw"],
            "bounds": {
                "t_hot_c":           (70.0, 180.0),
                "q_evap_kw":         (1.0, 1_000_000.0),
                "t_cw_in_c":         (15.0, 40.0),
                "t_chw_out_c":       (0.0, 20.0),
                "q_source_avail_kw": (0.0, 1_000_000.0),
            },
            "scenarios": {
                "hot source 90 °C":   {"t_hot_c": 90.0},
                "hot source 120 °C":  {"t_hot_c": 120.0},
                "high cooling duty":  {"q_evap_kw": 500.0},
            },
        }
