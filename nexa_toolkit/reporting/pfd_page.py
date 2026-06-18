"""
nexa_toolkit.reporting.pfd_page — the GT-system Process Flow Diagram as a live,
report-engine-native landscape page (no PowerPoint/LibreOffice at render time).

`make_pfd_flowable(engine, values, result)` returns a reportlab Flowable that
redraws the Nexa GT-system PFD with every value refreshed from the current
solve, or None for engines that aren't the GT system. build_pdf appends it as
the final landscape page.

Topology (post-rework): no steam splitter — all HRSG steam -> LiBr; a closed
dielectric-coolant loop (LiBr⇄GPU); the LiBr heat rejection drives MED (with a
manual MED-bypass), then an auto 3-way radiator valve trims the loop back to the
HRSG feedwater return set-point. Native reportlab redraw of the approved layout.
"""
from __future__ import annotations
from reportlab.platypus import Flowable
from reportlab.lib import colors

# Palette
NAVY  = colors.HexColor("#2E4E7E")
TEAL  = colors.HexColor("#2BB6A3")
INK   = colors.HexColor("#22303F")
GREY  = colors.HexColor("#5b6675")
LINEC = colors.HexColor("#C9D2E0")
LIGHT = colors.HexColor("#EAF0F8")
ORANGE= colors.HexColor("#E0902F")
GREEN = colors.HexColor("#2E7D4E")
RED   = colors.HexColor("#C0392B")
BASIS = {"verified": GREEN, "screening": ORANGE, "input": GREY, "unverified": RED}

# Stream colours
ST_STEAM = ORANGE   # steam / heat
ST_COOL  = TEAL     # dielectric coolant (GPU loop)
ST_REJ   = RED      # LiBr heat rejection
ST_LOOP  = colors.HexColor("#2E6FB0")   # cooling-water return


def _is_gt_system(result) -> bool:
    solved = result.get("solved") if isinstance(result, dict) else None
    if solved is None:
        return False
    try:
        from nexablock.blocks import GasTurbine, GPUCassette, LiBrChiller
    except Exception:
        return False
    # isinstance (not exact type) so subclasses like DoubleEffectLiBrChiller count.
    def _has(cls):
        return any(isinstance(b, cls) for b in solved.blocks)
    return _has(GasTurbine) and _has(GPUCassette) and _has(LiBrChiller)


