"""Chart generation and shared result formatting for Nexa toolkit reports."""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib import font_manager

NAVY = "#2E4E7E"
TEAL = "#2BB6A3"
AMBER = "#E0A93B"
RED = "#C0392B"
GRID = "#E4E8EF"
INK = "#22303F"

plt.rcParams.update({
    "font.family": "DejaVu Sans",
    "axes.edgecolor": "#C9D2E0",
    "axes.linewidth": 0.8,
    "axes.titlesize": 11,
    "axes.titleweight": "bold",
    "axes.titlecolor": NAVY,
    "text.color": INK,
    "axes.labelcolor": INK,
    "xtick.color": INK,
    "ytick.color": INK,
})


def design_rows(dp):
    return [
        ("Chilled-water supply", f"{dp.t_chw_out_c:.1f}", "degC"),
        ("Cooling-water inlet", f"{dp.t_cw_in_c:.1f}", "degC"),
        ("Heat source", f"{dp.t_hot_c:.1f}", "degC"),
        ("Cooling duty", f"{dp.q_evap_kw:.0f}", "kW"),
    ]


def result_rows(r):
    return [
        ("Weak (dilute) solution", f"{r['x_weak_pct']:.1f}", "% LiBr"),
        ("Strong (conc.) solution", f"{r['x_strong_pct']:.1f}", "% LiBr"),
        ("Concentration swing", f"{r['x_strong_pct']-r['x_weak_pct']:.1f}", "%"),
        ("Circulation ratio", f"{r['circulation_ratio']:.2f}", "-"),
        ("COP", f"{r['cop']:.3f}", "-"),
        ("Crystallisation margin", f"{r['cryst_margin_pct']:+.1f}", "%"),
    ]


def duty_rows(r):
    return [
        ("Evaporator", r["q_evap_kw"]),
        ("Condenser", r["q_cond_kw"]),
        ("Generator", r["q_gen_kw"]),
        ("Absorber", r["q_abs_kw"]),
    ]


def make_chart(r, path, dpi=150):
    """Two-panel figure: component duties + crystallisation margin."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(9.2, 3.5),
                                   gridspec_kw={"width_ratios": [1.55, 1]})
    fig.subplots_adjust(left=0.09, right=0.97, top=0.84, bottom=0.16, wspace=0.32)

    # panel 1 - duties
    labels = [d[0] for d in duty_rows(r)]
    vals = [d[1] for d in duty_rows(r)]
    colors = [TEAL, NAVY, AMBER, NAVY]
    bars = ax1.bar(labels, vals, color=colors, width=0.62, zorder=3)
    ax1.set_title("Component duties (kW)")
    ax1.yaxis.grid(True, color=GRID, zorder=0)
    ax1.set_axisbelow(True)
    ax1.spines[["top", "right"]].set_visible(False)
    for b, v in zip(bars, vals):
        ax1.text(b.get_x() + b.get_width() / 2, v + max(vals) * 0.02,
                 f"{v:.0f}", ha="center", va="bottom", fontsize=9, color=INK)
    ax1.set_ylim(0, max(vals) * 1.16)

    # panel 2 - crystallisation margin
    x_strong = r["x_strong_pct"]
    x_line = r["x_crystallisation_pct"]
    safe = r["cryst_margin_pct"] > 0
    # xlo follows the data so single-effect bands (<50% LiBr) aren't clipped.
    xlo, xhi = min(50, x_strong - 6), max(x_line, x_strong) + 4
    ax2.barh([0], [x_strong], color=NAVY, height=0.5, zorder=3)
    ax2.axvline(x_line, color=RED, lw=2, zorder=4)
    ax2.text(x_line, 0.55, f"crystallisation line  {x_line:.1f}%",
             color=RED, fontsize=8.5, ha="right", va="bottom")
    ax2.text(x_strong - 0.6, 0, f"operating  {x_strong:.1f}%", color="white",
             fontsize=9, ha="right", va="center", fontweight="bold")
    ax2.set_title("Crystallisation margin")
    ax2.set_xlim(xlo, xhi)
    ax2.set_ylim(-0.9, 0.9)
    ax2.set_yticks([])
    ax2.spines[["top", "right", "left"]].set_visible(False)
    ax2.xaxis.grid(True, color=GRID, zorder=0)
    ax2.set_axisbelow(True)
    ax2.set_xlabel("% LiBr", fontsize=8.5, color=INK)
    tag = f"margin {r['cryst_margin_pct']:+.1f}%  ({'safe' if safe else 'at risk'})"
    ax2.text((xlo + xhi) / 2, -0.62, tag, ha="center", fontsize=9.5,
             color=(TEAL if safe else RED), fontweight="bold")

    fig.savefig(path, dpi=dpi, facecolor="white")
    plt.close(fig)
    return path
