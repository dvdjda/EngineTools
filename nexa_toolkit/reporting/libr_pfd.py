"""
nexa_toolkit.reporting.libr_pfd — LiBr-H2O absorption chiller process flow diagram.

Single SVG (same style as the GT-system PFD), used for both the on-screen chart
and the rasterised report page, so they are always identical.

Two layouts:

* single-effect — Generator · SHX · Absorber in a vertical left column, with the
  weak (up) and strong (down) solution streams as parallel lines into two
  distinct absorber points; Condenser/Evaporator on the right. Generator and
  condenser share the HIGH-side pressure; evaporator and absorber the LOW side
  (the solution temperature is well above pure-water saturation because of the
  LiBr boiling-point elevation, so e.g. 93 degC solution at 6.6 kPa is correct).

* double-effect — adds the high-temperature generator (HTG) at a THIRD, higher
  pressure level whose vapour condenses to drive the low-temperature generator
  (LTG) at the condenser pressure (internal heat recovery), with separate high-
  and low-temperature solution heat exchangers (HTHE / LTHE). Three pressure
  levels are shown: HTG > LTG = condenser > evaporator = absorber.

A footer metrics band carries the duties + crystallisation margin so the
flowsheet and the duty read-out appear together. `libr_pfd_svg(engine, result)`
returns an SVG string.
"""
from __future__ import annotations

NAVY, TEAL, INK, GREY = "#2E4E7E", "#2BB6A3", "#22303F", "#5b6675"
RED, ORANGE, GREEN, BLUE = "#C0392B", "#E0902F", "#2E7D4E", "#2E6FB0"
PURPLE = "#7E57C2"
ST_REF = BLUE      # refrigerant (water) vapour / liquid
ST_SOL = PURPLE    # LiBr solution (weak / strong)
ST_CHW = TEAL      # chilled water
ST_CW  = "#6FA8DC"  # cooling water
ST_HEAT = ORANGE   # heat source / steam / gas
ST_INT = "#C0392B"  # internal HTG-vapour heat recovery

FILL = {"gen": "#F0B45C", "htg": "#E59A3C", "ltg": "#F0C98A", "cond": "#6FA8DC",
        "abs": "#8FB8E0", "evap": "#7FD3C4", "shx": "#D8DEE9", "burn": "#E08A6B"}


def _esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _txt(x, y, s, size, color, anchor="start", bold=False):
    w = ' font-weight="700"' if bold else ""
    return (f'<text x="{x}" y="{y}" text-anchor="{anchor}" font-size="{size}"'
            f'{w} fill="{color}">{_esc(s)}</text>')


def _box(rect, title, lines, fill):
    x, y, w, h = rect; cx = x + w / 2
    out = [f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="7" '
           f'fill="{fill}" stroke="{GREY}" stroke-width="1.2"/>',
           _txt(cx, y + (19 if h >= 48 else 15), title, 10.5 if h >= 48 else 9.5,
                INK, "middle", bold=True)]
    yy = y + (33 if h >= 48 else 27)
    for ln in lines:
        out.append(_txt(cx, yy, ln, 8.3, INK, "middle"))
        yy += 11
    return "".join(out)


def _arrow(x1, y1, x2, y2, color, dash=False, wdt=2):
    d = ' stroke-dasharray="5 3"' if dash else ""
    return (f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{color}" '
            f'stroke-width="{wdt}"{d} marker-end="url(#ah_{color.lstrip("#")})"/>')


def _marker(color):
    cid = color.lstrip("#")
    return (f'<marker id="ah_{cid}" markerWidth="9" markerHeight="9" refX="6" '
            f'refY="3" orient="auto"><path d="M0,0 L6,3 L0,6 Z" fill="{color}"/></marker>')


def _num(r, key, fmt="{:.0f}", default="—"):
    v = r.get(key)
    try:
        return fmt.format(v)
    except Exception:
        return default


def _open(W, H, colors):
    defs = "".join(_marker(c) for c in colors)
    return [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
            f'font-family="DejaVu Sans, Arial, sans-serif">',
            f'<defs>{defs}</defs>',
            f'<rect x="0" y="0" width="{W}" height="{H}" fill="white"/>']