def _mode_name(engine, key, val) -> str:
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
    if not _is_gt_system(result):
        return None
    from nexablock.blocks import (GasTurbine, DieselGenset, HRSG, LiBrChiller,
                                   DoubleEffectLiBrChiller, GPUCassette,
                                   MED, Radiator, CoolingTowerLoop, Calorifier)
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
    pump      = R(LiBrChiller, "LiBr pump electrical")
    fan       = R(Radiator,    "Radiator fan electrical")
    gt_aux    = R(GasTurbine,  "GT aux electrical")
    gt_actual = k.get("GT actual power kW", R(GasTurbine, "GT actual power"))
    bop       = max(0.0, getattr(solved, "bop_frac", 0.010)) * gt_actual
    overhead_total = pump + fan + gt_aux + bop

    qcool = k.get("LiBr cooling kW", R(LiBrChiller, "Cooling capacity kW"))
    qcond = R(LiBrChiller, "Condenser duty")
    reject_t = R(LiBrChiller, "Rejection loop temp") or values.get("libr_reject_t_C", 95.0)
    fuel  = R(GasTurbine, "Fuel energy input")
    exh   = R(GasTurbine, "Exhaust heat")
    med_water = k.get("MED water m3day", R(MED, "Water production m3/day"))
    med_th    = R(MED, "MED thermal input")
    med_byp   = R(MED, "MED bypass")
    _med_mode = getattr(getattr(solved, "params", None), "med_bypass_mode", "manual")
    _byp_tag  = "auto" if _med_mode == "auto" else "manual"
    rad_duty  = R(Radiator, "Radiator duty")
    rad_split = R(Radiator, "Through-radiator split")
    sw_m3h    = R(MED, "Seawater feed")
    brine_m3h = R(MED, "Brine reject")
    sw_t      = values.get("sw_t_C", 28.0)

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

    # Chiller box label reflects single- vs double-effect (detected from the block).
    _is_de = any(isinstance(b, DoubleEffectLiBrChiller) for b in solved.blocks)
    libr_name = "2x LiBr (DE)" if _is_de else "LiBr Chiller"

    # Backup engine: prime mover may be the diesel; reject may be the cooling tower.
    _pm_block  = next((b for b in solved.blocks if isinstance(b, GasTurbine)), None)
    _on_diesel = isinstance(_pm_block, DieselGenset)
    pm_name    = "Diesel Genset" if _on_diesel else "Gas Turbine"
    pm_mw  = (values.get("diesel_rated_kW", 1500) if _on_diesel else values.get("p_rated_kW", 0)) / 1000.0
    pm_eff = (values.get("diesel_eff", 0.40) if _on_diesel else values.get("gt_eff", 0)) * 100.0
    _rej_block = next((b for b in solved.blocks if isinstance(b, Radiator)), None)
    rej_name   = "Cooling Tower" if isinstance(_rej_block, CoolingTowerLoop) else "Radiator (fans)"
    _params    = getattr(solved, "params", None)
    _libr_failed = bool(getattr(_params, "libr_failed", False))
    backup_note = None
    if _on_diesel or _libr_failed:
        bits = []
        if _on_diesel:    bits.append("GT FAILED → diesel")
        if _libr_failed:  bits.append("LiBr FAILED → tower")
        backup_note = "BACKUP: " + " · ".join(bits)
    if _libr_failed:
        libr_name = "2x LiBr — FAILED"

    # Cooling-tower GPU-cooling duty + utilisation (from the resilience layer):
    # 0 when the LiBr carries it all, the top-up share on a GT-failure diesel run,
    # the full GPU heat when the LiBr has failed.
    _b = result.get("resilience") or {}
    _backup = bool(_b)
    _tower_gpu  = _b.get("tower_topup_kW", 0.0)
    _gpu_heat   = _b.get("gpu_heat_kW", 0.0) or 1.0
    _tower_util = 100.0 * _tower_gpu / _gpu_heat
    _libr_share = qcool                                  # LiBr's own cooling (0 if failed)
    libr_line2  = "tripped — 0 cooling" if _libr_failed else f"COP {values.get('libr_cop',0):.2f}"
    if _backup:
        # short enough for the 112-px tower box: duty + utilisation only
        rad_line3 = f"GPU {_tower_gpu:,.0f} kW · {_tower_util:.0f}%"
    else:
        rad_line3 = f"duty {rad_duty:,.0f} kW · {rad_split:.0f}% open"

    # Dielectric (GPU coolant) routing for the PFD, by cooling source:
    #   "libr"  — LiBr cools the GPU directly (normal / non-backup)
    #   "both"  — diesel-LiBr cools and the tower tops up (GT-failure backup)
    #   "tower" — LiBr tripped → the tower carries the whole GPU loop
    if _libr_failed:
        diel_mode = "tower"
    elif _backup and _tower_gpu > 1.0:
        diel_mode = "both"
    else:
        diel_mode = "libr"

    return {
        "title": "Nexa Block v1 — GT system energy balance",
        "design": (f"Design point:  GT {values.get('p_rated_kW',0)/1000:.0f} MW · "
                   f"{values.get('gt_eff',0)*100:.0f}% · ambient {values.get('t_ambient_C',0):.0f}°C · "
                   f"steam {values.get('steam_p_bar',0):.0f} bar · "
                   f"dielectric coolant {values.get('gpu_t_in_C',0):.0f}->{values.get('gpu_t_out_C',0):.0f}°C · "
                   f"LiBr rejection {reject_t:.0f}°C · return {values.get('fw_t_C',0):.0f}°C · "
                   f"{int(values.get('med_effects',0))}-effect MED"),
        "grid": grid,
        "mode_op": _mode_name(engine, "operating_mode", values.get("operating_mode", 0)),
        "mode_gt": _mode_name(engine, "gt_power_mode",  values.get("gt_power_mode", 0)),
        # block labels
        "gt":   [pm_name, f"{pm_mw:.0f} MW · {pm_eff:.0f}%",
                 f"load {load_pct:.1f}%  ·  {gt_actual:,.0f} kWe"],
        "backup_note": backup_note,
        "libr_failed": _libr_failed,
        "diel_mode": diel_mode,
        "hrsg": ["HRSG", f"{values.get('hrsg_eff_pct',0):.0f}% eff",
                 f"{k.get('Steam generation t/h',0):.2f} t/h"],
        "libr": [libr_name, libr_line2, f"Qcool {qcool:,.0f} kW"],
        "gpu":  ["GPU cassette", f"{it:,.0f} kWe IT  (PUE {values.get('cassette_pue',1.0):.2f})",
                 f"+{cassette:.0f} kW overhead"],
        "med":  ["MED Desalination", "rejection-driven",
                 f"{med_water:,.0f} m³/day"],
        "rad":  [rej_name, f"approach {values.get('tower_approach_K',15):.0f} K", rad_line3],
        # stream labels
        "s_exhaust": f"exhaust · ~{exh:,.0f} kW",
        "s_steam":   f"all steam · {values.get('steam_p_bar',0):.0f} bar",
        "s_diel":    f"dielectric coolant {values.get('gpu_t_in_C',0):.0f}-{values.get('gpu_t_out_C',0):.0f}°C",
        "s_rej":     f"rejection {reject_t:.0f}°C · {qcond:,.0f} kW",
        "s_byp":     f"MED bypass {med_byp:.0f}% ({_byp_tag})",
        "s_return":  f"return {values.get('fw_t_C',0):.0f}°C -> HRSG feedwater (closed loop)",
        "s_sw":      f"seawater {sw_t:.0f}°C · {sw_m3h:,.0f} m³/h",
        "s_fresh":   f"fresh {med_water:,.0f} m³/d",
        "s_brine":   f"brine {brine_m3h:,.0f} m³/h",
        "s_split":   (f"steam split {(cs.libr_frac if cs else 1.0)*100:.0f}% LiBr / "
                      f"{(1-(cs.libr_frac if cs else 1.0))*100:.0f}% → calorifier"
                      if getattr(getattr(solved, "params", None), "steam_split_mode", "off") == "auto"
                      else None),
        "cal":       ["Calorifier", "surplus steam",
                      f"{R(Calorifier, 'Calorifier duty'):,.0f} kW → MED"],
        "streams":   collect_streams(solved),
        # key results
        "results": [
            ("GT actual power",  f"{gt_actual:,.0f} kW", "verified"),
            ("NG consumption",   f"{k.get('NG consumption Nm3h',0):,.0f} Nm³/h", "verified"),
            ("Steam generation", f"{k.get('Steam generation t/h',0):.2f} t/h", "verified"),
            ("LiBr cooling, Qcool", f"{qcool:,.0f} kW", "verified"),
            ("GPU IT load",      f"{it:,.0f} kW", "verified"),
            ("MED water (rejection-driven)", f"{med_water:,.0f} m³/day", "screening"),
            ("Radiator duty",    f"{rad_duty:,.0f} kW", "screening"),
            ("Plant PUE (elec, export excl.)",
             f"{k.get('Plant PUE (electrical, export excluded)',0):.2f}", "screening"),
            (export_label,       f"{export_val:,.0f} kW", "input" if not grid else "screening"),
        ],
        "balance": _balance_lines(pbal, cbal, n_ok, n_tot, fuel, qcond),
        "overhead_note": (f"Plant overhead {overhead_total:,.0f} kWe  "
                          f"(pump {pump:.0f} · radiator fan {fan:.0f} · GT aux {gt_aux:.0f} · BoP {bop:.0f})"),
    }


