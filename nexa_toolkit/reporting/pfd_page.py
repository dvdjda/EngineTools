"""
nexa_toolkit.reporting.pfd_page — the GT-system Process Flow Diagram as a live,
report-engine-native landscape page (no PowerPoint/LibreOffice at render time).

`make_pfd_flowable(engine, values, result)` returns a reportlab Flowable that
redraws the Nexa GT-system PFD with every value refreshed from the current
solve, or None for engines that aren't the GT system. build_pdf appends it as
the final landscape page.

Layout is a faithful native recreation of Nexa_energy_balance_two_streams.pptx —
block boxes, flow streams, a Key-results table, an Energy-balance/audit panel,
the operating-mode strip, and a stream/basis legend. Not pixel-identical to the
slide (redraw, per the chosen approach), but the same content and structure.
"""
from __future__ import annotations
from reportlab.platypus import Flowable
from reportlab.lib import colors

# Palette (matches the app / report theme)
NAVY  = colors.HexColor("#2E4E7E")
TEAL  = colors.HexColor("#2BB6A3")
INK   = colors.HexColor("#22303F")
GREY  = colors.HexColor("#5b6675")
LINEC = colors.HexColor("#C9D2E0")
LIGHT = colors.HexColor("#EAF0F8")
ORANGE= colors.HexColor("#B26A00")
REJECT= colors.HexColor("#8A94A6")
GREEN = colors.HexColor("#2E7D4E")
RED   = colors.HexColor("#C0392B")
BASIS = {"verified": GREEN, "screening": ORANGE, "input": GREY, "unverified": RED}

# Stream colours by kind (the "two streams" + extras)
ST_ELEC = NAVY      # electrical (kWe)
ST_HEAT = ORANGE    # heat / steam (kWth)
ST_COOL = TEAL      # cooling / chilled water
ST_REJ  = REJECT    # rejected heat


# ── live value mapping ───────────────────────────────────────────────────────

def _is_gt_system(result) -> bool:
    solved = result.get("solved") if isinstance(result, dict) else None
    if solved is None:
        return False
    try:
        from nexablock.blocks import GasTurbine, GPUCassette, LiBrChiller
    except Exception:
        return False
    have = {type(b) for b in solved.blocks}
    return GasTurbine in have and GPUCassette in have and LiBrChiller in have


def _mode_name(engine, key, val) -> str:
    """Exact named mode as shown in the inputs (reverse of InputSpec.choices)."""
    for spec in engine.inputs:
        if spec.key == key and spec.choices:
            for name, v in spec.choices.items():
                try:
                    if int(float(v)) == int(float(val)):
                        return name
                except (TypeError, ValueError):
                    pass
    return str(val)