def _header(s, r, W):
    s.append(_txt(14, 26, f"LiBr-H₂O absorption chiller  —  {r.get('effect_label','')}",
                  14, NAVY, bold=True))
    s.append(_txt(W - 14, 26,
                  f"COP {_num(r,'cop','{:.3f}')}   (OEM rated {_num(r,'cop_rated','{:.2f}')})",
                  12, GREEN, anchor="end", bold=True))
    fy = 44
    if r.get("drive_low"):
        s.append(_txt(14, fy, f"! drive < {_num(r,'double_min_drive_c')} °C — too cool for "
                      f"double-effect (needs ~150 °C)", 9, RED, "start", bold=True))
        fy += 13
    if r.get("cooling_deficit_kw", 0.0) > 0.1:
        s.append(_txt(14, fy, f"! cooling deficit {_num(r,'cooling_deficit_kw')} kW "
                      f"(burner off, source short)", 9, RED, "start", bold=True))


def _footer(s, r, W, fy):
    s.append(f'<line x1="14" y1="{fy-14}" x2="{W-14}" y2="{fy-14}" stroke="#E4E8EF" stroke-width="1"/>')
    margin = r.get("cryst_margin_pct", 0.0)
    safe = margin > 0
    chips = [
        ("COP", _num(r, "cop", "{:.3f}"), GREEN),
        ("Q_evap", f"{_num(r,'q_evap_kw')} kW", TEAL),
        ("Q_gen", f"{_num(r,'q_gen_kw')} kW", ORANGE),
        ("Q_cond", f"{_num(r,'q_cond_kw')} kW", BLUE),
        ("Q_abs", f"{_num(r,'q_abs_kw')} kW", NAVY),
        ("LiBr", f"{_num(r,'x_weak_pct','{:.0f}')}-{_num(r,'x_strong_pct','{:.0f}')}%", PURPLE),
        ("cryst.", f"{margin:+.1f}% {'safe' if safe else 'risk'}", GREEN if safe else RED),
    ]
    stg = r.get("stage") or {}
    if stg:
        chips.insert(3, ("q_int", f"{_num(stg,'q_internal_kw')} kW", ST_INT))
    if r.get("burner_on"):
        chips.append(("NG", f"{(r.get('fuel_nm3h') or 0.0):.1f} Nm³/h", RED))
    cx = 18
    for label, val, col in chips:
        s.append(_txt(cx, fy, label, 8, GREY, "start"))
        s.append(_txt(cx, fy + 13, val, 9.5, col, "start", bold=True))
        cx += max(74, 10.5 * len(val))


def _tp(t, p):
    return f"{t} °C · {p} kPa"


