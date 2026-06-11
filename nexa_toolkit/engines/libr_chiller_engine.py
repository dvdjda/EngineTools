"""System 1: single-effect LiBr-H2O absorption chiller, on the engine contract."""
from ..framework.contract import Engine, InputSpec, OutputSpec, register
from ..engine.libr_chiller import DesignPoint, solve as _solve
from ..reporting.charts import make_chart


@register
class LiBrChiller(Engine):
    key = "libr_chiller"
    name = "Single-effect LiBr-H2O absorption chiller"
    notes = ("Water/steam properties from CoolProp (IAPWS); LiBr-H2O equilibrium from "
             "the ASHRAE / Herold-Klein Duhring relation; solution enthalpy from the "
             "ASHRAE polynomial. Concentration and crystallisation figures are solid "
             "screening numbers; absolute duties are screening-grade. ChemCAD is the "
             "system of record for certifiable numbers.")
    inputs = [
        InputSpec("t_chw_out_c", "Chilled-water supply", "degC", 10, 0, 20),
        InputSpec("t_cw_in_c", "Cooling-water inlet", "degC", 30, 15, 40),
        InputSpec("t_hot_c", "Heat source", "degC", 90, 70, 140),
        InputSpec("q_evap_kw", "Cooling duty", "kW", 500, 1, 1_000_000),
    ]

    def solve(self, v):
        dp = DesignPoint(t_chw_out_c=v["t_chw_out_c"], t_cw_in_c=v["t_cw_in_c"],
                         t_hot_c=v["t_hot_c"], q_evap_kw=v["q_evap_kw"])
        return _solve(dp)

    def outputs(self, r):
        return [
            OutputSpec("Weak (dilute) solution", r["x_weak_pct"], "% LiBr", "screening", "{:.1f}"),
            OutputSpec("Strong (conc.) solution", r["x_strong_pct"], "% LiBr", "screening", "{:.1f}"),
            OutputSpec("Concentration swing", r["x_strong_pct"] - r["x_weak_pct"], "%", "screening", "{:.1f}"),
            OutputSpec("Circulation ratio", r["circulation_ratio"], "-", "screening", "{:.2f}"),
            OutputSpec("Evaporator duty", r["q_evap_kw"], "kW", "input", "{:.0f}"),
            OutputSpec("Condenser duty", r["q_cond_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Generator duty", r["q_gen_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Absorber duty", r["q_abs_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("COP", r["cop"], "-", "screening", "{:.3f}"),
            OutputSpec("Crystallisation margin", r["cryst_margin_pct"], "%", "screening", "{:+.1f}"),
        ]

    def highlights(self, r):
        return [
            OutputSpec("COP", r["cop"], "-", "screening", "{:.3f}"),
            OutputSpec("Generator duty", r["q_gen_kw"], "kW", "screening", "{:.0f}"),
            OutputSpec("Crystallisation margin", r["cryst_margin_pct"], "%", "screening", "{:+.1f}"),
        ]

    def chart(self, r, path):
        return make_chart(r, path)