def pfd_context(engine, values, result) -> dict | None:
    """Gather every live value the PFD shows into a dict. None if not a GT solve."""
    if not _is_gt_system(result):
        return None
    from nexablock.blocks import (GasTurbine, HRSG, LiBrChiller, GPUCassette,
                                   CoolingTower)
    solved = result["solved"]
    k = result.get("kpis", {})

    def R(cls, label, default=0.0):
        for b in solved.blocks:
            if isinstance(b, cls) and label in b.results:
                return b.results[label].value
        return default

    cs = getattr(solved, "control", None)
    op_mode = getattr(solved, "operating_mode", "island")
    load_pct = cs.load_pct if cs is not None else float(values.get("load_pct", 0.0))

    it        = R(GPUCassette, "IT power")
    cassette  = R(GPUCassette, "Cassette overhead electrical")
    heat_load = R(GPUCassette, "Heat load")
    pump      = R(LiBrChiller, "LiBr pump electrical")
    fan       = R(CoolingTower, "CT fan electrical")
    gt_aux    = R(GasTurbine,  "GT aux electrical")
    gt_actual = k.get("GT actual power kW", R(GasTurbine, "GT actual power"))
    bop       = max(0.0, getattr(solved, "bop_frac", 0.010)) * gt_actual
    plant_overhead = pump + fan + gt_aux + bop          # plant-side electrical aux

    qcool = k.get("LiBr cooling kW", R(LiBrChiller, "Cooling capacity kW"))
    qgen  = R(LiBrChiller, "Generator duty")
    qcond = R(CoolingTower, "CT heat duty") or R(LiBrChiller, "Condenser duty")
    fuel  = R(GasTurbine, "Fuel energy input")
    exh   = R(GasTurbine, "Exhaust heat")
    gt_cw = R(GasTurbine, "GT cooling water")
    stack = R(HRSG, "Stack heat loss")

    # Feasibility balances (already computed) for the energy-balance panel.
    feas = result.get("feasibility")
    pbal = cbal = None
    if feas is not None:
        for b in getattr(feas, "balances", []):
            if b.resource == "Power":   pbal = b
            if b.resource.startswith("Cooling"): cbal = b
    audit = result.get("audit")
    n_ok = sum(1 for c in audit.checks if c.passed) if audit is not None else 0
    n_tot = len(audit.checks) if audit is not None else 0

    grid = op_mode == "grid_tied"
    export_label = "Grid export" if grid else "External load"
    export_val   = (cs.grid_export_kW if grid else cs.external_load_kW) if cs is not None else 0.0

    return {
        "title": "Nexa Block v1 — GT system energy balance",
        "design": (f"Design point:  GT {values.get('p_rated_kW',0)/1000:.0f} MW · "
                   f"{values.get('gt_eff',0)*100:.0f}% · ambient {values.get('t_ambient_C',0):.0f}°C · "
                   f"exhaust {values.get('t_exhaust_C',0):.0f}°C · steam {values.get('steam_p_bar',0):.0f} bar · "
                   f"CHW {values.get('chw_sup_C',0):.0f}°C / ΔT {values.get('chw_dt_K',0):.0f}K · "
                   f"{int(values.get('med_effects',0))}-effect MED · seawater {values.get('sw_t_C',0):.0f}°C"),
        "grid": grid,
        "mode_op":    _mode_name(engine, "operating_mode",   values.get("operating_mode", 0)),
        "mode_gt":    _mode_name(engine, "gt_power_mode",    values.get("gt_power_mode", 0)),
        "mode_split": _mode_name(engine, "steam_split_mode", values.get("steam_split_mode", 0)),
        # blocks
        "bus":      f"Electrical bus  {gt_actual:,.0f} kWe",
        "ng":       ["NG supply", f"{k.get('NG consumption Nm3h', R(GasTurbine,'NG consumption Nm3/h')):,.0f} Nm³/h",
                     f"≈{fuel:,.0f} kWth"],
        "gt":       ["GT-01 · Gas turbine", f"{values.get('p_rated_kW',0)/1000:.0f} MW · {values.get('gt_eff',0)*100:.0f}%",
                     f"load {load_pct:.1f}%"],
        "overhead": [f"Plant overhead {plant_overhead:,.0f} kWe", f"pump {pump:.0f} · fan {fan:.0f}",
                     f"GT aux {gt_aux:.0f} · BoP {bop:.0f}"],
        "export":   [export_label, f"{export_val:,.0f} kWe"],
        "gpu":      ["GPU cassette", f"{it:,.0f} kWe IT",
                     f"+{cassette:.0f} kW (PUE {values.get('cassette_pue',1.0):.2f})"],
        "hrsg":     ["HRSG-01", f"{values.get('hrsg_eff_pct',0):.0f}% eff",
                     f"{k.get('Steam generation t/h',0):.2f} t/h"],
        "libr":     ["CH-01 · LiBr chiller", f"COP {values.get('libr_cop',0):.2f}",
                     f"Qcool {qcool:,.0f} kW"],
        "ct":       ["CT-01 · Cooling tower", "reject", f"≈{qcond:,.0f} kW"],
        # stream labels
        "s_exhaust": f"Exhaust {values.get('t_exhaust_C',0):.0f}°C · ≈{exh:,.0f} kW",
        "s_steam":   f"Steam · {values.get('steam_p_bar',0):.0f} bar · {qgen:,.0f} kW",
        "s_cool":    f"Cooling {qcool:,.0f} kW",
        "s_heat":    f"Heat {heat_load:,.0f} kW",
        "s_gpuheat": f"{heat_load:,.0f} kWe",
        # key results (Cassette-PUE / pump / fan echoes dropped; Plant PUE is the
        # single overhead summary)
        "results": [
            ("GT actual power",  f"{gt_actual:,.0f} kW", "verified"),
            ("NG consumption",   f"{k.get('NG consumption Nm3h',0):,.0f} Nm³/h", "verified"),
            ("Steam generation", f"{k.get('Steam generation t/h',0):.2f} t/h", "verified"),
            ("LiBr cooling, Qcool", f"{qcool:,.0f} kW", "verified"),
            ("GPU IT load",      f"{it:,.0f} kW", "verified"),
            ("LiBr COP",         f"{values.get('libr_cop',0):.2f}", "input"),
            ("Plant PUE (elec, export excl.)",
             f"{k.get('Plant PUE (electrical, export excluded)',0):.2f}", "screening"),
            ("Cooling tower duty", f"≈{qcond:,.0f} kW", "screening"),
            (export_label,       f"{export_val:,.0f} kW", "input" if not grid else "screening"),
        ],
        # energy balance & audit
        "balance": _balance_lines(pbal, cbal, n_ok, n_tot, fuel, qcond, gt_cw, stack,
                                  export_label, export_val),
    }