def _balance_lines(pbal, cbal, n_ok, n_tot, fuel, qcond):
    out = []
    if pbal is not None:
        out.append(("Electrical", f"supply {pbal.supply:,.0f} = demand {pbal.demand:,.0f} "
                                   f"-> {pbal.balance:+,.0f} kW", pbal.feasible))
    if cbal is not None:
        sign = "=" if abs(cbal.balance) < 1 else "~"
        out.append(("Cooling", f"supply {cbal.supply:,.0f} {sign} demand {cbal.demand:,.0f} "
                               f"-> {cbal.balance:+,.0f} kW", cbal.feasible))
    out.append(("Audit", f"{n_ok} / {n_tot} checks passed", n_ok == n_tot and n_tot > 0))
    out.append(("Heat reject", f"LiBr rejection {qcond:,.0f} kW -> MED + radiator", None))
    out.append(("Recycle", "dielectric loop converged; cooling loop -> HRSG feedwater", True))
    return out


# ── single SVG layout — used for BOTH the on-screen chart and (rasterised) the
#    report page, so they are guaranteed identical. ───────────────────────────
_SC = {"steam": "#E0902F", "cool": "#2BB6A3", "rej": "#C0392B", "loop": "#2E6FB0",
       "sea": "#1F8A70", "brine": "#8A6D3B"}