# ── single-effect ────────────────────────────────────────────────────────────
def _render_single(r):
    W, H = 720, 470
    burner_on = bool(r.get("burner_on")); capped = bool(r.get("source_capped"))
    fuel = r.get("fuel_nm3h", 0.0) or 0.0
    show_burner = burner_on or capped
    B = {"gen": (205, 58, 160, 60), "cond": (480, 58, 160, 60),
         "abs": (205, 330, 160, 60), "evap": (480, 330, 160, 60),
         "shx": (240, 250, 90, 46), "burn": (24, 58, 150, 60)}
    X_WEAK, X_STRONG = 248, 322
    s = _open(W, H, {ST_REF, ST_SOL, ST_CHW, ST_CW, ST_HEAT})
    _header(s, r, W)

    ph, pl = _num(r, "p_high_kpa", "{:.1f}"), _num(r, "p_low_kpa", "{:.2f}")
    gx, gy, gw, gh = B["gen"]; ax, ay, aw, ah = B["abs"]
    s.append(_box(B["gen"], "Generator", [f"Q_gen {_num(r,'q_gen_kw')} kW",
              f"{_num(r,'t_gen_c')} °C soln · {ph} kPa"], FILL["gen"]))
    s.append(_box(B["cond"], "Condenser", [f"Q_cond {_num(r,'q_cond_kw')} kW",
              _tp(_num(r, "t_cond_c"), ph)], FILL["cond"]))
    s.append(_box(B["evap"], "Evaporator", [f"Q_evap {_num(r,'q_evap_kw')} kW",
              _tp(_num(r, "t_evap_c"), pl)], FILL["evap"]))
    s.append(_box(B["abs"], "Absorber", [f"Q_abs {_num(r,'q_abs_kw')} kW",
              _tp(_num(r, "t_abs_c"), pl)], FILL["abs"]))

    # solution loop — two parallel vertical lines into two absorber points
    gen_bot, abs_top = gy + gh, ay
    s.append(_arrow(X_WEAK, abs_top, X_WEAK, gen_bot + 2, ST_SOL))
    s.append(_arrow(X_STRONG, gen_bot, X_STRONG, abs_top - 2, ST_SOL, dash=True))
    s.append(_box(B["shx"], "SHX", [f"f {_num(r,'circulation_ratio','{:.1f}')}"], FILL["shx"]))
    py = (abs_top + B["shx"][1] + B["shx"][3]) / 2
    s.append(f'<circle cx="{X_WEAK}" cy="{py}" r="8" fill="white" stroke="{PURPLE}" stroke-width="1.6"/>')
    s.append(_txt(X_WEAK, py + 3, "P", 9, PURPLE, "middle", bold=True))
    s.append(_txt(X_WEAK - 6, py - 12, "weak", 8.5, PURPLE, "end", bold=True))
    s.append(_txt(X_WEAK - 6, py - 1, f"{_num(r,'x_weak_pct','{:.1f}')}%", 8.5, PURPLE, "end"))
    s.append(f'<rect x="{X_STRONG-4}" y="{py-3}" width="8" height="6" fill="white" stroke="{PURPLE}" stroke-width="1.2"/>')
    s.append(_txt(X_STRONG + 8, py - 12, "strong", 8.5, PURPLE, "start", bold=True))
    s.append(_txt(X_STRONG + 8, py - 1, f"{_num(r,'x_strong_pct','{:.1f}')}%", 8.5, PURPLE, "start"))

    # refrigerant loop
    s.append(_arrow(gx + gw, gy + 18, B["cond"][0], gy + 18, ST_REF))
    s.append(_txt((gx + gw + B["cond"][0]) / 2, gy + 12, "refrig. vapour", 8.5, BLUE, "middle"))
    cxv = B["cond"][0] + B["cond"][2] / 2
    s.append(_arrow(cxv, B["cond"][1] + B["cond"][3], cxv, B["evap"][1], ST_REF, dash=True))
    s.append(_txt(cxv + 12, (B["cond"][1] + B["evap"][1]) / 2, "liquid", 8, BLUE, "start"))
    s.append(_txt(cxv + 12, (B["cond"][1] + B["evap"][1]) / 2 + 11, "(throttle)", 7.5, GREY, "start"))
    s.append(_arrow(B["evap"][0], ay + 30, ax + aw, ay + 30, ST_REF))
    s.append(_txt((B["evap"][0] + ax + aw) / 2, ay + 24, "refrig. vapour", 8.5, BLUE, "middle"))

    # heat source / burner
    hx = gx + gw / 2
    s.append(_arrow(hx, gy - 26, hx, gy, ST_HEAT))
    src = (f"waste heat {_num(r,'q_source_avail_kw')} kW" if capped else
           f"heat source {_num(r,'t_gen_c')} °C (drive)")
    s.append(_txt(hx + 10, gy - 16, src, 8.5, ORANGE, "start"))
    if show_burner:
        s.append(_box(B["burn"], "Backup burner",
                      [(f"NG {fuel:.1f} Nm³/h" if (burner_on and fuel > 0) else
                        ("burner OFF" if not burner_on else "NG 0.0 Nm³/h")),
                       (f"+{_num(r,'burner_heat_kw')} kW" if burner_on else "make-up gas")],
                      FILL["burn"]))
        s.append(_arrow(B["burn"][0] + B["burn"][2], gy + 30, gx, gy + 30, ST_HEAT))

    # cooling water
    s.append(_arrow(ax - 44, ay + ah / 2, ax, ay + ah / 2, ST_CW))
    s.append(_txt(ax - 46, ay + ah / 2 - 5, "CW in", 8, ST_CW, "end"))
    s.append(_arrow(cxv, B["cond"][1] - 22, cxv, B["cond"][1], ST_CW))
    s.append(_txt(cxv - 8, B["cond"][1] - 12, "CW", 8, ST_CW, "end"))
    # chilled water
    ex = B["evap"][0] + B["evap"][2]
    s.append(_arrow(ex + 56, B["evap"][1] + 20, ex, B["evap"][1] + 20, ST_CHW))
    s.append(_txt(W - 6, B["evap"][1] + 14, "CHW return", 8, TEAL, "end"))
    s.append(_arrow(ex, B["evap"][1] + 44, ex + 56, B["evap"][1] + 44, ST_CHW))
    s.append(_txt(W - 6, B["evap"][1] + 56, "CHW supply", 8, TEAL, "end"))

    _footer(s, r, W, 446)
    s.append("</svg>")
    return "".join(s)