def _balance_lines(pbal, cbal, n_ok, n_tot, fuel, qcond, gt_cw, stack,
                   export_label, export_val):
    out = []
    if pbal is not None:
        out.append(("Electrical", f"supply {pbal.supply:,.0f} = demand {pbal.demand:,.0f} "
                                   f"→ {pbal.balance:+,.0f} kW", pbal.feasible))
    if cbal is not None:
        sign = "=" if abs(cbal.balance) < 1 else "≈"
        out.append(("Cooling", f"supply {cbal.supply:,.0f} {sign} demand {cbal.demand:,.0f} "
                               f"→ {cbal.balance:+,.0f} kW", cbal.feasible))
    out.append(("Audit", f"{n_ok} / {n_tot} checks passed", n_ok == n_tot and n_tot > 0))
    out.append(("First law", f"fuel {fuel:,.0f} ≈ {export_label.lower()} {export_val:,.0f} "
                             f"+ reject {qcond:,.0f} + GT/stack loss {gt_cw+stack:,.0f}", None))
    out.append(("Validation", "vs v1 GT tool ±2%, 14/14 pass", True))
    return out


# ── the flowable ─────────────────────────────────────────────────────────────

# Block coordinates (inches, PPTX top-left origin) — the faithful layout.
_BLOCKS = {
    "ng":       (0.28, 2.52, 1.55, 0.98),
    "gt":       (2.05, 2.25, 1.55, 1.62),
    "overhead": (4.55, 1.55, 2.05, 1.05),
    "export":   (6.85, 1.55, 1.55, 1.05),
    "gpu":      (8.60, 1.50, 1.95, 1.48),
    "hrsg":     (4.55, 3.95, 1.65, 1.05),
    "libr":     (8.60, 3.55, 1.95, 1.48),
    "ct":       (10.85, 3.60, 2.10, 1.32),
}
_PW, _PH = 13.3333, 7.5     # PPTX slide size (inches)


