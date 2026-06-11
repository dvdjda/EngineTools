"""
GT System v2 — load-sweep screening adapter.

Inherits inputs / outputs / highlights from GTSystemV2 but replaces the
chart slot with a GT-load sweep line chart (one line per top-level KPI).
Solve runs both the base point and a sweep over load_pct.

Status: draft. Same physics as gt_system_v2; this entry just shows a
different visualisation in the chart slot for screening reports.
"""
from __future__ import annotations

from nexa_toolkit.framework.contract import register
from simulators.gt_system.system    import build_gt_system, summary
from nexablock.studies              import ParameterSweep, sweep_chart

from .gt_system_v2 import GTSystemV2, _params_from

_SWEEP_KPIS = [
    "GT actual power kW",
    "Steam generation t/h",
    "LiBr cooling kW",
    "MED water m3day",
]


@register
class GTSystemV2LoadSweep(GTSystemV2):
    key          = "gt_system_v2_loadsweep"
    name         = "GT System v2 — load sweep screening"
    status       = "trusted"
    chart_format = "png"   # override parent's "svg" — sweep chart is matplotlib PNG
    notes = (
        "Same physics as gt_system_v2 (validated vs the v1 trusted GT tool "
        "within ±2%, 14/14 checks; tests/test_gt_system.py). Chart slot "
        "shows a load-screening sweep (load_pct 50–100% in 5% steps) across "
        "GT power, steam, LiBr cooling and MED water."
    )

    def solve(self, v: dict) -> dict:
        base   = super().solve(v)
        params = _params_from(v)
        sweep  = ParameterSweep(build_gt_system, params, summary).run(
            {"load_pct": list(range(50, 101, 5))})
        return {**base, "sweep": sweep}

    def chart(self, r: dict, path: str) -> str:
        return sweep_chart(
            r["sweep"], path,
            kpis  = _SWEEP_KPIS,
            title = "GT-load sweep (50–100%)",
        )