# block boxes (x, y, w, h) on the 680-wide SVG canvas
_B = {
    "gt":   (12,  72, 100, 48), "hrsg": (152, 72, 100, 48),
    "libr": (322, 72, 100, 48), "gpu":  (558, 72, 100, 48),
    "med":  (250, 252, 100, 48), "rad": (452, 252, 112, 48),
    "cal":  (237, 166, 100, 42),    # calorifier — only drawn when steam split is on
}
_BFILL = {"gt": "#F2C14E", "hrsg": "#E8956B", "libr": "#6FA8DC",
          "gpu": "#B49AD4", "med": "#93D7A8", "rad": "#6FA8DC",
          "cal": "#F0C98A"}


def _esc(s): return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _svg_box(key, lines):
    x, y, w, h = _B[key]; cx = x + w / 2
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6" '
           f'fill="{_BFILL[key]}" stroke="#5b6675" stroke-width="1.2"/>',
           f'<text x="{cx}" y="{y+18}" text-anchor="middle" font-weight="700" '
           f'font-size="11" fill="#22303F">{_esc(lines[0])}</text>']
    yy = y + 31
    for ln in lines[1:]:
        out.append(f'<text x="{cx}" y="{yy}" text-anchor="middle" font-size="9" '
                   f'fill="#22303F">{_esc(ln)}</text>')
        yy += 11
    return "".join(out)


def _svg_text(x, y, s, size, color, anchor="start", bold=False):
    w = ' font-weight="700"' if bold else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"'
            f'{w} fill="{color}">{_esc(s)}</text>')