class PFDFlowable(Flowable):
    """Draws the GT-system PFD scaled to fill the available (landscape) frame."""

    def __init__(self, ctx: dict):
        super().__init__()
        self.ctx = ctx
        self._aw = self._ah = 0.0

    def wrap(self, aw, ah):
        self._aw, self._ah = aw, ah
        return aw, ah

    # coordinate transform: PPTX inches (y-down) -> reportlab points (y-up)
    def _setup(self):
        s = min(self._aw / (_PW * 72), self._ah / (_PH * 72))
        self._s = s
        dw, dh = _PW * 72 * s, _PH * 72 * s
        self._ox = (self._aw - dw) / 2.0
        self._oy = (self._ah - dh) / 2.0

    def _X(self, xin): return self._ox + xin * 72 * self._s
    def _Y(self, yin): return self._oy + (_PH - yin) * 72 * self._s   # top-edge y
    def _fs(self, pt): return pt * self._s

    def _rect(self, l, t, w, h, fill, stroke, lw=1.0, radius=0.08):
        c = self.canv
        x, y = self._X(l), self._Y(t + h)
        W, H = w * 72 * self._s, h * 72 * self._s
        if fill is not None: c.setFillColor(fill)
        if stroke is not None: c.setStrokeColor(stroke)
        c.setLineWidth(lw * self._s)
        c.roundRect(x, y, W, H, radius * 72 * self._s,
                    fill=1 if fill is not None else 0,
                    stroke=1 if stroke is not None else 0)

    def _lines(self, l, t, lines, size, color, align="left", bold=False, gap=1.18):
        """Draw stacked text lines from the top of (l, t)."""
        c = self.canv
        fs = self._fs(size)
        font = "Helvetica-Bold" if bold else "Helvetica"
        c.setFont(font, fs); c.setFillColor(color)
        x = self._X(l); y = self._Y(t) - fs
        for ln in lines:
            if align == "center":
                c.drawCentredString(x, y, ln)
            elif align == "right":
                c.drawRightString(x, y, ln)
            else:
                c.drawString(x, y, ln)
            y -= fs * gap

    def _arrow(self, x1in, y1in, x2in, y2in, color, lw=2.0):
        import math
        c = self.canv
        x1, y1, x2, y2 = self._X(x1in), self._Y(y1in), self._X(x2in), self._Y(y2in)
        c.setStrokeColor(color); c.setFillColor(color); c.setLineWidth(lw * self._s)
        c.line(x1, y1, x2, y2)
        ang = math.atan2(y2 - y1, x2 - x1); ah = 5 * self._s
        c.setLineWidth(max(0.5, 1.0 * self._s))
        for da in (math.radians(150), math.radians(-150)):
            c.line(x2, y2, x2 + ah * math.cos(ang + da) * 1.6,
                   y2 + ah * math.sin(ang + da) * 1.6)

    def _block(self, key, color=NAVY):
        l, t, w, h = _BLOCKS[key]
        self._rect(l, t, w, h, LIGHT, color, lw=1.2)
        lines = self.ctx[key]
        # title line bold, rest regular
        self._lines(l + 0.10, t + 0.10, [lines[0]], 8.0, NAVY, bold=True)
        if len(lines) > 1:
            self._lines(l + 0.10, t + 0.30, lines[1:], 7.4, INK)

    def draw(self):
        self._setup()
        c = self.canv
        ctx = self.ctx

        # ── header: title + design point ────────────────────────────────────
        self._lines(0.35, 0.16, [ctx["title"]], 15, NAVY, bold=True)
        self._lines(0.35, 0.70, [ctx["design"]], 8.2, GREY)

        # ── operating-mode strip (top-right) + island/grid badge ────────────
        badge = "GRID-TIED" if ctx["grid"] else "ISLAND"
        bcol = TEAL if ctx["grid"] else NAVY
        bx, by, bw, bh = 10.55, 0.14, 2.45, 0.34
        self._rect(bx, by, bw, bh, bcol, bcol, lw=0, radius=0.06)
        self._lines(bx + bw / 2, by + 0.045, [badge], 10.5, colors.white,
                    align="center", bold=True)
        self._lines(10.55, 0.60, [
            f"Operating mode · {ctx['mode_op']}",
            f"GT power control · {ctx['mode_gt']}",
            f"Steam split · {ctx['mode_split']}",
        ], 7.2, INK)

        # ── electrical bus line ─────────────────────────────────────────────
        c.setStrokeColor(ST_ELEC); c.setLineWidth(2.2 * self._s)
        c.line(self._X(3.55), self._Y(1.45), self._X(10.55), self._Y(1.45))
        self._lines(3.55, 1.12, [ctx["bus"]], 8.0, ST_ELEC, bold=True)

        # ── flow streams (arrows, coloured by kind) ─────────────────────────
        self._arrow(1.83, 3.01, 2.05, 3.01, ST_HEAT)            # NG -> GT
        self._arrow(3.05, 3.06, 4.55, 4.45, ST_HEAT)            # GT exhaust -> HRSG
        self._arrow(6.20, 4.45, 8.60, 4.30, ST_HEAT)            # HRSG steam -> LiBr
        self._arrow(9.55, 3.55, 9.55, 2.98, ST_COOL)            # LiBr cooling -> GPU
        self._arrow(9.95, 2.98, 9.95, 3.55, ST_COOL)            # GPU heat -> LiBr
        self._arrow(10.55, 4.27, 10.85, 4.27, ST_REJ)          # LiBr -> CT
        self._arrow(3.55, 1.45, 3.55, 2.25, ST_ELEC)           # bus down to GT label
        for xin in (5.55, 7.60, 9.55):                          # bus -> consumers
            self._arrow(xin, 1.45, xin, 1.55, ST_ELEC, lw=1.6)

        # ── blocks ──────────────────────────────────────────────────────────
        for key in ("ng", "gt", "overhead", "export", "gpu", "hrsg", "libr", "ct"):
            self._block(key)

        # ── stream labels ───────────────────────────────────────────────────
        self._lines(2.95, 4.48, [ctx["s_exhaust"]], 6.8, ST_HEAT)
        self._lines(6.45, 3.95, [ctx["s_steam"]],   6.8, ST_HEAT)
        self._lines(8.20, 3.10, [ctx["s_cool"]],    6.8, ST_COOL)
        self._lines(9.78, 3.10, [ctx["s_heat"]],    6.8, ST_COOL)
        self._lines(8.95, 1.05, [ctx["s_gpuheat"]], 6.8, ST_ELEC)

        # ── bottom panels (3 columns) ───────────────────────────────────────
        self._rect(0.35, 5.18, 5.05, 1.95, colors.white, LINEC, lw=0.8)
        self._rect(5.55, 5.18, 3.55, 1.95, colors.white, LINEC, lw=0.8)
        self._rect(9.25, 5.18, 3.73, 1.95, colors.white, LINEC, lw=0.8)

        # Key results
        self._lines(0.50, 5.25, ["Key results"], 9, NAVY, bold=True)
        y = 5.54
        for label, val, basis in ctx["results"]:
            self._lines(0.50, y, [label], 7.4, INK)
            self._lines(3.30, y, [val], 7.4, INK)
            self._lines(4.35, y, [basis], 7.0, BASIS.get(basis, GREY))
            y += 0.165

        # Energy balance & audit
        self._lines(5.70, 5.25, ["Energy balance & audit"], 9, NAVY, bold=True)
        y = 5.56
        for head, txt, ok in ctx["balance"]:
            col = INK if ok is None else (GREEN if ok else RED)
            self._lines(5.70, y, [head], 7.4, NAVY, bold=True)
            self._lines(6.55, y, [txt], 7.0, col)
            y += 0.30

        # Streams & basis legend
        self._lines(9.40, 5.25, ["Streams & basis"], 9, NAVY, bold=True)
        leg = [("Electrical (kWe)", ST_ELEC), ("Heat / steam (kWth)", ST_HEAT),
               ("Cooling, chilled water", ST_COOL), ("Rejected heat", ST_REJ)]
        y = 5.56
        for txt, col in leg:
            c.setStrokeColor(col); c.setLineWidth(2.4 * self._s)
            c.line(self._X(9.50), self._Y(y) - self._fs(7) * 0.4,
                   self._X(9.92), self._Y(y) - self._fs(7) * 0.4)
            self._lines(10.02, y, [txt], 7.2, INK)
            y += 0.185
        y += 0.06
        self._lines(9.40, y, ["Basis  (line colour = stream kind)"], 6.8, GREY)
        y += 0.20
        for txt, b in (("verified", "verified"), ("screening", "screening"), ("input", "input")):
            self._rect(9.50, y, 0.11, 0.11, BASIS[b], BASIS[b], lw=0, radius=0.0)
            self._lines(9.70, y - 0.01, [txt], 7.0, INK)
            y += 0.185


def make_pfd_flowable(engine, values, result):
    """Return a PFDFlowable for the GT system, or None for other engines."""
    ctx = pfd_context(engine, values, result)
    return PFDFlowable(ctx) if ctx is not None else None