# ── double-effect ────────────────────────────────────────────────────────────
def _render_double(r):
    W, H = 790, 540
    stg = r.get("stage") or {}
    burner_on = bool(r.get("burner_on")); capped = bool(r.get("source_capped"))
    fuel = r.get("fuel_nm3h", 0.0) or 0.0
    show_burner = burner_on or capped
    pl = _num(r, "p_low_kpa", "{:.2f}")
    p_htg = _num(stg, "htg_p_kpa", "{:.1f}")
    p_mid = _num(stg, "ltg_p_kpa", "{:.1f}")

    B = {"htg": (185, 74, 170, 56), "ltg": (185, 244, 170, 56),
         "abs": (185, 414, 170, 56), "cond": (575, 244, 170, 56),  # cond level = LTG
         "evap": (575, 414, 170, 56), "hthe": (220, 158, 76, 38),
         "lthe": (220, 330, 76, 38), "burn": (14, 74, 150, 56)}
    XW, XS = 222, 318    # weak (up) / strong (down) solution lines
    s = _open(W, H, {ST_REF, ST_SOL, ST_CHW, ST_CW, ST_HEAT, ST_INT})
    _header(s, r, W)

    hx0, hy0, hw, hh = B["htg"]; ax, ay, aw, ah = B["abs"]

    # solution lines first (so boxes overlay and the streams read as through them)
    s.append(_arrow(XW, ay, XW, hy0 + hh + 2, ST_SOL))                 # weak up
    s.append(_arrow(XS, hy0 + hh, XS, ay - 2, ST_SOL, dash=True))      # strong down

    # vessels + solution HXs
    s.append(_box(B["htg"], "HTG  (high-temp gen)",
                  [f"Q_gen {_num(r,'q_gen_kw')} kW", _tp(_num(stg, "htg_t_c"), p_htg)], FILL["htg"]))
    s.append(_box(B["ltg"], "LTG  (low-temp gen)",
                  ["driven by HTG vapour", _tp(_num(stg, "ltg_t_c"), p_mid)], FILL["ltg"]))
    s.append(_box(B["abs"], "Absorber",
                  [f"Q_abs {_num(r,'q_abs_kw')} kW", _tp(_num(r, "t_abs_c"), pl)], FILL["abs"]))
    s.append(_box(B["cond"], "Condenser",
                  [f"Q_cond {_num(r,'q_cond_kw')} kW", _tp(_num(r, "t_cond_c"), p_mid)], FILL["cond"]))
    s.append(_box(B["evap"], "Evaporator",
                  [f"Q_evap {_num(r,'q_evap_kw')} kW", _tp(_num(r, "t_evap_c"), pl)], FILL["evap"]))
    s.append(_box(B["hthe"], "HTHE", [], FILL["shx"]))
    s.append(_box(B["lthe"], "LTHE", [], FILL["shx"]))

    # solution labels + pump
    py = (ay + B["lthe"][1] + B["lthe"][3]) / 2
    s.append(f'<circle cx="{XW}" cy="{py}" r="8" fill="white" stroke="{PURPLE}" stroke-width="1.6"/>')
    s.append(_txt(XW, py + 3, "P", 9, PURPLE, "middle", bold=True))
    s.append(_txt(XW - 12, py - 4, "weak", 8.5, PURPLE, "end", bold=True))
    s.append(_txt(XW - 12, py + 7, f"{_num(r,'x_weak_pct','{:.1f}')}%", 8.5, PURPLE, "end"))
    s.append(_txt(XS + 10, py - 4, "strong", 8.5, PURPLE, "start", bold=True))
    s.append(_txt(XS + 10, py + 7, f"{_num(r,'x_strong_pct','{:.1f}')}%", 8.5, PURPLE, "start"))

    # internal heat recovery: HTG vapour -> LTG (the double-effect signature)
    xi = hx0 + hw + 18
    s.append(_arrow(hx0 + hw, hy0 + 20, xi, hy0 + 20, ST_INT))
    s.append(f'<line x1="{xi}" y1="{hy0+20}" x2="{xi}" y2="{B["ltg"][1]+18}" '
             f'stroke="{ST_INT}" stroke-width="2"/>')
    s.append(_arrow(xi, B["ltg"][1] + 18, B["ltg"][0] + B["ltg"][2], B["ltg"][1] + 18, ST_INT))
    s.append(_txt(xi + 6, (hy0 + B["ltg"][1]) / 2 + 6, "HTG vapour", 8, ST_INT, "start", bold=True))
    s.append(_txt(xi + 6, (hy0 + B["ltg"][1]) / 2 + 17, f"drives LTG  {_num(stg,'q_internal_kw')} kW",
                  8, ST_INT, "start"))
    s.append(_txt(xi + 6, (hy0 + B["ltg"][1]) / 2 + 28, f"(cond. {_num(stg,'int_cond_t_c')} °C)",
                  7.5, GREY, "start"))

    # refrigerant: LTG vapour + HTG condensate -> condenser ; condenser->evap ; evap->abs
    s.append(_arrow(B["ltg"][0] + B["ltg"][2], B["ltg"][1] + 30, B["cond"][0], B["cond"][1] + 30, ST_REF))
    s.append(_txt((B["ltg"][0] + B["ltg"][2] + B["cond"][0]) / 2, B["cond"][1] + 22,
                  "refrig. vapour", 8.5, BLUE, "middle"))
    cxv = B["cond"][0] + B["cond"][2] / 2
    s.append(_arrow(cxv, B["cond"][1] + B["cond"][3], cxv, B["evap"][1], ST_REF, dash=True))
    s.append(_txt(cxv + 12, (B["cond"][1] + B["evap"][1]) / 2, "liquid", 8, BLUE, "start"))
    s.append(_txt(cxv + 12, (B["cond"][1] + B["evap"][1]) / 2 + 11, "(throttle)", 7.5, GREY, "start"))
    s.append(_arrow(B["evap"][0], ay + 30, ax + aw, ay + 30, ST_REF))
    s.append(_txt((B["evap"][0] + ax + aw) / 2, ay + 24, "refrig. vapour", 8.5, BLUE, "middle"))

    # heat source / burner into HTG
    hcx = hx0 + hw / 2
    s.append(_arrow(hcx, hy0 - 26, hcx, hy0, ST_HEAT))
    src = (f"waste heat {_num(r,'q_source_avail_kw')} kW" if capped else
           f"heat source {_num(stg,'htg_t_c')} °C (drive)")
    s.append(_txt(hcx + 10, hy0 - 16, src, 8.5, ORANGE, "start"))
    if show_burner:
        s.append(_box(B["burn"], "Backup burner",
                      [(f"NG {fuel:.1f} Nm³/h" if (burner_on and fuel > 0) else
                        ("burner OFF" if not burner_on else "NG 0.0 Nm³/h")),
                       (f"+{_num(r,'burner_heat_kw')} kW" if burner_on else "make-up gas")],
                      FILL["burn"]))
        s.append(_arrow(B["burn"][0] + B["burn"][2], hy0 + 28, hx0, hy0 + 28, ST_HEAT))

    # cooling water + chilled water
    s.append(_arrow(ax - 44, ay + ah / 2, ax, ay + ah / 2, ST_CW))
    s.append(_txt(ax - 46, ay + ah / 2 - 5, "CW in", 8, ST_CW, "end"))
    s.append(_arrow(cxv, B["cond"][1] - 22, cxv, B["cond"][1], ST_CW))
    s.append(_txt(cxv - 8, B["cond"][1] - 12, "CW", 8, ST_CW, "end"))
    ex = B["evap"][0] + B["evap"][2]
    s.append(_arrow(ex + 56, B["evap"][1] + 20, ex, B["evap"][1] + 20, ST_CHW))
    s.append(_txt(W - 6, B["evap"][1] + 14, "CHW return", 8, TEAL, "end"))
    s.append(_arrow(ex, B["evap"][1] + 44, ex + 56, B["evap"][1] + 44, ST_CHW))
    s.append(_txt(W - 6, B["evap"][1] + 56, "CHW supply", 8, TEAL, "end"))

    # three-pressure-level legend
    s.append(_txt(14, H - 70, "Pressure levels:", 8.5, GREY, "start", bold=True))
    s.append(_txt(14, H - 58, f"HTG ~{p_htg} kPa  >  LTG = cond ~{p_mid} kPa  >  "
                  f"evap = abs ~{pl} kPa", 8.5, INK, "start"))

    _footer(s, r, W, H - 22)
    s.append("</svg>")
    return "".join(s)


def libr_pfd_svg(engine, r: dict) -> str:
    return _render_double(r) if r.get("effect") == "double" else _render_single(r)