def collect_streams(solved) -> list:
    """Heat-&-material balance rows for every block port: (group, [(port, T, P, flow)]).
    T in °C, P in bar, flow in kg/s — read from each port's solved Stream, with the
    feedwater and seawater inlets (seeded pools) taken from the computed results."""
    from nexablock.blocks import (GasTurbine, HRSG, LiBrChiller, GPUCassette,
                                  MED, Radiator, Calorifier)
    p = getattr(solved, "params", None)

    def blk(cls): return next((b for b in solved.blocks if isinstance(b, cls)), None)

    def strm(b, name):
        if b is None:
            return None
        port = getattr(b, "inlets", {}).get(name) or getattr(b, "outlets", {}).get(name)
        return port.stream if port is not None else None

    def res(b, label, d=None):
        if b is None:
            return d
        r = b.results.get(label)
        return r.value if r is not None else d

    def prow(label, b, name):
        s = strm(b, name)
        T = f"{s.T - 273.15:.0f}" if (s is not None and s.T) else "—"
        P = f"{s.P / 1e5:.1f}"    if (s is not None and s.P) else "—"
        M = f"{s.mdot:.1f}"       if (s is not None and s.mdot) else "—"
        return (label, T, P, M)

    def crow(label, T, P, M):
        return (label,
                f"{T:.0f}" if T is not None else "—",
                f"{P:.1f}" if P is not None else "—",
                f"{M:.1f}" if M is not None else "—")

    gt = blk(GasTurbine); h = blk(HRSG); lb = blk(LiBrChiller)
    gp = blk(GPUCassette); md = blk(MED); rd = blk(Radiator); cal = blk(Calorifier)
    fw = getattr(p, "fw_t_C", 80.0); sw = getattr(p, "sw_t_C", 28.0)
    sp = getattr(p, "steam_p_bar", 10.0)
    s_steam = strm(h, "steam")
    steam_mdot = s_steam.mdot if (s_steam is not None and s_steam.mdot) else None
    sw_m3h = res(md, "Seawater feed")
    sw_kgs = sw_m3h * 1020.0 / 3600.0 if sw_m3h else None

    groups = [
        ("Gas Turbine", [prow("exhaust out", gt, "exhaust")]),
        ("HRSG", [prow("exhaust in", h, "exhaust_in"),
                  crow("feedwater in", fw, sp, steam_mdot),
                  prow("steam out", h, "steam"),
                  prow("stack gas out", h, "stack")]),
        ("LiBr chiller", [prow("steam in", lb, "steam_in"),
                          prow("coolant return in", lb, "chw_return"),
                          prow("coolant supply out", lb, "chw_supply"),
                          prow("condensate out", lb, "condensate"),
                          prow("rejection out", lb, "reject_out")]),
        ("GPU cassette", [prow("coolant in", gp, "coolant_in"),
                          prow("coolant out", gp, "coolant_out")]),
        ("MED desalination", [prow("loop in", md, "loop_in"),
                              crow("seawater in", sw, 1.5, sw_kgs),
                              prow("loop out", md, "loop_out"),
                              prow("fresh water out", md, "fresh"),
                              prow("brine out", md, "brine")]),
        ("Radiator", [prow("loop in", rd, "loop_in"),
                      prow("loop out", rd, "loop_out")]),
    ]
    if cal is not None:                                  # LiBr-priority steam split active
        groups.append(("Calorifier (surplus steam)",
                       [prow("steam in", cal, "steam_in"),
                        prow("hot water out", cal, "hot_out"),
                        prow("condensate out", cal, "condensate")]))
    return groups


def _render_stream_table(groups, y0=356):
    """Two-column heat-&-material balance table; groups split evenly between the
    columns (so an extra block like the calorifier still fits). Returns
    (svg_fragments, bottom_y)."""
    out = [_svg_text(12, y0, "Stream table  —  inlet / outlet  T (°C) · P (bar) · flow (kg/s)",
                     10, "#2E4E7E", bold=True)]
    half = (len(groups) + 1) // 2
    cols = [(groups[:half], 12, 196, 236, 300), (groups[half:], 352, 536, 576, 644)]
    pitch = 12
    bottom = y0 + 16
    for grp_list, nx, tx, px, fx in cols:
        yy = y0 + 16
        out += [_svg_text(tx, yy, "T", 7, "#5b6675", anchor="end"),
                _svg_text(px, yy, "bar", 7, "#5b6675", anchor="end"),
                _svg_text(fx, yy, "kg/s", 7, "#5b6675", anchor="end")]
        yy += pitch
        for gname, rows in grp_list:
            out.append(_svg_text(nx, yy, gname, 8.5, "#2E4E7E", bold=True))
            yy += pitch
            for (label, T, P, F) in rows:
                out += [_svg_text(nx + 8, yy, label, 7.6, "#22303F"),
                        _svg_text(tx, yy, T, 7.6, "#22303F", anchor="end"),
                        _svg_text(px, yy, P, 7.6, "#22303F", anchor="end"),
                        _svg_text(fx, yy, F, 7.6, "#22303F", anchor="end")]
                yy += pitch
            yy += 3
        bottom = max(bottom, yy)
    return out, bottom


