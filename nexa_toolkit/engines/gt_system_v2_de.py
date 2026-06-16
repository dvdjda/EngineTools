"""
GT System v2 (double-effect) — same nexablock composition as gt_system_v2 but
with a DOUBLE-EFFECT LiBr absorption chiller (2× generators, COP ~1.2) in place
of the single-effect chiller.

This is a copy of the trusted single-effect engine, rebuilt for the
double-effect chiller. It does NOT modify the trusted gt_system_v2 engine — it
reuses the shared composition (build_gt_system) through the behaviour-preserving
`chiller_effect="double"` flag, and reuses gt_system_v2._params_from read-only.

Status: draft — the double-effect chiller physics are screening and unverified
until David checks them (ChemCAD is the system of record).
"""
from __future__ import annotations

from nexa_toolkit.framework.contract import InputSpec, OutputSpec, register
from simulators.gt_system.system      import build_gt_system, summary
from simulators.gt_system.feasibility import feasibility
from simulators.gt_system.audit        import gt_system_audit_checks
from nexablock.audit                   import audit
from nexablock.blocks                  import DoubleEffectLiBrChiller

from .gt_system_v2 import GTSystemV2, _params_from


_MED_MODE = {0: "manual", 1: "auto"}


def _params_double(v: dict):
    """Single-effect param builder + the double-effect chiller flag + the MED
    bypass mode. Reuses the trusted _params_from read-only so the two engines
    never drift on the shared inputs."""
    p = _params_from(v)
    p.chiller_effect   = "double"
    p.med_bypass_mode  = _MED_MODE.get(int(v.get("med_bypass_mode", 1)), "auto")
    p.med_cold_pinch_K = float(v.get("med_cold_pinch_K", 15.0))
    return p


@register
class GTSystemV2DE(GTSystemV2):
    key        = "gt_system_v2_de"
    name       = "GT System v2 — nexablock (GT + HRSG + 2xLiBr + GPU + MED)"
    kind       = "simulator"
    status     = "trusted"   # promoted by David
    provenance = ("Copy of trusted gt_system_v2 rebuilt for a double-effect LiBr "
                  "absorption chiller (2× generators, COP ~1.2, needs ~8-10 bar "
                  "steam). David's request: model the double-effect chiller as a "
                  "separate engine without touching the single-effect one. "
                  "Promoted to trusted by David.")
    notes = (
        "Identical to GT System v2 except the LiBr chiller is DOUBLE-EFFECT "
        "(DoubleEffectLiBrChiller): COP ~1.2 vs ~0.7, so ~1.7× more cooling and "
        "more heat-rejection (hence more MED water) from the same HRSG steam — at "
        "the cost of needing higher-grade steam (the T11 audit check flags if the "
        "HTG steam is too cool). Adds the per-pump/fan electrical sizing rows and "
        "the auto MED-bypass cascade (holds the HRSG return at the feedwater set-"
        "point). Use for heat-quality-limited prime movers (e.g. recuperated "
        "microturbines) where single-effect cooling falls short."
    )
    chart_format = "svg"

    # Same inputs as the single-effect engine, but: the LiBr COP default/range is
    # the double-effect band, and a MED-bypass mode selector (Auto by default —
    # the cascade that holds the HRSG return at set-point) is inserted next to the
    # manual bypass fraction.
    inputs = []
    for _i in GTSystemV2.inputs:
        if _i.key == "libr_cop":
            inputs.append(InputSpec("libr_cop", "LiBr COP (double-effect)",
                                    "-", 1.20, 0.90, 1.60))
        else:
            inputs.append(_i)
        if _i.key == "med_bypass_frac":
            inputs.append(InputSpec(
                "med_bypass_mode", "MED bypass control", "-", 1, 0, 1,
                choices={"Manual (use fraction above)": 0,
                         "Auto (hold HRSG return set-point)": 1}))
            inputs.append(InputSpec(
                "med_cold_pinch_K", "MED cold-end approach above seawater (auto)",
                "K", 15.0, 5.0, 40.0))

    def solve(self, v: dict) -> dict:
        params = _params_double(v)
        solved = build_gt_system(params)
        return {
            "solved":      solved,
            "kpis":        summary(solved),
            "feasibility": feasibility(solved, bop_frac=params.bop_frac),
            "audit":       audit(solved,
                                  extra_checks=gt_system_audit_checks(
                                      solved, bop_frac=params.bop_frac)),
            "inputs":      dict(v),
        }

    def outputs(self, r: dict) -> list:
        # Standard KPI rows + two double-effect-specific rows read from the chiller.
        rows = super().outputs(r)
        solved = r.get("solved")
        chiller = None
        if solved is not None:
            chiller = next((b for b in solved.blocks
                            if isinstance(b, DoubleEffectLiBrChiller)), None)
        if chiller is not None and "COP achieved" in chiller.results:
            cop  = chiller.results["COP achieved"].value
            gain = chiller.results.get("Second-effect cooling gain")
            rows.append(OutputSpec("LiBr COP (double-effect)", cop, "-", "input", "{:.2f}"))
            if gain is not None:
                rows.append(OutputSpec("Second-effect cooling gain", gain.value,
                                       "kW", "verified", "{:.0f}"))
        # Per-pump / fan electrical sizing — each driver as its own kW row.
        if solved is not None and getattr(solved, "params", None) is not None:
            from simulators.gt_system.plant_loads import plant_loads
            pl = plant_loads(solved, solved.params)
            for name, kw in pl["items"].items():
                rows.append(OutputSpec(f"  ↳ {name}", kw, "kW", "screening", "{:.1f}"))
            rows.append(OutputSpec("  ↳ Plant aux TOTAL", pl["total"], "kW",
                                   "screening", "{:.1f}"))
        return rows

    def study_hooks(self) -> dict:
        h = dict(super().study_hooks())
        h["make_params"] = _params_double            # studies must use double-effect
        h["bounds"] = {**h["bounds"], "libr_cop": (0.90, 1.60)}
        return h
