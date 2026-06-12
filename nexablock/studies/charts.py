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
                  kpi:       str,
                  top_n:     int | None = None,
                  title:     str | None = None,
                  drop_zero: bool       = False) -> str:
    """Horizontal tornado bar chart of elasticity for one KPI. Returns path.

    drop_zero=True hides inputs whose elasticity is effectively zero — useful
    when the picked KPI is structurally decoupled from most inputs and the
    zero-length bars make the chart read as broken."""
    fig = _tornado_figure(result, kpi=kpi, top_n=top_n, title=title,
                           drop_zero=drop_zero)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def sweep_chart(result, path: str, *,
                kpis:     list | None = None,
                x:        str | None  = None,
                title:    str | None  = None,
                subplots: bool        = False) -> str:
    """Line chart of KPIs vs the swept input. 1-D only.

    subplots=False (default): all KPIs on one axes. Best when they share a
                              scale; otherwise the smaller-scale KPIs read
                              as pinned to zero against the larger ones.
    subplots=True:            one stacked subplot per KPI, each on its own
                              y-axis. Use this when KPIs span very different
                              magnitudes (kW vs t/h vs m³/day)."""
    fig = _sweep_figure(result, kpis=kpis, x=x, title=title, subplots=subplots)
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
                  title: str | None = None) -> str:
    """2-D contour plot over a two-input sweep grid. Returns path.

    The SweepResult must have exactly 2 varied inputs. KPI is contoured
    via matplotlib.contourf with a colorbar."""
    fig = _contour_figure(result, kpi=kpi, x=x, y=y, title=title)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


def tornado_multi_chart(result, path: str, *,
                        kpis:  list,
                        title: str | None = None,
                        drop_zero: bool = True) -> str:
    """Multi-panel tornado — one tornado per requested KPI stacked vertically."""
    fig = _tornado_multi_figure(result, kpis=kpis, title=title, drop_zero=drop_zero)
    fig.savefig(path, dpi=150, facecolor="white", bbox_inches="tight")
    plt.close(fig)
    return path


# ── figure builders (tests inspect these before they're closed) ───────────

def _tornado_figure(result, *, kpi, top_n=None, title=None,
                     drop_zero: bool = False) -> Figure:
    entries = result.tornado(kpi)
    if drop_zero:
        entries = [e for e in entries if abs(e.elasticity) > 1e-6]
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


def _sweep_figure(result, *, kpis=None, x=None, title=None,
                   subplots: bool = False) -> Figure:
    if len(result.varied) > 1:
        raise ValueError(
            f"sweep_chart is 1-D only (got {len(result.varied)} varied inputs: "
            f"{result.varied}). Use sweep_contour(...) for 2-D (placeholder).")
    x_name = x or result.varied[0]
    xs = [p.inputs[x_name] for p in result.points]
    if kpis is None:
        kpis = list(result.points[0].kpis.keys()) if result.points else []

    if subplots and len(kpis) > 1:
        # One row per KPI — independent y-axes so small-scale KPIs aren't
        # crushed by the largest-scale one.
        fig, axes = plt.subplots(len(kpis), 1, sharex=True,
                                  figsize=(9.0, 1.6 * len(kpis) + 1.0))
        if len(kpis) == 1:
            axes = [axes]
        for i, (ax, k) in enumerate(zip(axes, kpis)):
            ys = [p.kpis.get(k, math.nan) for p in result.points]
            ax.plot(xs, ys, marker="o", linewidth=1.6,
                    color=_LINE_COLORS[i % len(_LINE_COLORS)])
            ax.set_ylabel(k, color=INK, fontsize=9)
            ax.yaxis.grid(True, color=GRID); ax.set_axisbelow(True)
            ax.spines[["top", "right"]].set_visible(False)
        axes[-1].set_xlabel(x_name, color=INK)
        fig.suptitle(title or f"Sweep over {x_name}", color=INK, fontsize=12)
        fig.tight_layout()
        return fig

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