def pfd_svg(ctx: dict, with_panels: bool = True) -> str:
    """The GT-system PFD as an SVG string. with_panels adds the Key-results /
    energy-balance / legend panels (report page); without -> flow diagram only
    (on-screen chart). Same layout either way, so the two always match."""
    H = 615 if with_panels else 575
    f = ['<defs>']
    for nm, col in (("aS", _SC["steam"]), ("aC", _SC["cool"]),
                    ("aR", _SC["rej"]), ("aL", _SC["loop"]),
                    ("aSea", _SC["sea"]), ("aBr", _SC["brine"])):
        f.append(f'<marker id="{nm}" viewBox="0 0 10 10" refX="8" refY="5" '
                 f'markerWidth="6" markerHeight="6" orient="auto">'
                 f'<path d="M2 1L8 5L2 9" fill="none" stroke="{col}" stroke-width="1.6"/></marker>')
    f.append('</defs>')
    FL = 'fill="none" stroke-width="2.3"'
    split = bool(ctx.get("s_split"))
    # flows
    f += [
        f'<path d="M112 96 H152" {FL} stroke="{_SC["steam"]}" marker-end="url(#aS)"/>',
        f'<path d="M372 120 V179" {FL} stroke="{_SC["rej"]}" marker-end="url(#aR)"/>',
        f'<path d="M364 186 H342 V252" {FL} stroke="{_SC["rej"]}" marker-end="url(#aR)"/>',
        f'<path d="M380 186 H414 V275" {FL} stroke="{_SC["rej"]}" stroke-dasharray="5 3"/>',
        f'<path d="M350 276 H430" {FL} stroke="{_SC["rej"]}" marker-end="url(#aR)"/>',
        f'<path d="M446 276 H452" {FL} stroke="{_SC["rej"]}" marker-end="url(#aR)"/>',
        f'<path d="M438 285 V322" {FL} stroke="{_SC["loop"]}"/>',
        f'<path d="M508 300 V322" {FL} stroke="{_SC["loop"]}"/>',
        f'<path d="M508 322 H192 V120" {FL} stroke="{_SC["loop"]}" marker-end="url(#aL)"/>',
    ]
    if split:
        # HRSG steam → 3-way splitter → LiBr, with the surplus branch down to the
        # calorifier, whose hot water joins the rejection at a mixer dot → MED.
        f += [
            f'<path d="M252 96 H281" {FL} stroke="{_SC["steam"]}"/>',
            f'<path d="M293 96 H322" {FL} stroke="{_SC["steam"]}" marker-end="url(#aS)"/>',
            f'<path d="M287 102 V166" {FL} stroke="{_SC["steam"]}" marker-end="url(#aS)"/>',
            f'<path d="M287 208 V240 H340" {FL} stroke="{_SC["rej"]}" marker-end="url(#aR)"/>',
        ]
        f.append(f'<path d="M287 89 L295 96 L287 103 L279 96 Z" fill="#22303F"/>')  # 3-way valve
        f.append(f'<circle cx="342" cy="240" r="2.6" fill="{_SC["rej"]}"/>')        # mixer junction
    else:
        f.append(f'<path d="M252 96 H322" {FL} stroke="{_SC["steam"]}" marker-end="url(#aS)"/>')
    # valves + junction
    for vx, vy in ((372, 186), (438, 276)):
        f.append(f'<path d="M{vx} {vy-7} L{vx+8} {vy} L{vx} {vy+7} L{vx-8} {vy} Z" fill="#22303F"/>')
    f.append(f'<circle cx="414" cy="276" r="2.6" fill="{_SC["rej"]}"/>')
    # boxes
    boxes = ("gt", "hrsg", "libr", "gpu", "med", "rad") + (("cal",) if split else ())
    for kk in boxes:
        f.append(_svg_box(kk, ctx[kk]))
    if split:
        f.append(_svg_text(287, 86, "3-way", 6, _SC["steam"], anchor="middle"))
    # ── dielectric coolant (GPU loop) — routed by the cooling source ──────────
    _DC = _SC["cool"]
    diel = ctx.get("diel_mode", "libr")
    if diel in ("libr", "both"):
        f += [
            f'<path d="M422 88 H558" {FL} stroke="{_DC}" marker-end="url(#aC)"/>',   # supply LiBr→GPU
            f'<path d="M558 104 H424" {FL} stroke="{_DC}" marker-end="url(#aC)"/>',  # return GPU→LiBr
        ]
    if diel == "both":
        # T-connections: the warm return is tapped down into the tower and the
        # cooled water rejoins the supply — the tower shares the GPU loop with LiBr.
        f += [
            f'<path d="M536 104 V252" {FL} stroke="{_DC}" marker-end="url(#aC)"/>',  # return → tower
            f'<path d="M480 252 V88"  {FL} stroke="{_DC}" marker-end="url(#aC)"/>',  # tower → supply
            f'<circle cx="536" cy="104" r="2.6" fill="{_DC}"/>',
            f'<circle cx="480" cy="88"  r="2.6" fill="{_DC}"/>',
        ]
        f.append(_svg_text(508, 248, "tower shares GPU loop", 6, _DC, anchor="middle"))
    elif diel == "tower":
        # LiBr out of the loop: the GPU dielectric loops only to the cooling tower.
        f += [
            f'<path d="M558 104 H536 V252" {FL} stroke="{_DC}" marker-end="url(#aC)"/>',  # GPU → tower
            f'<path d="M480 252 V88 H558"  {FL} stroke="{_DC}" marker-end="url(#aC)"/>',  # tower → GPU
        ]
        f.append(_svg_text(508, 248, "GPU cooled by tower (LiBr out)", 6, _DC, anchor="middle"))
    # header
    f.append(_svg_text(12, 22, ctx["title"], 15, "#2E4E7E", bold=True))
    f.append(_svg_text(12, 40, ctx["design"], 8, "#5b6675"))
    bcol = _SC["cool"] if ctx["grid"] else "#2E4E7E"
    f.append(f'<rect x="556" y="12" width="116" height="20" rx="4" fill="{bcol}"/>')
    f.append(_svg_text(614, 26, "GRID-TIED" if ctx["grid"] else "ISLAND", 10.5,
                       "#FFFFFF", anchor="middle", bold=True))
    f.append(_svg_text(672, 44, f"GT power · {ctx['mode_gt']}", 7.5, "#5b6675", anchor="end"))
    if ctx.get("backup_note"):
        f.append(_svg_text(672, 56, ctx["backup_note"], 8, _SC["rej"], anchor="end", bold=True))
    # stream labels (in clear whitespace)
    f.append(_svg_text(132, 64, ctx["s_exhaust"], 7, _SC["steam"], anchor="middle"))
    f.append(_svg_text(287, 64, ctx["s_steam"],   7, _SC["steam"], anchor="middle"))
    f.append(_svg_text(490, 62, ctx["s_diel"],    7, _SC["cool"],  anchor="middle"))
    f.append(_svg_text(382, 150, ctx["s_rej"],    7, _SC["rej"]))
    f.append(_svg_text(420, 232, ctx["s_byp"],    7, _SC["rej"]))
    f.append(_svg_text(120, 336, ctx["s_return"], 7.5, _SC["loop"]))
    # MED auxiliary streams: seawater feed (in, left), fresh water + brine (out, bottom)
    f += [
        f'<path d="M214 284 H250" {FL} stroke="{_SC["sea"]}" marker-end="url(#aSea)"/>',
        f'<path d="M286 300 V316" {FL} stroke="{_SC["sea"]}" marker-end="url(#aSea)"/>',
        f'<path d="M320 300 V316" {FL} stroke="{_SC["brine"]}" marker-end="url(#aBr)"/>',
    ]
    f.append(_svg_text(212, 280, ctx["s_sw"],    6.5, _SC["sea"], anchor="end"))
    f.append(_svg_text(280, 328, ctx["s_fresh"], 6.5, _SC["sea"], anchor="middle"))
    f.append(_svg_text(330, 328, ctx["s_brine"], 6.5, _SC["brine"]))
    # steam-split annotation (only when the calorifier path is active)
    if ctx.get("s_split"):
        f.append(_svg_text(287, 54, ctx["s_split"], 6.5, _SC["steam"], anchor="middle"))
    # stream table (heat & material balance) — always shown, both chart + report
    tbl, tbl_bottom = _render_stream_table(ctx["streams"], y0=356)
    f += tbl
    # report-only footer: compact energy balance + stream-colour legend
    if with_panels:
        yb = tbl_bottom + 14
        bx = 12
        for head, txt, ok in ctx["balance"][:3]:        # Electrical · Cooling · Audit
            col = "#22303F" if ok is None else ("#2E7D4E" if ok else "#C0392B")
            f.append(_svg_text(bx, yb, f"{head}", 7.5, "#2E4E7E", bold=True))
            f.append(_svg_text(bx, yb + 11, txt, 6.8, col))
            bx += 178
        lx = 12; ly = yb + 25
        for txt, col in (("steam / heat", _SC["steam"]), ("dielectric coolant", _SC["cool"]),
                         ("LiBr rejection", _SC["rej"]), ("loop return", _SC["loop"]),
                         ("seawater / fresh", _SC["sea"]), ("brine", _SC["brine"])):
            f.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+14}" y2="{ly}" stroke="{col}" stroke-width="2.4"/>')
            f.append(_svg_text(lx + 18, ly + 3, txt, 6.5, "#22303F"))
            lx += 112
        H = ly + 14
    else:
        H = tbl_bottom + 10
    body = "".join(f)
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 680 {int(H)}" '
            f'font-family="Helvetica,Arial,sans-serif">{body}</svg>')


