"""
nexablock.studies.charts — matplotlib chart helpers for study results.

Three public helpers, each matching the engine.chart(result, path) -> path
contract so they drop straight into the existing v1 reporting pipeline
when chart_format == "png":

    tornado_chart(sensitivity_result,  path, kpi=...)
    sweep_chart(sweep_result,          path, kpis=...)
    scenarios_chart(scenario_result,   path, kpis=...)

Plus a placeholder sweep_contour() for the 2-D hook.

Styling mirrors nexa_toolkit/reporting/charts.py so charts blend with
existing reports without coupling the v2 studies layer back to the v1
framework.
"""
from __future__ import annotations
import math

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.figure import Figure


# ── palette (values mirror nexa_toolkit/reporting/charts.py) ───────────────
NAVY = "#2E4E7E"
TEAL = "#2BB6A3"
GREY = "#5b6675"
INK  = "#22303F"
LINE = "#dbe2ee"
RED  = "#C0392B"
GRID = "#e6ebf3"

_LINE_COLORS = [NAVY, TEAL, RED, GREY]


# ── public helpers ─────────────────────────────────────────────────────────

def tornado_chart(result, path: str, *,
                  kpi:   str,
                  top_n: int | None = None,
                  title: str | None = None) -> str:
    """Horizontal tornado bar chart of elasticity for one KPI. Returns path."""
    fig = _tornado_figure(result, kpi=kpi, top_n=top_n, title=title)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def sweep_chart(result, path: str, *,
                kpis:  list | None = None,
                x:     str | None  = None,
                title: str | None  = None) -> str:
    """Line chart of KPIs vs the swept input. 1-D only. Returns path."""
    fig = _sweep_figure(result, kpis=kpis, x=x, title=title)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def scenarios_chart(result, path: str, *,
                    kpis:  list | None = None,
                    title: str | None  = None) -> str:
    """Grouped bars: scenarios on X, KPIs as ratio vs base. Returns path."""
    fig = _scenarios_figure(result, kpis=kpis, title=title)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def sweep_contour(result, path: str, *,
                  kpi:   str,
                  x:     str | None = None,
                  y:     str | None = None,
                  title: str | None = None):
    """Reserved for 2-D contour over a two-input sweep grid."""
    raise NotImplementedError(
        "sweep_contour: 2-D contour coming in a later step. "
        "Use sweep_chart(...) for 1-D sweeps.")


# ── figure builders (tests inspect these before they're closed) ───────────

def _tornado_figure(result, *, kpi, top_n=None, title=None) -> Figure:
    entries = result.tornado(kpi)
    if top_n is not None:
        entries = entries[:top_n]
    if not entries:
        raise ValueError(f"No sensitivity entries for KPI {kpi!r}")

    labels = [e.input for e in entries]
    values = [e.elasticity if not _isnan(e.elasticity) else 0.0 for e in entries]
    colors = [TEAL if v >= 0 else RED for v in values]

    fig, ax = plt.subplots(figsize=(8.5, 0.45 * len(entries) + 1.5))
    positions = list(range(len(entries)))
    ax.barh(positions, values, color=colors, edgecolor=INK, linewidth=0.5)
    ax.set_yticks(positions)
    ax.set_yticklabels(labels, color=INK)
    ax.invert_yaxis()                                    # largest |ε| at top
    ax.axvline(0, color=GREY, linewidth=0.8)
    ax.set_xlabel("Elasticity  (% ΔKPI / % ΔInput)", color=INK)
    ax.set_title(title or f"Sensitivity tornado — {kpi}",
                 color=INK, fontsize=12)
    ax.xaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    for i, v in enumerate(values):
        ax.text(v, i, f"  {v:+.3f}", va="center",
                ha="left" if v >= 0 else "right",
                fontsize=9, color=INK)
    return fig


def _sweep_figure(result, *, kpis=None, x=None, title=None) -> Figure:
    if len(result.varied) > 1:
        raise ValueError(
            f"sweep_chart is 1-D only (got {len(result.varied)} varied inputs: "
            f"{result.varied}). Use sweep_contour(...) for 2-D (placeholder).")
    x_name = x or result.varied[0]
    xs = [p.inputs[x_name] for p in result.points]
    if kpis is None:
        kpis = list(result.points[0].kpis.keys()) if result.points else []

    fig, ax = plt.subplots(figsize=(9.0, 4.0))
    for i, k in enumerate(kpis):
        ys = [p.kpis.get(k, math.nan) for p in result.points]
        ax.plot(xs, ys, marker="o", linewidth=1.6,
                color=_LINE_COLORS[i % len(_LINE_COLORS)], label=k)
    ax.set_xlabel(x_name, color=INK)
    ax.set_title(title or f"Sweep over {x_name}", color=INK, fontsize=12)
    ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="best", frameon=False, fontsize=9)
    return fig


def _scenarios_figure(result, *, kpis=None, title=None) -> Figure:
    if kpis is None:
        kpis = list(result.base_kpis.keys())
    if not result.points:
        raise ValueError("scenarios_chart: no scenario points to plot")

    scen_names = [p.name for p in result.points]
    n_scen = len(scen_names)
    n_kpi  = len(kpis)
    bar_w  = 0.8 / max(n_kpi, 1)

    fig, ax = plt.subplots(figsize=(max(7.5, 1.2 * n_scen + 2), 4.2))
    centers = list(range(n_scen))
    for i, k in enumerate(kpis):
        base = result.base_kpis.get(k)
        ratios = []
        for p in result.points:
            v = p.kpis.get(k)
            if base in (0, None) or v is None:
                ratios.append(math.nan)
            else:
                ratios.append(v / base)
        offsets = [c + bar_w * (i - (n_kpi - 1) / 2.0) for c in centers]
        ax.bar(offsets, ratios, width=bar_w * 0.95,
               color=_LINE_COLORS[i % len(_LINE_COLORS)],
               edgecolor=INK, linewidth=0.5, label=k)
    ax.axhline(1.0, linestyle="--", color=GREY, linewidth=0.8)
    ax.set_xticks(centers)
    ax.set_xticklabels(scen_names, color=INK)
    ax.set_ylabel("Ratio vs base", color=INK)
    ax.set_title(title or "Scenario comparison (ratio vs base)",
                 color=INK, fontsize=12)
    ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend(loc="best", frameon=False, fontsize=9)
    return fig


def _isnan(v) -> bool:
    return isinstance(v, float) and v != v