def _contour_figure(result, *, kpi, x=None, y=None, title=None) -> Figure:
    """2D contour over a SweepResult with exactly 2 varied inputs."""
    if len(result.varied) != 2:
        raise ValueError(
            f"sweep_contour requires exactly 2 varied inputs; "
            f"got {result.varied}. Use sweep_chart for 1D.")
    x_name = x or result.varied[0]
    y_name = y or result.varied[1]
    # Collect unique sorted axis values.
    xs_unique = sorted({p.inputs[x_name] for p in result.points})
    ys_unique = sorted({p.inputs[y_name] for p in result.points})
    Z = [[math.nan] * len(xs_unique) for _ in ys_unique]
    for p in result.points:
        i = xs_unique.index(p.inputs[x_name])
        j = ys_unique.index(p.inputs[y_name])
        Z[j][i] = p.kpis.get(kpi, math.nan)

    fig, ax = plt.subplots(figsize=(8.5, 5.5))
    import numpy as _np
    Xg, Yg = _np.meshgrid(xs_unique, ys_unique)
    Zg = _np.array(Z)
    cs = ax.contourf(Xg, Yg, Zg, levels=10, cmap="viridis")
    cl = ax.contour(Xg, Yg, Zg, levels=10, colors="white",
                     linewidths=0.5, alpha=0.4)
    ax.clabel(cl, inline=True, fontsize=7, fmt="%.0f")
    cb = fig.colorbar(cs, ax=ax, label=kpi)
    cb.ax.tick_params(labelsize=8)
    ax.set_xlabel(x_name, color=INK)
    ax.set_ylabel(y_name, color=INK)
    ax.set_title(title or f"{kpi}  contour over  ({x_name}, {y_name})",
                  color=INK, fontsize=12)
    return fig


def _tornado_multi_figure(result, *, kpis: list, title=None,
                           drop_zero: bool = True) -> Figure:
    """Stacked tornado panels, one per KPI in kpis."""
    if not kpis:
        raise ValueError("tornado_multi_chart needs at least one KPI")
    fig, axes = plt.subplots(len(kpis), 1,
                              figsize=(9.0, 2.0 * len(kpis) + 1.0))
    if len(kpis) == 1:
        axes = [axes]
    for ax, kpi in zip(axes, kpis):
        entries = result.tornado(kpi)
        if drop_zero:
            entries = [e for e in entries if abs(e.elasticity) > 1e-6]
        if not entries:
            ax.text(0.5, 0.5, f"(no non-zero sensitivities for {kpi})",
                     ha="center", va="center", transform=ax.transAxes,
                     color=GREY, fontsize=10)
            ax.set_axis_off()
            continue
        labels = [e.input for e in entries]
        values = [e.elasticity if not _isnan(e.elasticity) else 0.0
                   for e in entries]
        colors = [TEAL if v >= 0 else RED for v in values]
        positions = list(range(len(entries)))
        ax.barh(positions, values, color=colors, edgecolor=INK, linewidth=0.4)
        ax.set_yticks(positions)
        ax.set_yticklabels(labels, color=INK, fontsize=9)
        ax.invert_yaxis()
        ax.axvline(0, color=GREY, linewidth=0.6)
        ax.set_title(kpi, color=INK, fontsize=10, loc="left")
        ax.xaxis.grid(True, color=GRID); ax.set_axisbelow(True)
        ax.spines[["top", "right"]].set_visible(False)
        for i, v in enumerate(values):
            ax.text(v, i, f"  {v:+.3f}", va="center",
                     ha="left" if v >= 0 else "right",
                     fontsize=8, color=INK)
    axes[-1].set_xlabel("Elasticity  (% ΔKPI / % ΔInput)", color=INK)
    if title:
        fig.suptitle(title, color=INK, fontsize=12)
    fig.tight_layout()
    return fig


def _isnan(v) -> bool:
    return isinstance(v, float) and v != v