_BHEX = {"verified": "#2E7D4E", "screening": "#B26A00", "input": "#5b6675",
         "unverified": "#C0392B"}


def pfd_chart_svg(engine, values, result) -> str | None:
    """Topology-only SVG (no panels) for the on-screen chart slot."""
    ctx = pfd_context(engine, values, result)
    return pfd_svg(ctx, with_panels=False) if ctx is not None else None


def make_pfd_flowable(engine, values, result):
    """Reportlab Image of the rasterised full PFD (with panels), sized to the
    landscape frame. Same SVG the on-screen chart uses -> identical look."""
    ctx = pfd_context(engine, values, result)
    if ctx is None:
        return None
    import tempfile, os
    import cairosvg
    from reportlab.platypus import Image
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.lib.units import mm
    svg = pfd_svg(ctx, with_panels=True)
    png = os.path.join(tempfile.mkdtemp(), "pfd.png")
    cairosvg.svg2png(bytestring=svg.encode("utf-8"), write_to=png, output_width=1800)
    LAND = landscape(A4)
    # landscape frame minus reportlab's 6 pt frame padding each side, minus a
    # small safety margin so the image never overflows the frame.
    fw = LAND[0] - 24 * mm - 14
    fh = LAND[1] - 24 * mm - 14
    import re
    m = re.search(r'viewBox="0 0 (\d+) (\d+)"', svg)     # match the dynamic height
    aspect = (int(m.group(1)) / int(m.group(2))) if m else 680.0 / 615.0
    if fw / fh > aspect:                               # height-bound
        h = fh; w = fh * aspect
    else:
        w = fw; h = fw / aspect
    return Image(png, width=w, height=h)
