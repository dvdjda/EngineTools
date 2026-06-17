"""
Nexa process toolkit - generic UI with a tool-request box.

Pick a system and its inputs/results/chart/downloads build themselves from the
contract. "Request a tool" captures a description, records it, and scaffolds a
conforming DRAFT that appears in the dropdown badged "draft" - the assistant
fills its logic, sandboxed, and it stays draft until you promote it.

Run:
    pip install dash CoolProp scipy matplotlib reportlab openpyxl python-pptx cairosvg
    python -m nexa_toolkit.app.app      # then open http://127.0.0.1:8050
"""
import base64
import json
import math
import os
import tempfile
import time

import dash
from dash import dcc, html, Input, Output, State, ALL, MATCH, ctx, no_update

import nexa_toolkit.engines  # noqa: F401  (registers the systems)
from nexa_toolkit.framework import list_engines, get, REGISTRY
from nexa_toolkit.framework.builder import save_request, scaffold_tool, _slug, load_kinds, add_kind
from nexa_toolkit.framework import datasets as _datasets
from nexa_toolkit.reporting.generic_report import (
    build_chart, build_excel, build_pdf, build_pptx)
from nexa_toolkit.reporting.study_export import study_to_csv, study_to_xlsx
from nexablock.studies import (
    ParameterSweep, OneAtATimeSensitivity, ScenarioRunner,
    tornado_chart, sweep_chart, scenarios_chart,
    sweep_contour, tornado_multi_chart)
import dataclasses as _dc
import datetime as _dt
import pathlib as _pl
import pickle as _pk
try:
    from nexa_toolkit.dwsim_export import build_flowsheet as _dwsim_build_flowsheet
except Exception:
    _dwsim_build_flowsheet = None

NAVY = "#2E4E7E"; TEAL = "#2BB6A3"; LIGHT = "#EAF0F8"; GREY = "#5b6675"
INK = "#22303F"; BG = "#f4f7fb"; LINE = "#dbe2ee"; RED = "#C0392B"
BASIS = {"verified": "#2E7D4E", "screening": "#B26A00", "input": "#5b6675", "unverified": RED}

# AI model selector — comprehensive Anthropic Claude model list.
# Static so the dropdown populates without an API call; if the user wants
# a model that's launched after this list was written, they can type its
# ID into the model dropdown (it's `searchable` so freeform values work).
AI_MODELS = [
    # Claude 4 family
    {"label": "Claude Opus 4.7 (1M context)",       "value": "claude-opus-4-7"},
    {"label": "Claude Opus 4.6",                    "value": "claude-opus-4-6"},
    {"label": "Claude Opus 4.5",                    "value": "claude-opus-4-5"},
    {"label": "Claude Opus 4.1",                    "value": "claude-opus-4-1"},
    {"label": "Claude Sonnet 4.6",                  "value": "claude-sonnet-4-6"},
    {"label": "Claude Sonnet 4.5",                  "value": "claude-sonnet-4-5"},
    {"label": "Claude Haiku 4.5 (fast)",            "value": "claude-haiku-4-5"},
    # Claude 3.7 family
    {"label": "Claude 3.7 Sonnet (latest)",         "value": "claude-3-7-sonnet-latest"},
    {"label": "Claude 3.7 Sonnet (2025-02-19)",     "value": "claude-3-7-sonnet-20250219"},
    # Claude 3.5 family
    {"label": "Claude 3.5 Sonnet v2 (latest)",      "value": "claude-3-5-sonnet-latest"},
    {"label": "Claude 3.5 Sonnet v2 (2024-10-22)",  "value": "claude-3-5-sonnet-20241022"},
    {"label": "Claude 3.5 Sonnet v1 (2024-06-20)",  "value": "claude-3-5-sonnet-20240620"},
    {"label": "Claude 3.5 Haiku (latest)",          "value": "claude-3-5-haiku-latest"},
    {"label": "Claude 3.5 Haiku (2024-10-22)",      "value": "claude-3-5-haiku-20241022"},
    # Claude 3 family
    {"label": "Claude 3 Opus (latest)",             "value": "claude-3-opus-latest"},
    {"label": "Claude 3 Opus (2024-02-29)",         "value": "claude-3-opus-20240229"},
    {"label": "Claude 3 Sonnet (2024-02-29)",       "value": "claude-3-sonnet-20240229"},
    {"label": "Claude 3 Haiku (2024-03-07)",        "value": "claude-3-haiku-20240307"},
]
# Default to a smart-and-capable Opus when first opened; user can pick any.
AI_MODEL_DEFAULT = "claude-sonnet-4-6"

CARD = {"background": "white", "border": f"1px solid {LINE}", "borderRadius": "10px",
        "padding": "18px 20px", "boxShadow": "0 1px 3px rgba(20,40,80,0.06)"}

# suppress_callback_exceptions: the inputs panel (#inputs) is rebuilt per engine,
# so components like the GT-load-kW twin only exist for some engines. Relax the
# initial-layout validation so callbacks referencing them don't error when an
# engine without them is selected.
app = dash.Dash(__name__, title="EngineTools", suppress_callback_exceptions=True)
server = app.server


# ── Markdown docs Flask route ────────────────────────────────────────────────
# Serves docs/*.md as styled HTML in a new browser tab. Header bar matches
# the app's navy theme; tables / code blocks / blockquotes styled to match.

_DOCS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "docs"))

_DOC_CSS = """
body { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
       max-width: 920px; margin: 0 auto 60px auto; padding: 0 24px;
       line-height: 1.65; color: #22303F; font-size: 15px; }
.header { background: #2E4E7E; color: white; padding: 18px 28px;
          margin: 0 -24px 28px -24px; }
.header .title { font-size: 14px; font-weight: 600; }
.header .crumb { font-size: 13px; opacity: 0.85; }
h1 { color: #2E4E7E; border-bottom: 2px solid #2E4E7E; padding-bottom: 8px;
     margin-top: 36px; font-size: 28px; }
h2 { color: #2E4E7E; border-bottom: 1px solid #dbe2ee; padding-bottom: 4px;
     margin-top: 28px; font-size: 22px; }
h3 { color: #2E4E7E; margin-top: 22px; font-size: 17px; }
code { background: #EAF0F8; padding: 2px 6px; border-radius: 4px;
       font-size: 92%; color: #22303F; font-family: 'SF Mono', Consolas, monospace; }
pre { background: #f4f7fb; padding: 14px 18px; border-radius: 6px;
      overflow-x: auto; border: 1px solid #dbe2ee; }
pre code { background: none; padding: 0; font-size: 13px; }
table { border-collapse: collapse; width: 100%; margin: 18px 0; font-size: 14px; }
th, td { border: 1px solid #dbe2ee; padding: 8px 12px; text-align: left;
         vertical-align: top; }
th { background: #EAF0F8; color: #2E4E7E; font-weight: 700; }
blockquote { border-left: 4px solid #2BB6A3; padding: 6px 16px;
             background: #f4f7fb; color: #5b6675; margin: 18px 0; }
a { color: #2BB6A3; text-decoration: none; }
a:hover { text-decoration: underline; }
hr { border: none; border-top: 1px solid #dbe2ee; margin: 28px 0; }
ul, ol { padding-left: 24px; }
li { margin-bottom: 4px; }
.toc { background: #f4f7fb; border: 1px solid #dbe2ee; border-radius: 6px;
       padding: 12px 18px; margin: 12px 0 24px 0; font-size: 14px; }
"""


@server.route("/docs/<path:filename>")
def serve_doc(filename):
    """Serve docs/*.md as styled HTML in a new tab. Only files actually in
    docs/ are servable; path-traversal attempts get 404."""
    from flask import abort, Response
    if not filename.endswith(".md"):
        abort(404)
    path = os.path.normpath(os.path.join(_DOCS_DIR, filename))
    if not path.startswith(_DOCS_DIR) or not os.path.isfile(path):
        abort(404)
    with open(path, encoding="utf-8") as f:
        md_text = f.read()
    try:
        import markdown as _md
        html_body = _md.markdown(
            md_text,
            extensions=["tables", "fenced_code", "toc", "sane_lists"],
            extension_configs={"toc": {"toc_class": "toc"}},
        )
    except ImportError:
        html_body = f"<pre>{md_text}</pre>"
    page = (f"<!DOCTYPE html><html><head><meta charset='utf-8'>"
            f"<title>{filename} — EngineTools docs</title>"
            f"<style>{_DOC_CSS}</style></head><body>"
            f"<div class='header'>"
            f"<div class='title'>EngineTools Documentation</div>"
            f"<div class='crumb'>docs / {filename}</div>"
            f"</div>"
            f"{html_body}"
            f"</body></html>")
    return Response(page, mimetype="text/html")


def build_options():
    opts = []
    for key, e in REGISTRY.items():
        label = e.name + ("  -  draft" if e.status == "draft" else "")
        opts.append({"label": label, "value": key})
    return opts


_INPUT_STYLE = {"width": "100%", "padding": "8px 10px", "border": f"1px solid {LINE}",
                "borderRadius": "6px", "fontSize": "14px", "boxSizing": "border-box"}


def _dataset_options(engine_key):
    """Dropdown options for the datasets saved under this engine."""
    return [{"label": n, "value": n} for n in _datasets.list_datasets(engine_key)]


def _dataset_sysin_values(ids, dataset):
    """Ordered list of values to push into the `sysin` number inputs, aligned to
    `ids` (the ALL-pattern id list). Keys absent from the dataset stay put
    (`no_update`) so a dataset saved before a new input was added still loads."""
    return [dataset[cid["key"]] if cid["key"] in dataset else no_update
            for cid in ids]


def _dataset_mat_values(mat_ids, dataset, engine):
    """Ordered values for the `sysin-mat` dropdowns (choice inputs only) so the
    visible selector reflects a loaded dataset. A value that matches one of the
    input's choices selects it; anything else shows the Custom… box."""
    choices_by_key = {s.key: (s.choices or {}) for s in engine.inputs if s.choices}
    out = []
    for cid in mat_ids:
        k = cid["key"]
        if k not in dataset:
            out.append(no_update); continue
        val = dataset[k]
        ch = choices_by_key.get(k, {})
        try:
            matches = any(abs(float(cv) - float(val)) < 1e-9 for cv in ch.values())
        except (TypeError, ValueError):
            matches = False
        out.append(val if matches else "__custom__")
    return out


def _gt_derated_kW(p_rated_kW, t_ambient_C):
    """Ambient-derated GT capacity in kW — same law as nexablock GasTurbine:
    derate = max(0.50, 1 − 0.007·max(0, T_amb−15°C)). Used to convert between
    the 'GT load (%)' and 'GT load (kW)' twin fields (kW = derated × load%)."""
    derate = max(0.50, 1.0 - 0.007 * max(0.0, float(t_ambient_C) - 15.0))
    return float(p_rated_kW) * derate


# Engines that expose all three of these get the linked GT-load %↔kW twin field.
_GT_LOAD_LINK_KEYS = ("load_pct", "p_rated_kW", "t_ambient_C")


def _has_gt_load_link(engine):
    keys = {s.key for s in engine.inputs}
    return all(k in keys for k in _GT_LOAD_LINK_KEYS)


def _effective_defaults(engine):
    """The engine's effective defaults: the user-saved 'Default' dataset (if any,
    persisted per-engine) layered over the code InputSpec defaults. This is what
    the panel pre-fills on open and what Reset restores. Keys no longer valid for
    the engine are dropped so a stale saved Default can't inject unknown inputs."""
    base = engine.defaults()
    override = _datasets.get_default_params(engine.key) or {}
    valid = {s.key for s in engine.inputs}
    base.update({k: v for k, v in override.items() if k in valid})
    return base


def input_fields(engine):
    out = []
    linked_load = _has_gt_load_link(engine)
    d = _effective_defaults(engine)
    for s in engine.inputs:
        # Skip the "(unit)" suffix for dimensionless inputs so labels
        # like "Operating mode" don't read as "Operating mode  (-)".
        label_txt = s.label if s.unit in ("", "-") else f"{s.label}  ({s.unit})"
        lbl = html.Label(label_txt,
                         style={"fontSize": "13px", "color": GREY,
                                "display": "block", "marginBottom": "4px"})
        if s.choices:
            # Legacy "mm" suffix was for material-thickness choices; the
            # modern path just labels options by their name. Custom-value
            # entry is also legacy — only offer it when the unit hints
            # at a continuous quantity (i.e. not "-" or empty).
            opts = [{"label": str(name), "value": val}
                    for name, val in s.choices.items()]
            if s.unit not in ("", "-"):
                opts.append({"label": "Custom…", "value": "__custom__"})
            # find if default matches a choice; if not, show custom input
            default_in_choices = any(abs(float(o["value"]) - s.default) < 1e-9
                                     for o in opts if o["value"] != "__custom__")
            drop_val  = s.default if default_in_choices else "__custom__"
            num_style = dict(_INPUT_STYLE, **({"display": "none"} if default_in_choices
                                              else {"display": "block"}))
            out.append(html.Div([
                lbl,
                dcc.Dropdown(id={"type": "sysin-mat", "key": s.key},
                             options=opts, value=drop_val, clearable=False,
                             style={"marginBottom": "4px", "fontSize": "13px"}),
                dcc.Input(id={"type": "sysin", "key": s.key}, type="number",
                          value=s.default, style=num_style),
            ], style={"marginBottom": "12px"}))
        else:
            out.append(html.Div([
                lbl,
                dcc.Input(id={"type": "sysin", "key": s.key}, type="number",
                          value=s.default, style=_INPUT_STYLE),
            ], style={"marginBottom": "12px"}))
            # GT-load twin: render "GT load (kW)" directly under "GT load (%)".
            # Not a `sysin` — solve reads load_pct only; this is a UI convenience
            # synced both ways by _sync_gt_load. kW = derated capacity × load%.
            if linked_load and s.key == "load_pct":
                kw_default = round(
                    _gt_derated_kW(d["p_rated_kW"], d["t_ambient_C"])
                    * float(d["load_pct"]) / 100.0, 1)
                out.append(html.Div([
                    html.Label("GT load  (kW)",
                               style={"fontSize": "13px", "color": GREY,
                                      "display": "block", "marginBottom": "4px"}),
                    dcc.Input(id="gt-load-kw", type="number",
                              value=kw_default, style=_INPUT_STYLE),
                    html.Div("= derated capacity × load%  ·  re-derives with "
                             "rated power & ambient",
                             style={"fontSize": "11px", "color": GREY,
                                    "fontStyle": "italic", "marginTop": "3px"}),
                ], style={"marginBottom": "12px"}))
    return out


def highlight_cards(engine, r):
    cards = [html.Div([
        html.Div(o.label, style={"fontSize": "12px", "color": GREY, "marginBottom": "4px"}),
        html.Div(f"{o.text()} {o.unit}", style={"fontSize": "24px", "fontWeight": "700", "color": NAVY}),
    ], style={**CARD, "flex": "1", "padding": "14px 16px"}) for o in engine.highlights(r)]
    return html.Div(cards, style={"display": "flex", "gap": "14px", "marginBottom": "16px"})


def _convergence_status(r):
    """Return SolvedSystem.convergence if r['solved'] has one, else None."""
    solved = r.get("solved") if isinstance(r, dict) else None
    return getattr(solved, "convergence", None) if solved is not None else None


def _feasibility_status(r):
    """Return r['feasibility'] (FeasibilityStatus) if engine surfaces it."""
    return r.get("feasibility") if isinstance(r, dict) else None


def _audit_status(r):
    """Return r['audit'] (AuditStatus) if engine surfaces it."""
    return r.get("audit") if isinstance(r, dict) else None


def audit_card(r):
    """Audit status card. Green: N/N passed. Red: lists failed checks."""
    a = _audit_status(r)
    if a is None:
        return html.Div()
    GREEN = "#2E7D4E"
    n  = len(a.checks); ok = sum(1 for c in a.checks if c.passed)
    if a.passed:
        return html.Div([
            html.Span("✓ ", style={"fontWeight": "800", "fontSize": "16px",
                                    "color": GREEN}),
            html.Span("Audit", style={"fontWeight": "700", "fontSize": "14px",
                                       "color": GREEN, "marginRight": "10px"}),
            html.Span(f"{ok}/{n} checks passed",
                      style={"fontSize": "13px", "color": INK}),
        ], style={
            "background": "#EAF7EE", "border": f"1px solid {GREEN}",
            "borderRadius": "8px", "padding": "10px 14px",
            "marginBottom": "14px",
        })
    failed = a.failed()
    items = [html.Li(f"[{c.category}] {c.name} — {c.detail}",
                      style={"fontSize": "11px", "marginBottom": "3px"})
             for c in failed]
    return html.Div([
        html.Div([
            html.Span("⚠ ", style={"fontWeight": "800", "fontSize": "18px"}),
            html.Span("AUDIT FAILED",
                      style={"fontWeight": "800", "fontSize": "15px",
                             "letterSpacing": "0.5px"}),
        ], style={"marginBottom": "6px"}),
        html.Div(f"{ok}/{n} passed, {len(failed)} failed:",
                 style={"fontSize": "13px", "fontWeight": "700",
                        "marginBottom": "6px"}),
        html.Ul(items, style={"marginTop": "4px", "marginBottom": "4px",
                               "paddingLeft": "20px"}),
        html.Div("Affected KPIs are flagged as 'unverified' in the table below.",
                 style={"fontSize": "11px", "fontStyle": "italic",
                        "opacity": "0.9"}),
    ], style={
        "background": RED, "color": "white",
        "borderRadius": "8px", "padding": "12px 16px",
        "marginBottom": "14px",
    })


def _balance_card(b):
    """Single resource-balance card. Neutral white background by default;
    audit is the authoritative pass/fail signal so this card never claims
    ✓ green. Goes red only when there's a real engineering issue (deficit
    or, for power closure, excess that has nowhere to go)."""
    summary = (f"Supply {b.supply:,.0f} {b.unit} · "
               f"Demand {b.demand:,.0f} {b.unit} · "
               f"Balance {b.balance:+,.0f} {b.unit}")

    if b.feasible:
        # Neutral card — informational, no ✓ sign.
        return html.Div([
            html.Div([
                html.Span(f"{b.resource} balance",
                          style={"fontWeight": "700", "fontSize": "14px",
                                 "color": NAVY, "marginRight": "10px"}),
                html.Span(summary, style={"fontSize": "13px", "color": INK}),
            ]),
            html.Div(f"Assumption: {b.assumption}",
                     style={"fontSize": "11px", "color": GREY,
                            "marginTop": "4px", "fontStyle": "italic"}),
        ], style={
            "background": "white", "border": f"1px solid {LINE}",
            "borderRadius": "8px", "padding": "10px 14px",
            "marginBottom": "10px",
        })

    # Failure mode — work out the right verb. Power closure can fail with
    # EXCESS (no sink in island) or DEFICIT (supply < demand).
    if b.resource == "Power" and b.balance > 0:
        title = "POWER BUS DID NOT CLOSE — excess electrical"
        body  = (f"GT actual {b.supply:,.0f} {b.unit} > demand "
                  f"{b.demand:,.0f} {b.unit}, residual "
                  f"+{abs(b.balance):,.0f} {b.unit}. In island mode this "
                  f"means the flowsheet didn't converge: there's no sink "
                  f"for the surplus.")
    else:
        title = f"{b.resource.upper()} DEFICIT"
        body  = (f"demand {b.demand:,.0f} {b.unit} > supply "
                  f"{b.supply:,.0f} {b.unit}, shortfall "
                  f"{b.shortfall:,.0f} {b.unit}")
    return html.Div([
        html.Div([
            html.Span("⚠ ", style={"fontWeight": "800", "fontSize": "18px"}),
            html.Span(title,
                      style={"fontWeight": "800", "fontSize": "15px",
                             "letterSpacing": "0.5px"}),
        ], style={"marginBottom": "6px"}),
        html.Div(body,
                 style={"fontSize": "13px", "fontWeight": "700", "marginBottom": "4px"}),
        html.Div(f"Assumption: {b.assumption}",
                 style={"fontSize": "11px", "opacity": "0.85"}),
    ], style={
        "background": RED, "color": "white",
        "borderRadius": "8px", "padding": "12px 16px",
        "marginBottom": "10px",
    })


def feasibility_card(r):
    """One card per resource balance (power, cooling, ...). Empty Div if the
    engine doesn't surface feasibility (v1 path)."""
    feas = _feasibility_status(r)
    if feas is None or not getattr(feas, "balances", None):
        return html.Div()
    return html.Div(
        [_balance_card(b) for b in feas.balances],
        style={"marginBottom": "4px"},
    )


def convergence_card(r):
    """Dedicated convergence-status card shown after every Run. Renders nothing
    for engines that don't return a SolvedSystem (v1 path) so layout is stable."""
    from nexablock.core.convergence import convergence_summary
    conv = _convergence_status(r)
    if conv is None:
        return html.Div()
    text, ok = convergence_summary(conv)
    GREEN = "#2E7D4E"

    if ok:
        # Single-row green card, full width.
        return html.Div([
            html.Span("✓ ", style={"fontWeight": "800", "fontSize": "16px", "color": GREEN}),
            html.Span("Converged",
                      style={"fontWeight": "700", "fontSize": "14px", "color": GREEN,
                             "marginRight": "10px"}),
            html.Span(text, style={"fontSize": "13px", "color": INK}),
        ], style={
            "background": "#EAF7EE", "border": f"1px solid {GREEN}",
            "borderRadius": "8px", "padding": "10px 14px",
            "marginBottom": "14px",
            "display": "flex", "alignItems": "center", "flexWrap": "wrap",
        })

    # Non-converged: louder, multi-line, names the loop and the reason.
    bad = next(L for L in conv.loops if not L.converged)
    return html.Div([
        html.Div([
            html.Span("⚠ ", style={"fontWeight": "800", "fontSize": "18px"}),
            html.Span("NOT CONVERGED",
                      style={"fontWeight": "800", "fontSize": "15px", "letterSpacing": "0.5px"}),
        ], style={"marginBottom": "6px"}),
        html.Div(text, style={"fontSize": "13px", "fontWeight": "600", "marginBottom": "4px"}),
        html.Div(f"Reason: {bad.reason or 'unknown'}",
                 style={"fontSize": "12px", "opacity": "0.95", "marginBottom": "4px"}),
        html.Div("KPIs below may be unreliable.",
                 style={"fontSize": "12px", "fontStyle": "italic", "opacity": "0.9"}),
    ], style={
        "background": RED, "color": "white",
        "borderRadius": "8px", "padding": "12px 16px",
        "marginBottom": "14px",
    })


def results_table(engine, r):
    head = html.Tr([html.Th(h, style={"textAlign": "left" if h == "Quantity" else "center",
                                       "padding": "8px 10px", "color": NAVY, "fontSize": "13px",
                                       "borderBottom": f"2px solid {LIGHT}"})
                    for h in ("Quantity", "Value", "Unit", "Basis")])
    rows = [head]
    conv  = _convergence_status(r)
    feas  = _feasibility_status(r)
    audit = _audit_status(r)
    # Global flip — convergence / feasibility / generic audit (P12/P13) failures
    # invalidate every row irrespective of per-check coverage.
    generic_audit_fail = (audit is not None and bool(audit.generic_failures()))
    global_fail = (
        (conv is not None and not conv.converged)
        or (feas is not None and not feas.feasible)
        or generic_audit_fail
    )
    for i, o in enumerate(engine.outputs(r)):
        bg = "white" if i % 2 == 0 else LIGHT
        if global_fail:
            display_basis = "unverified"
        elif audit is None:
            display_basis = o.basis
        else:
            cov = audit.coverage_for(o.label)
            if   cov == "failed":  display_basis = "unverified"
            elif cov == "passed":  display_basis = o.basis
            else:                  display_basis = "screening"
        rows.append(html.Tr([
            html.Td(o.label, style={"padding": "7px 10px", "fontSize": "13px", "color": INK}),
            html.Td(o.text(), style={"padding": "7px 10px", "fontSize": "13px", "textAlign": "center"}),
            html.Td(o.unit, style={"padding": "7px 10px", "fontSize": "13px", "textAlign": "center", "color": GREY}),
            html.Td(display_basis, style={"padding": "7px 10px", "fontSize": "12px", "textAlign": "center",
                                    "color": BASIS.get(display_basis, GREY)}),
        ], style={"background": bg}))
    return html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"})


def chart_src(engine, r):
    fmt = getattr(engine, "chart_format", "png")
    d = tempfile.mkdtemp(); p = os.path.join(d, f"c.{fmt}")
    build_chart(engine, r, p)
    mime = "image/svg+xml" if fmt == "svg" else "image/png"
    return f"data:{mime};base64," + base64.b64encode(open(p, "rb").read()).decode()


def build_smart_section(engine, v, r):
    """Convergence alerts + input summary + method notes. Generic — reads the contract."""
    # find margin outputs ({:+ format convention)
    margin_outs = [(o.label, o.value, o.unit) for o in engine.outputs(r)
                   if o.fmt.startswith("{:+")]
    bad_vals = [o.label for o in engine.outputs(r)
                if isinstance(o.value, float) and not math.isfinite(o.value)]

    parts = []

    # --- convergence block ---
    if margin_outs or bad_vals:
        items = []
        all_ok = True
        for label, value, unit in margin_outs:
            fin = math.isfinite(value) if isinstance(value, float) else True
            if not fin or value < 0:
                col, icon, all_ok = RED, "\u2717", False
                tail = "non-finite — check inputs." if not fin else f"{value:+.0f} {unit}  \u2014  deficit, does not converge."
            elif value == 0:
                col, icon = "#B26A00", "\u26a0"
                tail = f"exactly zero  \u2014  system at its limit."
            else:
                col, icon = "#2E7D4E", "\u2713"
                tail = f"{value:+.0f} {unit}  \u2014  OK."
            items.append(html.Div([
                html.Span(f"{icon}  ", style={"fontWeight": "700"}),
                html.Span(f"{label}: {tail}"),
            ], style={"color": col, "fontSize": "13px", "padding": "5px 0",
                      "borderBottom": f"1px solid {LINE}"}))
        for label in bad_vals:
            items.append(html.Div([
                html.Span("\u2717  ", style={"fontWeight": "700"}),
                html.Span(f"{label}: non-finite value — check for zero inputs."),
            ], style={"color": RED, "fontSize": "13px", "padding": "5px 0",
                      "borderBottom": f"1px solid {LINE}"}))
            all_ok = False
        status_msg = "All balances close \u2014 system converges." if all_ok else \
                     "One or more balances do not close \u2014 see items below."
        parts.append(html.Div([
            html.Div([
                html.Span("Convergence  ",
                          style={"fontWeight": "700", "color": NAVY, "fontSize": "13px"}),
                html.Span(status_msg,
                          style={"fontSize": "12px",
                                 "color": "#2E7D4E" if all_ok else RED}),
            ], style={"marginBottom": "8px"}),
            html.Div(items),
        ], style={"marginBottom": "14px"}))

    # --- inputs used ---
    # If the engine returns a SolvedSystem with a resolved control state
    # (gt_system_v2 in auto modes), hide the manual inputs whose values are
    # ignored at this operating point and append the auto-derived equivalents
    # below \u2014 same logic the report's Design point uses, kept in sync so the
    # UI section reads as the ACTUAL operating point, not stale defaults.
    solved = r.get("solved") if isinstance(r, dict) else None
    cs = getattr(solved, "control", None) if solved is not None else None
    op_mode = getattr(solved, "operating_mode", "island") if solved is not None else "island"

    def _input_tr(label, value_text, hint=""):
        return html.Tr([
            html.Td(label,
                    style={"padding": "4px 8px", "fontSize": "12px", "color": INK}),
            html.Td(value_text,
                    style={"padding": "4px 8px", "fontSize": "12px",
                           "textAlign": "right", "color": NAVY, "fontWeight": "600"}),
            html.Td(hint,
                    style={"padding": "4px 8px", "fontSize": "11px", "color": GREY}),
        ])

    rows = []
    for spec in engine.inputs:
        # Mode-suppressed inputs \u2014 their UI value is inert at this op point.
        if cs is not None:
            if spec.key == "load_pct"         and cs.derived_load_pct:    continue
            if spec.key == "libr_frac"        and cs.derived_libr_frac:   continue
            if spec.key == "external_load_kW" and op_mode == "grid_tied": continue
        hint = (f"range {spec.min:g}\u2013{spec.max:g}"
                 if spec.min is not None else "")
        rows.append(_input_tr(spec.label, f"{v[spec.key]:g} {spec.unit}", hint))

    # Auto-derived rows shown distinctively at the bottom of the table.
    if cs is not None:
        if cs.derived_load_pct:
            rows.append(_input_tr("GT load_pct  (Auto-derived)",
                                   f"{cs.load_pct:.1f} %",
                                   "computed from NEXA + mode"))
        if cs.derived_libr_frac:
            rows.append(_input_tr("libr_frac  (Auto-derived)",
                                   f"{cs.libr_frac:.3f}",
                                   "LiBr-priority \u00b7 MED residual"))
        if op_mode == "grid_tied":
            rows.append(_input_tr("Grid export  (Auto)",
                                   f"{cs.grid_export_kW:.0f} kW",
                                   "supply \u2212 NEXA demand \u00b7 export-only"))

    parts.append(html.Div([
        html.Div("Inputs used",
                 style={"fontWeight": "700", "color": NAVY,
                        "fontSize": "12px", "marginBottom": "6px"}),
        html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"}),
    ], style={"paddingTop": "12px", "borderTop": f"1px solid {LINE}",
              "marginBottom": "12px"}))

    # --- method notes ---
    if engine.notes:
        parts.append(html.Div([
            html.Div("Method & caveats",
                     style={"fontWeight": "700", "color": NAVY,
                            "fontSize": "12px", "marginBottom": "6px"}),
            html.Div(engine.notes,
                     style={"fontSize": "12px", "color": GREY, "lineHeight": "1.6"}),
        ], style={"paddingTop": "12px", "borderTop": f"1px solid {LINE}"}))

    return html.Div(parts, style={**CARD, "marginBottom": "16px"}) if parts else None


def call_ai_narrative(engine, v, r, model=None, api_key=None):
    """Call Claude directly via the Anthropic SDK.

    The API key comes from (in priority order):
      1. The `api_key` argument — typically the UI's stored key (dcc.Store
         with storage_type="local", persisted in browser localStorage).
      2. ANTHROPIC_API_KEY in the environment.

    No gateways. No fallbacks. If neither key is available or the call
    fails, the UI shows a clear inline error and reports stay clear of
    AI content."""
    model = model or AI_MODEL_DEFAULT
    inp_txt = "\n".join(f"  {s.label}: {v[s.key]:g} {s.unit}" for s in engine.inputs)
    out_txt = "\n".join(
        f"  {o.label}: {o.text()} {o.unit}  [{o.basis}]" for o in engine.outputs(r))
    prompt = (
        f"You are a multidisciplinary expert engineering consultant with deep expertise across "
        f"four domains simultaneously:\n"
        f"  1. Senior Process Engineer - thermodynamics, fluid mechanics, heat & mass transfer, "
        f"P&IDs, steady-state simulation, equipment sizing.\n"
        f"  2. Expert in Cooling & Heating Systems - industrial chillers, heat exchangers, HRSG, "
        f"waste-heat recovery, district energy, absorption cycles, cooling towers.\n"
        f"  3. Expert in Power Generation - gas turbines, combined cycle, cogeneration, fuel "
        f"systems, grid interconnect, part-load performance, emissions.\n"
        f"  4. Expert in High-density Data Centers - GPU/TPU compute clusters, immersion cooling, "
        f"direct liquid cooling, PUE optimisation, IT power density, thermal management.\n\n"
        f"You are reviewing a screening-grade simulation. Apply all four lenses where relevant.\n\n"
        f"Tool: {engine.name}\n"
        f"Method notes: {engine.notes}\n\n"
        f"Inputs:\n{inp_txt}\n\n"
        f"Results:\n{out_txt}\n\n"
        f"Write a thorough engineering assessment structured in exactly these five sections. "
        f"Each section should be 3-4 sentences. Be specific to the numbers above; "
        f"use engineering units throughout; no filler phrases.\n\n"
        f"1. SYSTEM OVERVIEW & CONVERGENCE\n"
        f"   Describe what this simulation models and state clearly whether all balance margins "
        f"close (>= 0). Give the overall verdict in one sentence.\n\n"
        f"2. KEY PERFORMANCE FINDINGS\n"
        f"   Highlight the most important quantitative results - efficiencies, flows, duties, "
        f"key ratios - and what they imply for the design or operation.\n\n"
        f"3. ENGINEERING CONCERNS & RISKS\n"
        f"   Identify anything marginal, unusual, or potentially problematic. Cross-reference "
        f"across domains where relevant (e.g. does available exhaust heat match chiller demand? "
        f"Is velocity within acceptable pipe limits? Is PUE competitive?).\n\n"
        f"4. DESIGN RECOMMENDATIONS\n"
        f"   Give concrete, quantified suggestions to improve performance, close any deficits, "
        f"or reduce risk. State which input to change and by how much where possible.\n\n"
        f"5. VERIFICATION PRIORITIES\n"
        f"   State which screening assumptions carry the most uncertainty and must be validated "
        f"- against manufacturer data, plant measurements, or detailed simulation - before "
        f"these numbers can be used for detailed design."
    )
    text = None
    model_used = None
    err = None

    import os as _os
    resolved_key = api_key or _os.environ.get("ANTHROPIC_API_KEY")
    if not resolved_key:
        return html.Div(
            "AI Analysis unavailable: no Anthropic API key. Paste your key "
            "in the AI Analysis card below (it stores in your browser only, "
            "never on the server) — or export ANTHROPIC_API_KEY in the env "
            "before starting the app.",
            style={"fontSize": "12px", "color": RED, "fontStyle": "italic"}), None

    try:
        import anthropic as _ant
        client = _ant.Anthropic(api_key=resolved_key)
        msg = client.messages.create(
            model=model, max_tokens=1400,
            messages=[{"role": "user", "content": prompt}])
        text = msg.content[0].text
        model_used = f"anthropic/{model}"
    except Exception as e:
        err = f"{type(e).__name__}: {e}"

    if text is None:
        return html.Div(
            f"AI call failed: {err}",
            style={"fontSize": "12px", "color": RED}), None

    # render each numbered section with a bold heading
    import re as _re
    parts = _re.split(r"(\d\.\s+[A-Z][A-Z &]+)", text)
    children = [
        html.Div(
            f"AI engineering assessment  -  {model_used}  (screening only)",
            style={"fontSize": "11px", "color": GREY,
                   "fontStyle": "italic", "marginBottom": "10px"})
    ]
    i = 0
    while i < len(parts):
        chunk = parts[i].strip()
        if not chunk:
            i += 1; continue
        if _re.match(r"^\d\.\s+[A-Z]", chunk):
            body = parts[i + 1].strip() if i + 1 < len(parts) else ""
            children.append(html.Div([
                html.Span(chunk,
                          style={"fontWeight": "700", "color": NAVY, "fontSize": "13px"}),
                html.P(body,
                       style={"fontSize": "13px", "color": INK,
                              "lineHeight": "1.70", "margin": "4px 0 12px 0"}),
            ]))
            i += 2
        else:
            children.append(
                html.P(chunk, style={"fontSize": "13px", "color": INK,
                                     "lineHeight": "1.70", "margin": "0 0 12px 0"}))
            i += 1

    return html.Div(children), text


def build_request_queue():
    """Read requests.jsonl and cross-reference REGISTRY to show live status."""
    log = os.path.join(os.path.dirname(__file__), "..", "data", "requests.jsonl")
    if not os.path.exists(log):
        return html.Div("No requests submitted yet.",
                        style={"fontSize": "13px", "color": GREY, "padding": "4px 0"})
    reqs = []
    with open(log) as f:
        for line in f:
            try:
                reqs.append(json.loads(line.strip()))
            except Exception:
                pass
    if not reqs:
        return html.Div("No requests submitted yet.",
                        style={"fontSize": "13px", "color": GREY, "padding": "4px 0"})

    def status_of(text):
        for e in REGISTRY.values():
            prov = e.provenance or ""
            # exact match, OR provenance starts with the first 60 chars of the request
            # (handles tools whose provenance was extended with upgrade notes)
            if prov == text or prov.startswith(text[:min(len(text), 60)]):
                if e.status == "trusted":
                    return "trusted", e.name
                if e.notes.startswith("Draft skeleton generated"):
                    return "skeleton", e.name
                return "logic_ready", e.name
        return "pending", None

    BADGE = {
        "trusted":    {"color": "#2E7D4E", "background": "#E8F5EC", "border": "1px solid #2E7D4E",
                       "label": "\u2713 Verified"},
        "logic_ready":{"color": "#1A5276", "background": "#D6EAF8", "border": "1px solid #2980B9",
                       "label": "\u25cf Logic ready"},
        "skeleton":   {"color": NAVY,      "background": LIGHT,    "border": f"1px solid {LINE}",
                       "label": "\u25d4 Skeleton"},
        "pending":    {"color": GREY,      "background": "#F5F5F5", "border": "1px solid #CCC",
                       "label": "\u25cb Pending"},
    }
    bp = {"padding": "2px 8px", "borderRadius": "4px", "fontSize": "11px",
          "fontWeight": "600", "display": "inline-block"}

    head = html.Tr([html.Th(h, style={"textAlign": "left", "padding": "6px 10px",
                                      "color": NAVY, "fontSize": "12px",
                                      "borderBottom": f"2px solid {LIGHT}"})
                    for h in ("Submitted", "Description", "Kind", "Tool name", "Status")])
    rows = [head]
    for req in sorted(reqs, key=lambda r: r.get("created", 0), reverse=True):
        text = req.get("text", "")
        kind = req.get("kind", "-")
        ts   = req.get("created", 0)
        status, tname = status_of(text)
        b = BADGE.get(status, BADGE["pending"])
        rows.append(html.Tr([
            html.Td(time.strftime("%Y-%m-%d %H:%M", time.localtime(ts)) if ts else "-",
                    style={"padding": "6px 10px", "fontSize": "12px",
                           "color": GREY, "whiteSpace": "nowrap"}),
            html.Td(text[:90] + ("\u2026" if len(text) > 90 else ""),
                    style={"padding": "6px 10px", "fontSize": "12px", "color": INK}),
            html.Td(kind,  style={"padding": "6px 10px", "fontSize": "12px", "color": GREY}),
            html.Td(tname or "\u2014",
                    style={"padding": "6px 10px", "fontSize": "12px", "color": NAVY}),
            html.Td(html.Span(b["label"],
                              style={**bp, "color": b["color"],
                                     "background": b["background"],
                                     "border": b["border"]}),
                    style={"padding": "6px 10px"}),
        ]))
    return html.Table(rows, style={"width": "100%", "borderCollapse": "collapse"})


def _btn(label, bid, primary=False):
    return html.Button(label, id=bid, n_clicks=0, style={
        "padding": "9px 16px", "borderRadius": "7px", "border": f"1px solid {NAVY}", "cursor": "pointer",
        "fontSize": "13px", "fontWeight": "600", "marginRight": "10px",
        "background": (TEAL if primary else "white"), "color": ("white" if primary else NAVY)})


def _sbtn(label, bid, danger=False):
    """Small dataset-control button — sized to fit two-per-row in the 300px panel."""
    col = RED if danger else NAVY
    return html.Button(label, id=bid, n_clicks=0, style={
        "flex": "1", "padding": "6px 8px", "borderRadius": "6px",
        "border": f"1px solid {col}", "cursor": "pointer", "fontSize": "12px",
        "fontWeight": "600", "background": "white", "color": col})


def datasets_panel():
    """Save / Update / Load / Delete controls for the current engine's inputs.
    Lives in the static left panel (always present) so its callbacks don't
    depend on the per-engine #inputs rebuild."""
    field = {"width": "100%", "padding": "7px 9px", "border": f"1px solid {LINE}",
             "borderRadius": "6px", "fontSize": "12px", "boxSizing": "border-box",
             "marginBottom": "6px"}
    return html.Div([
        html.Div("Datasets", style={"fontSize": "12px", "fontWeight": "700",
                                     "color": NAVY, "marginBottom": "6px"}),
        dcc.Dropdown(id="dataset-select", options=[], placeholder="select a dataset…",
                     style={"fontSize": "12px", "marginBottom": "6px"}),
        dcc.Input(id="dataset-name", type="text", placeholder="name for new dataset",
                  style=field),
        html.Div([_sbtn("💾 Save", "b-ds-save"),
                  _sbtn("↻ Update", "b-ds-update")],
                 style={"display": "flex", "gap": "6px", "marginBottom": "6px"}),
        html.Div([_sbtn("📂 Load", "b-ds-load"),
                  _sbtn("🗑 Delete", "b-ds-delete", danger=True)],
                 style={"display": "flex", "gap": "6px", "marginBottom": "6px"}),
        html.Div([_sbtn("⟲ Reset to default", "b-ds-reset")],
                 style={"display": "flex", "gap": "6px"}),
        html.Div("Save a dataset named “Default” to set this simulator's default "
                 "parameters; Reset reloads them.",
                 style={"fontSize": "10px", "color": GREY, "marginTop": "6px",
                        "lineHeight": "1.3"}),
        html.Div(id="ds-status", style={"fontSize": "11px", "color": GREY,
                                         "marginTop": "7px", "minHeight": "14px"}),
    ], style={"padding": "12px", "border": f"1px solid {LINE}",
              "borderRadius": "8px", "background": BG, "marginBottom": "16px"})


MODAL_HIDDEN = {"display": "none"}
MODAL_SHOWN = {"display": "flex", "position": "fixed", "top": "0", "left": "0", "width": "100%",
               "height": "100%", "background": "rgba(20,30,50,0.45)", "alignItems": "center",
               "justifyContent": "center", "zIndex": "1000"}

app.layout = html.Div([
    html.Div([
        html.Div([
            html.Div("EngineTools", style={"fontSize": "22px", "fontWeight": "700"}),
            html.Div("Nexa Block v1 - pick a tool, run it, export the report; or request a new one",
                     style={"fontSize": "13px", "opacity": "0.85", "marginTop": "2px"}),
        ]),
        html.Div([
            # Docs picker — opens the chosen markdown file rendered as styled
            # HTML in a new browser tab via the /docs/<name> Flask route.
            html.Div([
                html.Span("📖 Docs:", style={"fontSize": "13px", "marginRight": "8px",
                                              "opacity": "0.85"}),
                html.A("Simulator", href="/docs/NEXA_SIMULATOR.md", target="_blank",
                       style={"color": "white", "fontSize": "12px",
                              "marginRight": "10px", "textDecoration": "underline"}),
                html.A("Manual",    href="/docs/MANUAL.md", target="_blank",
                       style={"color": "white", "fontSize": "12px",
                              "marginRight": "10px", "textDecoration": "underline"}),
                html.A("Dictionary", href="/docs/DICTIONARY.md", target="_blank",
                       style={"color": "white", "fontSize": "12px",
                              "marginRight": "10px", "textDecoration": "underline"}),
                html.A("Architecture", href="/docs/ARCHITECTURE.md", target="_blank",
                       style={"color": "white", "fontSize": "12px",
                              "marginRight": "10px", "textDecoration": "underline"}),
                html.A("Index", href="/docs/README.md", target="_blank",
                       style={"color": "white", "fontSize": "12px",
                              "textDecoration": "underline"}),
            ], style={"display": "flex", "alignItems": "center",
                      "marginRight": "20px"}),
            html.Button("+ Request a tool", id="req-open", n_clicks=0, style={
                "padding": "10px 16px", "borderRadius": "7px", "border": "1px solid white",
                "background": "transparent", "color": "white", "cursor": "pointer", "fontWeight": "600"}),
        ], style={"display": "flex", "alignItems": "center"}),
    ], style={"background": NAVY, "color": "white", "padding": "20px 28px", "display": "flex",
              "justifyContent": "space-between", "alignItems": "center"}),

    html.Div([
        html.Div([
            html.Label("System", style={"fontSize": "13px", "color": GREY, "fontWeight": "600"}),
            dcc.Dropdown(id="system", clearable=False, options=build_options(),
                         value="gt_system_v2", style={"marginBottom": "16px", "marginTop": "6px"}),
            datasets_panel(),
            html.Div(id="inputs"),
            _btn("Run", "run", primary=True),
        ], style={**CARD, "width": "300px", "alignSelf": "flex-start"}),

        html.Div([
            html.Div(id="status-bar"),
            html.Div(id="banner"),
            html.Div(id="conv-status"),       # convergence card (per-Run, persistent across study clicks)
            html.Div(id="feas-status"),       # resource-balance feasibility cards (separate from convergence)
            html.Div(id="audit-status"),      # post-solve audit summary card (39 checks)
            html.Div(id="highlights"),
            html.Div([
                dcc.Loading(type="circle", color=TEAL,
                            children=html.Img(id="chart", style={"width": "100%", "borderRadius": "8px"})),
            ], style={**CARD, "marginBottom": "16px"}),
            html.Div([
                html.Div("Studies",
                         style={"fontWeight": "700", "color": NAVY, "fontSize": "14px",
                                "marginBottom": "10px"}),
                # Sensitivity row — multi-select inputs, multi-select KPIs
                html.Div([
                    html.Div("Sensitivity",
                             style={"fontSize": "12px", "fontWeight": "700",
                                    "color": NAVY, "marginBottom": "4px"}),
                    html.Div([
                        html.Div(dcc.Dropdown(id="study-sens-inputs", multi=True,
                                              placeholder="inputs to perturb",
                                              style={"fontSize": "11px"}),
                                 style={"flex": "2", "marginRight": "6px"}),
                        html.Div(dcc.Dropdown(id="study-sens-kpis", multi=True,
                                              placeholder="KPIs to analyse",
                                              style={"fontSize": "11px"}),
                                 style={"flex": "2", "marginRight": "6px"}),
                        html.Button("\U0001F300 Run", id="b-study-sens", n_clicks=0,
                                    style={"padding": "8px 12px", "borderRadius": "7px",
                                           "fontSize": "12px", "fontWeight": "600",
                                           "cursor": "pointer",
                                           "background": "white", "color": NAVY,
                                           "border": f"1px solid {NAVY}"}),
                    ], style={"display": "flex", "alignItems": "center"}),
                ], style={"marginBottom": "10px"}),

                # Sweep row — 1D/2D toggle with conditional selectors
                html.Div([
                    html.Div([
                        html.Div("Sweep",
                                 style={"fontSize": "12px", "fontWeight": "700",
                                        "color": NAVY, "marginRight": "10px"}),
                        dcc.RadioItems(id="study-sweep-mode",
                                       options=[{"label": " 1D", "value": "1d"},
                                                 {"label": " 2D", "value": "2d"}],
                                       value="1d", inline=True,
                                       style={"fontSize": "11px", "color": INK}),
                    ], style={"display": "flex", "alignItems": "center",
                              "marginBottom": "4px"}),
                    html.Div([
                        html.Div(dcc.Dropdown(id="study-sweep-x", clearable=False,
                                              placeholder="X axis (input)",
                                              style={"fontSize": "11px"}),
                                 style={"flex": "1", "marginRight": "6px"}),
                        html.Div(dcc.Dropdown(id="study-sweep-y", clearable=False,
                                              placeholder="Y axis (input)",
                                              style={"fontSize": "11px"}),
                                 style={"flex": "1", "marginRight": "6px",
                                        "display": "none"},
                                 id="study-sweep-y-wrap"),
                        html.Div(dcc.Dropdown(id="study-sweep-kpis", multi=True,
                                              placeholder="KPI(s) to plot",
                                              style={"fontSize": "11px"}),
                                 style={"flex": "2", "marginRight": "6px"}),
                        html.Button("\U0001F4C8 Run", id="b-study-sweep", n_clicks=0,
                                    style={"padding": "8px 12px", "borderRadius": "7px",
                                           "fontSize": "12px", "fontWeight": "600",
                                           "cursor": "pointer",
                                           "background": "white", "color": NAVY,
                                           "border": f"1px solid {NAVY}"}),
                    ], style={"display": "flex", "alignItems": "center"}),
                    # Range controls for the 1D X sweep: min · max · steps.
                    # Auto-filled from the input's bounds when X is picked; edit
                    # to control the swept range and resolution.
                    html.Div([
                        html.Span("Range", style={"fontSize": "11px", "fontWeight": "700",
                                                  "color": NAVY, "marginRight": "8px"}),
                        html.Span("min", style={"fontSize": "10px", "color": GREY,
                                                "marginRight": "3px"}),
                        dcc.Input(id="sweep-min", type="number", placeholder="min",
                                  style={"width": "78px", "fontSize": "11px",
                                         "padding": "5px 6px", "marginRight": "10px",
                                         "border": f"1px solid {LINE}", "borderRadius": "6px"}),
                        html.Span("max", style={"fontSize": "10px", "color": GREY,
                                                "marginRight": "3px"}),
                        dcc.Input(id="sweep-max", type="number", placeholder="max",
                                  style={"width": "78px", "fontSize": "11px",
                                         "padding": "5px 6px", "marginRight": "10px",
                                         "border": f"1px solid {LINE}", "borderRadius": "6px"}),
                        html.Span("steps", style={"fontSize": "10px", "color": GREY,
                                                  "marginRight": "3px"}),
                        dcc.Input(id="sweep-steps", type="number", value=10, min=2, step=1,
                                  style={"width": "64px", "fontSize": "11px",
                                         "padding": "5px 6px",
                                         "border": f"1px solid {LINE}", "borderRadius": "6px"}),
                        html.Span("(1D sweep)", style={"fontSize": "10px", "color": GREY,
                                                       "marginLeft": "10px", "fontStyle": "italic"}),
                    ], style={"display": "flex", "alignItems": "center", "marginTop": "8px"}),
                ], style={"marginBottom": "10px"}),

                # Scenarios — single button
                html.Div([
                    html.Button("\U0001F326 Run scenarios", id="b-study-scen", n_clicks=0,
                                style={"padding": "8px 14px", "borderRadius": "7px",
                                       "fontSize": "12px", "fontWeight": "600",
                                       "cursor": "pointer",
                                       "background": "white", "color": NAVY,
                                       "border": f"1px solid {NAVY}"}),
                ], style={"marginBottom": "4px"}),
                html.Div([
                    html.Div(id="study-status",
                             style={"fontSize": "12px", "color": GREY,
                                    "marginRight": "12px", "flex": "1"}),
                    html.Button("Download Study CSV", id="b-study-csv", n_clicks=0,
                                style={"padding": "6px 12px", "borderRadius": "6px",
                                       "fontSize": "12px", "fontWeight": "600",
                                       "marginRight": "6px", "cursor": "pointer",
                                       "background": "white", "color": NAVY,
                                       "border": f"1px solid {NAVY}"}),
                    html.Button("Download Study Excel", id="b-study-xlsx", n_clicks=0,
                                style={"padding": "6px 12px", "borderRadius": "6px",
                                       "fontSize": "12px", "fontWeight": "600",
                                       "cursor": "pointer",
                                       "background": "white", "color": NAVY,
                                       "border": f"1px solid {NAVY}"}),
                    dcc.Download(id="d-study-csv"), dcc.Download(id="d-study-xlsx"),
                ], style={"display": "flex", "alignItems": "center",
                          "marginTop": "12px", "borderTop": f"1px solid {LINE}",
                          "paddingTop": "10px"}),
            ], style={**CARD, "marginBottom": "16px"}),
            html.Div(id="results", style={**CARD, "marginBottom": "16px"}),
            html.Div(id="smart-section", style={"marginBottom": "16px"}),
            html.Div([
                html.Div([
                    html.Div("AI Analysis",
                             style={"fontWeight": "700", "color": NAVY, "fontSize": "14px"}),
                    dcc.Dropdown(
                        id="ai-model", clearable=False, searchable=True,
                        options=AI_MODELS, value=AI_MODEL_DEFAULT,
                        style={"width": "320px", "fontSize": "12px"}),
                ], style={"display": "flex", "alignItems": "center",
                          "justifyContent": "space-between", "marginBottom": "10px"}),

                # API key row \u2014 input + save + remove + status. The actual key
                # lives in dcc.Store(storage_type="local") so it persists in
                # the user's browser only, never on the server filesystem.
                html.Div([
                    dcc.Input(id="ai-key-input", type="password",
                              placeholder="paste Anthropic API key (sk-ant-...)",
                              style={"flex": "1", "fontSize": "12px",
                                     "padding": "6px 10px",
                                     "border": f"1px solid {LINE}",
                                     "borderRadius": "6px",
                                     "marginRight": "6px"}),
                    html.Button("Save key", id="b-ai-key-save", n_clicks=0,
                                style={"padding": "6px 12px", "borderRadius": "6px",
                                       "fontSize": "12px", "fontWeight": "600",
                                       "cursor": "pointer", "background": "white",
                                       "color": NAVY, "marginRight": "6px",
                                       "border": f"1px solid {NAVY}"}),
                    html.Button("Remove", id="b-ai-key-clear", n_clicks=0,
                                style={"padding": "6px 12px", "borderRadius": "6px",
                                       "fontSize": "12px", "fontWeight": "600",
                                       "cursor": "pointer", "background": "white",
                                       "color": RED,
                                       "border": f"1px solid {RED}"}),
                ], style={"display": "flex", "alignItems": "center",
                          "marginBottom": "8px"}),
                html.Div(id="ai-key-status",
                         style={"fontSize": "11px", "color": GREY,
                                "marginBottom": "10px",
                                "fontStyle": "italic"}),

                _btn("\u26a1 AI Explain", "b-ai-explain"),
                dcc.Loading(type="dot", color=TEAL,
                            children=html.Div(id="ai-narrative",
                                             style={"marginTop": "12px", "minHeight": "20px"})),
            ], style={**CARD, "marginBottom": "16px"}),
            html.Div([
                _btn("Download PDF", "b-pdf"), _btn("Download Excel", "b-xlsx"),
                dcc.Checklist(id="include-study", value=[],
                              options=[{"label": "  Include latest study",
                                        "value": "yes"}],
                              style={"display": "inline-block",
                                     "marginLeft": "12px",
                                     "fontSize": "12px",
                                     "color": GREY}),
                dcc.Download(id="d-pdf"), dcc.Download(id="d-xlsx"),
            ], style={"display": "flex", "alignItems": "center",
                      "flexWrap": "wrap", "gap": "6px"}),
        ], style={"flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "padding": "22px 28px", "maxWidth": "1200px", "margin": "0 auto"}),

    # request queue panel
    html.Div([
        html.Div([
            html.Div("Request Queue",
                     style={"fontSize": "14px", "fontWeight": "700",
                            "color": NAVY, "marginBottom": "12px"}),
            html.Div(id="req-queue"),
        ], style={**CARD, "maxWidth": "1200px", "margin": "0 auto"}),
    ], style={"padding": "0 28px 22px 28px"}),

    dcc.Interval(id="queue-tick", interval=5000, n_intervals=0),

    # request modal
    html.Div([
        html.Div([
            html.Div("Request a tool", style={"fontSize": "18px", "fontWeight": "700", "color": NAVY, "marginBottom": "8px"}),
            html.Div("Describe what you need. A draft skeleton is created and appears below badged "
                     "\"draft\"; the logic gets filled in afterwards in chat with the assistant. "
                     "It stays draft until you verify and promote it.",
                     style={"fontSize": "13px", "color": GREY, "marginBottom": "12px"}),
            dcc.Textarea(id="req-text", placeholder="e.g. I need a process simulator for a single-stage flash desalination unit...",
                         style={"width": "100%", "height": "120px", "padding": "10px", "border": f"1px solid {LINE}",
                                "borderRadius": "8px", "fontSize": "14px", "boxSizing": "border-box"}),
            html.Div([
                html.Label("Kind", style={"fontSize": "13px", "color": GREY, "marginRight": "10px"}),
                dcc.Dropdown(id="req-kind", clearable=False, value="simulator",
                             options=[{"label": k, "value": k} for k in load_kinds()],
                             style={"width": "200px"}),
            ], style={"display": "flex", "alignItems": "center", "gap": "8px", "margin": "12px 0 6px"}),
            html.Div([
                dcc.Input(id="req-newkind", type="text", placeholder="or add a new kind (optional)",
                          style={"flex": "1", "padding": "8px 10px", "border": f"1px solid {LINE}",
                                 "borderRadius": "6px", "fontSize": "13px"}),
            ], style={"display": "flex", "marginBottom": "8px"}),
            html.Div(id="req-msg", style={"fontSize": "13px", "color": TEAL, "minHeight": "18px", "marginBottom": "10px"}),
            html.Div([_btn("Submit request", "req-submit", primary=True), _btn("Close", "req-cancel")]),
        ], style={**CARD, "width": "520px", "maxWidth": "90%"}),
    ], id="modal", style=MODAL_HIDDEN),

    dcc.Store(id="last"),
    dcc.Store(id="ai-text"),   # stores plain-text AI narrative for report export
    # API key persists in the user's browser localStorage; never on the server.
    dcc.Store(id="ai-key-store", storage_type="local"),
], style={"background": BG, "minHeight": "100vh", "fontFamily": "Arial, Helvetica, sans-serif"})


@app.callback(Output("inputs", "children"), Input("system", "value"))
def _build_inputs(key):
    return input_fields(get(key))


@app.callback(
    Output({"type": "sysin",     "key": MATCH}, "value"),
    Output({"type": "sysin",     "key": MATCH}, "style"),
    Input( {"type": "sysin-mat", "key": MATCH}, "value"),
    prevent_initial_call=True)
def _material_select(mat_val):
    visible = dict(_INPUT_STYLE, display="block", marginTop="4px")
    hidden  = dict(_INPUT_STYLE, display="none")
    if mat_val == "__custom__":
        return no_update, visible
    return float(mat_val), hidden


def _gt_load_sync(from_kw, pct, kw, p_rated, t_amb):
    """Pure core of the GT-load %↔kW link — returns (pct_out, kw_out) where
    each is either a number to write or `no_update` to leave alone.

    kW = derated capacity × load%, derated = p_rated × derate(T_amb).
    `from_kw` is True when the kW field is what the user just edited; otherwise
    the % is the source of truth (covers editing %, rated power, or ambient).
    Epsilon guards make the set→re-fire round-trip a no-op so it can't loop."""
    if p_rated is None or t_amb is None:
        return no_update, no_update
    derated = _gt_derated_kW(p_rated, t_amb)
    if derated <= 0:
        return no_update, no_update
    PCT_MIN, PCT_MAX = 10.0, 100.0

    if from_kw:
        if kw is None:
            return no_update, no_update
        pct_raw = float(kw) / derated * 100.0
        pct_new = min(PCT_MAX, max(PCT_MIN, pct_raw))
        # If we clamped (kW outside the 10–100% envelope), push the consistent
        # kW back so the two fields agree.
        kw_out = (round(derated * pct_new / 100.0, 1)
                  if abs(pct_new - pct_raw) > 1e-6 else no_update)
        if pct is not None and abs(float(pct) - pct_new) < 1e-3:
            return no_update, kw_out
        return round(pct_new, 2), kw_out

    # % is the source of truth (% / rated power / ambient changed) → recompute kW.
    if pct is None:
        return no_update, no_update
    kw_new = round(derated * float(pct) / 100.0, 1)
    if kw is not None and abs(float(kw) - kw_new) < 0.5:
        return no_update, no_update
    return no_update, kw_new


@app.callback(
    Output({"type": "sysin", "key": "load_pct"}, "value", allow_duplicate=True),
    Output("gt-load-kw", "value", allow_duplicate=True),
    Input({"type": "sysin", "key": "load_pct"},    "value"),
    Input("gt-load-kw",                            "value"),
    Input({"type": "sysin", "key": "p_rated_kW"},  "value"),
    Input({"type": "sysin", "key": "t_ambient_C"}, "value"),
    prevent_initial_call=True)
def _sync_gt_load(pct, kw, p_rated, t_amb):
    """Two-way link between 'GT load (%)' and 'GT load (kW)'. Whichever field
    the user edits drives the other; editing rated power or ambient re-derives
    the kW at the current %. Logic lives in _gt_load_sync (unit-tested)."""
    return _gt_load_sync(ctx.triggered_id == "gt-load-kw", pct, kw, p_rated, t_amb)


# ── Datasets: Save / Update / Delete (+ refresh) and Load ─────────────────────

@app.callback(
    Output("dataset-select", "options"),
    Output("dataset-select", "value"),
    Output("ds-status", "children"),
    Input("b-ds-save",   "n_clicks"),
    Input("b-ds-update", "n_clicks"),
    Input("b-ds-delete", "n_clicks"),
    Input("system",      "value"),
    State("dataset-name",   "value"),
    State("dataset-select", "value"),
    State({"type": "sysin", "key": ALL}, "value"),
    State({"type": "sysin", "key": ALL}, "id"))
def _manage_datasets(_s, _u, _d, engine_key, new_name, selected, values, ids):
    """Save (named), Update (overwrite selected), Delete (selected). Also
    refreshes the dataset list when the engine changes. Loading is separate
    (_load_dataset) because it writes into the input fields."""
    trig = ctx.triggered_id
    opts = _dataset_options(engine_key)

    # Engine changed / first load → just (re)populate the list, clear selection.
    if trig in (None, "system"):
        return opts, None, ""

    cur = {i["key"]: v for i, v in zip(ids, values)} if ids else {}

    if trig == "b-ds-save":
        name = (new_name or "").strip()
        if not name:
            return opts, selected, "Enter a name to save a dataset."
        existed = _datasets.exists(engine_key, name)
        _datasets.save_dataset(engine_key, name, cur)
        verb = "Overwrote" if existed else "Saved"
        note = ""
        if _datasets.is_default_name(name):           # 'Default' → set simulator default
            _datasets.set_default_params(engine_key, cur)
            note = "  — set as this simulator's default parameters."
        return _dataset_options(engine_key), name, f"{verb} dataset '{name}'.{note}"

    if trig == "b-ds-update":
        if not selected:
            return opts, selected, "Select a dataset first, then Update."
        _datasets.save_dataset(engine_key, selected, cur)
        note = ""
        if _datasets.is_default_name(selected):
            _datasets.set_default_params(engine_key, cur)
            note = "  — simulator default parameters updated."
        return _dataset_options(engine_key), selected, f"Updated dataset '{selected}'.{note}"

    if trig == "b-ds-delete":
        if not selected:
            return opts, selected, "Select a dataset first, then Delete."
        _datasets.delete_dataset(engine_key, selected)
        # Deleting the 'Default' dataset does NOT clear the persisted default
        # parameters — they remain the simulator default until overwritten.
        note = (" Default parameters are still retained."
                if _datasets.is_default_name(selected) else "")
        return _dataset_options(engine_key), None, f"Deleted dataset '{selected}'.{note}"

    return opts, selected, ""


@app.callback(
    Output({"type": "sysin",     "key": ALL}, "value", allow_duplicate=True),
    Output({"type": "sysin-mat", "key": ALL}, "value", allow_duplicate=True),
    Output("ds-status", "children", allow_duplicate=True),
    Input("b-ds-load", "n_clicks"),
    State("dataset-select", "value"),
    State("system",         "value"),
    State({"type": "sysin",     "key": ALL}, "id"),
    State({"type": "sysin-mat", "key": ALL}, "id"),
    prevent_initial_call=True)
def _load_dataset(_n, selected, engine_key, sysin_ids, mat_ids):
    """Push a saved dataset back into every input. Sets the `sysin` number
    inputs (what solve reads) plus the `sysin-mat` selectors (so mode dropdowns
    show the right option). The GT-load kW twin re-derives via _sync_gt_load."""
    noop = ([no_update] * len(sysin_ids), [no_update] * len(mat_ids))
    if not selected:
        return (*noop, "Select a dataset to load.")
    ds = _datasets.get_dataset(engine_key, selected)
    if ds is None:
        return (*noop, f"Dataset '{selected}' not found.")
    engine = get(engine_key)
    return (_dataset_sysin_values(sysin_ids, ds),
            _dataset_mat_values(mat_ids, ds, engine),
            f"Loaded dataset '{selected}'.")


@app.callback(
    Output({"type": "sysin",     "key": ALL}, "value", allow_duplicate=True),
    Output({"type": "sysin-mat", "key": ALL}, "value", allow_duplicate=True),
    Output("ds-status", "children", allow_duplicate=True),
    Input("b-ds-reset", "n_clicks"),
    State("system",         "value"),
    State({"type": "sysin",     "key": ALL}, "id"),
    State({"type": "sysin-mat", "key": ALL}, "id"),
    prevent_initial_call=True)
def _reset_defaults(_n, engine_key, sysin_ids, mat_ids):
    """Reset every input to this simulator's default parameters — the user-saved
    'Default' dataset if one exists, otherwise the code (InputSpec) defaults."""
    engine = get(engine_key)
    eff = _effective_defaults(engine)
    saved = _datasets.get_default_params(engine_key) is not None
    msg = ("Reset to saved default parameters." if saved
           else "Reset to built-in default parameters (no 'Default' saved yet).")
    return (_dataset_sysin_values(sysin_ids, eff),
            _dataset_mat_values(mat_ids, eff, engine),
            msg)


@app.callback(
    Output("highlights", "children"), Output("results", "children"),
    Output("chart", "src"), Output("last", "data"), Output("banner", "children"),
    Output("status-bar", "children"), Output("smart-section", "children"),
    Output("conv-status", "children"), Output("feas-status", "children"),
    Output("audit-status", "children"),
    Input("run", "n_clicks"), Input("system", "value"),
    State({"type": "sysin", "key": ALL}, "value"), State({"type": "sysin", "key": ALL}, "id"))
def _run(_n, key, values, ids):
    engine = get(key)
    if values and ids and len(values) == len(engine.inputs):
        vals = {i["key"]: v for i, v in zip(ids, values)}
    else:
        vals = _effective_defaults(engine)
    r = engine.solve(vals)
    # Draft-tool notice (if any) goes into the multi-purpose banner; convergence
    # status gets its own dedicated card below so it's not clobbered when the
    # study buttons write into banner.
    banner = None
    if engine.status == "draft":
        banner = html.Div(
            "Draft tool - generated skeleton, logic not filled, outputs unverified. "
            "Edit it through Request a tool, then verify and promote.",
            style={"background": "#FDEEEC", "border": f"1px solid {RED}", "color": RED,
                   "padding": "10px 14px", "borderRadius": "8px", "marginBottom": "14px", "fontSize": "13px"})
    conv_status  = convergence_card(r)
    feas_status  = feasibility_card(r)
    audit_status = audit_card(r)
    status_bar = html.Div([
        html.Span("\u2713  ", style={"fontWeight": "700"}),
        html.Span(f"Calculation complete \u2014 {engine.name}"),
    ], style={"background": "#E8F8F5", "border": f"1px solid {TEAL}", "borderRadius": "8px",
              "padding": "9px 14px", "marginBottom": "14px", "fontSize": "13px",
              "color": TEAL, "fontWeight": "600"})
    return (highlight_cards(engine, r), results_table(engine, r), chart_src(engine, r),
            {"key": key, "vals": vals}, banner, status_bar,
            build_smart_section(engine, vals, r),
            conv_status, feas_status, audit_status)


@app.callback(Output("modal", "style"),
              Input("req-open", "n_clicks"), Input("req-cancel", "n_clicks"), Input("req-submit", "n_clicks"))
def _modal(_o, _c, _s):
    if ctx.triggered_id == "req-open":
        return MODAL_SHOWN
    return MODAL_HIDDEN


@app.callback(Output("req-msg", "children"), Output("system", "options"), Output("req-kind", "options"),
              Input("req-submit", "n_clicks"), State("req-text", "value"),
              State("req-kind", "value"), State("req-newkind", "value"),
              prevent_initial_call=True)
def _submit(_n, text, kind, newkind):
    text = (text or "").strip()
    kind_opts = [{"label": k, "value": k} for k in load_kinds()]
    if not text:
        return "Enter a description first.", build_options(), kind_opts
    if (newkind or "").strip():
        add_kind(newkind)
        kind = newkind.strip().lower()
        kind_opts = [{"label": k, "value": k} for k in load_kinds()]
    save_request(text, kind)
    key = f"{_slug(text)}_{int(time.time())}"
    name = text.split("\n")[0][:60]
    scaffold_tool(key, name, kind, [("value", "Value", "-", 0)], text)
    return f"Draft created ({kind}): {name}. Select it in the System list.", build_options(), kind_opts


@app.callback(Output("req-queue", "children"), Input("queue-tick", "n_intervals"))
def _refresh_queue(_n):
    return build_request_queue()


@app.callback(Output("ai-narrative", "children"),
              Output("ai-text", "data"),
              Input("b-ai-explain", "n_clicks"),
              State("last", "data"),
              State("ai-model", "value"),
              State("ai-key-store", "data"),
              prevent_initial_call=True)
def _ai_explain(_n, data, model, api_key):
    if not data:
        return html.Div("Run a calculation first, then click AI Explain.",
                        style={"fontSize": "12px", "color": GREY}), None
    engine = get(data["key"])
    vals   = data["vals"]
    r      = engine.solve(vals)
    html_div, plain_text = call_ai_narrative(engine, vals, r,
                                              model=model or AI_MODEL_DEFAULT,
                                              api_key=api_key)
    return html_div, plain_text


# ─── API key save / clear / status ─────────────────────────────────────────

@app.callback(Output("ai-key-store", "data", allow_duplicate=True),
              Output("ai-key-input", "value", allow_duplicate=True),
              Input("b-ai-key-save", "n_clicks"),
              State("ai-key-input", "value"),
              prevent_initial_call=True)
def _ai_key_save(_n, value):
    """Persist the typed key into browser localStorage; clear the input field."""
    if not value or not value.strip():
        return no_update, no_update
    return value.strip(), ""


@app.callback(Output("ai-key-store", "data", allow_duplicate=True),
              Input("b-ai-key-clear", "n_clicks"),
              prevent_initial_call=True)
def _ai_key_clear(_n):
    """Remove the key from browser localStorage."""
    return None


@app.callback(Output("ai-key-status", "children"),
              Input("ai-key-store", "data"))
def _ai_key_status(stored):
    """Show whether a key is stored and a redacted hint of which one."""
    import os as _os
    if stored:
        # show last 4 chars only — confirms identity without exposing the key
        hint = ("…" + stored[-4:]) if len(stored) > 4 else "…"
        return html.Span([
            html.Span("✓ Key stored in browser ",
                       style={"color": "#2E7D4E", "fontWeight": "600"}),
            html.Span(f"({hint})", style={"color": GREY}),
        ])
    env_key = _os.environ.get("ANTHROPIC_API_KEY")
    if env_key:
        return html.Span(
            "ANTHROPIC_API_KEY found in server env — will be used if no key "
            "is saved here.", style={"color": GREY})
    return html.Span(
        "No API key. Paste your Anthropic key above and click Save.",
        style={"color": RED})


# Latest study per engine. Populated by the three study callbacks; read by
# the report exporters (when "Include latest study" is on) and by the
# standalone Study CSV / Excel downloads. Backed by a small pickle file
# per engine under ~/.enginetools/studies so a server restart doesn't
# silently drop the user's last run.
_LATEST_STUDY: dict = {}
_STUDY_DIR    = _pl.Path.home() / ".enginetools" / "studies"


def _save_study_to_disk(engine_key: str, study: dict) -> None:
    """Best-effort persist; never crashes the request."""
    try:
        _STUDY_DIR.mkdir(parents=True, exist_ok=True)
        with open(_STUDY_DIR / f"{engine_key}_latest.pkl", "wb") as f:
            _pk.dump(study, f, protocol=_pk.HIGHEST_PROTOCOL)
    except Exception as e:
        print(f"[STUDY] disk save failed for {engine_key}: {e}")


def _load_studies_from_disk() -> None:
    """Restore _LATEST_STUDY from any previously saved pickles. Skip bad ones."""
    if not _STUDY_DIR.is_dir():
        return
    for p in _STUDY_DIR.glob("*_latest.pkl"):
        try:
            with open(p, "rb") as f:
                study = _pk.load(f)
            engine_key = study.get("engine_key") or p.stem.replace("_latest", "")
            _LATEST_STUDY[engine_key] = study
        except Exception as e:
            print(f"[STUDY] could not restore {p.name}: {e}")


_load_studies_from_disk()


def _report(data, kind, ai_text=None, include_study=False):
    engine = get(data["key"]); vals = data["vals"]; r = engine.solve(vals)
    d = tempfile.mkdtemp(); slug = data["key"]
    study = _LATEST_STUDY.get(data["key"]) if include_study else None
    if kind == "pdf":
        p = f"{d}/{slug}.pdf"
        build_pdf(engine, vals, r, p, f"{d}/c.png", ai_text=ai_text, study=study)
    elif kind == "xlsx":
        p = f"{d}/{slug}.xlsx"
        build_excel(engine, vals, r, p, ai_text=ai_text, study=study)
    else:
        p = f"{d}/{slug}.pptx"
        build_pptx(engine, vals, r, p, f"{d}/c.png", ai_text=ai_text)
    return dcc.send_file(p)


@app.callback(Output("d-pdf", "data"), Input("b-pdf", "n_clicks"),
              State("last", "data"), State("ai-text", "data"),
              State("include-study", "value"), prevent_initial_call=True)
def _dl_pdf(_n, data, ai_text, include_study):
    return _report(data, "pdf", ai_text=ai_text,
                   include_study=bool(include_study and "yes" in include_study))


@app.callback(Output("d-xlsx", "data"), Input("b-xlsx", "n_clicks"),
              State("last", "data"), State("ai-text", "data"),
              State("include-study", "value"), prevent_initial_call=True)
def _dl_xlsx(_n, data, ai_text, include_study):
    return _report(data, "xlsx", ai_text=ai_text,
                   include_study=bool(include_study and "yes" in include_study))


# ─── Studies (sensitivity / sweep / scenarios) ────────────────────────────────

def _engine_hooks(key: str):
    """Return (engine, hooks) or (engine, None) if the engine doesn't expose them."""
    engine = get(key)
    hooks  = engine.study_hooks() if hasattr(engine, "study_hooks") else None
    return engine, hooks


@app.callback(Output("study-sens-inputs", "options"),
              Output("study-sens-inputs", "value"),
              Output("study-sens-kpis", "options"),
              Output("study-sens-kpis", "value"),
              Output("study-sweep-x", "options"),
              Output("study-sweep-x", "value"),
              Output("study-sweep-y", "options"),
              Output("study-sweep-y", "value"),
              Output("study-sweep-kpis", "options"),
              Output("study-sweep-kpis", "value"),
              Input("system", "value"))
def _populate_study_pickers(engine_key):
    """When the engine changes, repopulate every Studies dropdown from the
    engine's study_hooks. Defaults: all sensitivity_inputs + all KPIs
    selected; sweep X = first sweep_inputs entry; KPIs = all."""
    empty = ([], None)
    none10 = (*empty,)*5
    if not engine_key:
        return [], [], [], [], [], None, [], None, [], []
    _, hooks = _engine_hooks(engine_key)
    if not hooks:
        return [], [], [], [], [], None, [], None, [], []
    sens_inputs = hooks.get("sensitivity_inputs", [])
    sweep_inputs = hooks.get("sweep_inputs", [])
    kpis  = hooks.get("kpis", [])
    sens_input_opts  = [{"label": k, "value": k} for k in sens_inputs]
    kpi_opts         = [{"label": k, "value": k} for k in kpis]
    sweep_input_opts = [{"label": k, "value": k} for k in sweep_inputs]
    x_val = sweep_inputs[0] if sweep_inputs else None
    y_val = sweep_inputs[1] if len(sweep_inputs) >= 2 else (sweep_inputs[0] if sweep_inputs else None)
    return (sens_input_opts,  sens_inputs,
            kpi_opts,         kpis,
            sweep_input_opts, x_val,
            sweep_input_opts, y_val,
            kpi_opts,         kpis)


@app.callback(Output("study-sweep-y-wrap", "style"),
              Input("study-sweep-mode", "value"))
def _toggle_y_picker(mode):
    """Show Y selector only in 2D mode."""
    base = {"flex": "1", "marginRight": "6px"}
    return ({**base, "display": "block"} if mode == "2d"
            else {**base, "display": "none"})


def _msg(text, color=None):
    return html.Div(text, style={"color": color or GREY, "fontSize": "12px",
                                 "fontWeight": "600", "marginBottom": "8px"})


def _png_data_uri(path: str) -> str:
    with open(path, "rb") as f:
        return "data:image/png;base64," + base64.b64encode(f.read()).decode()


def _run_study(kind: str, data, *, sens_inputs=None, sens_kpis=None,
               sweep_mode="1d", sweep_x=None, sweep_y=None, sweep_kpis=None,
               sweep_min=None, sweep_max=None, sweep_steps=None):
    """Build the appropriate study chart and return (chart_src, banner).

    Multi-select inputs / KPIs honoured for sensitivity. Sweep dispatches
    on sweep_mode: 1D uses sweep_x + sweep_kpis; 2D uses sweep_x + sweep_y
    + first sweep_kpis entry (5×5 grid → contour)."""
    if not data:
        return no_update, _msg("Run the engine first, then use Studies.")
    engine, hooks = _engine_hooks(data["key"])
    if not hooks:
        return no_update, _msg("This engine doesn't expose study_hooks.", RED)

    vals   = data["vals"]
    params = hooks["make_params"](vals)
    d = tempfile.mkdtemp(); p = os.path.join(d, f"study_{kind}.png")

    try:
        if kind == "sensitivity":
            inputs_to_use = sens_inputs or hooks["sensitivity_inputs"]
            kpis_to_use   = sens_kpis or hooks["kpis"]
            if not inputs_to_use or not kpis_to_use:
                return no_update, _msg(
                    "Pick at least one input and one KPI for sensitivity.", RED)
            sens = OneAtATimeSensitivity(
                builder       = hooks["builder"],
                base_params   = params,
                kpi_fn        = hooks["kpi_fn"],
                bounds        = hooks.get("bounds", {}),
                step_override = hooks.get("step_override", {}),
            ).run(inputs=inputs_to_use, kpis=kpis_to_use)
            chart_kwargs = {"kpis": list(kpis_to_use), "drop_zero": True,
                            "title": f"Sensitivity tornado ({len(kpis_to_use)} KPIs)"}
            tornado_multi_chart(sens, p, **chart_kwargs)
            label = f"Sensitivity: {len(inputs_to_use)} inputs × {len(kpis_to_use)} KPIs"
            study_result = sens
            banner = _msg(label, NAVY)

        elif kind == "sweep":
            sweep_kpis = sweep_kpis or hooks["kpis"]
            if not sweep_x:
                return no_update, _msg("Pick an X input first.", RED)
            if not sweep_kpis:
                return no_update, _msg("Pick at least one KPI for sweep.", RED)
            bounds = hooks.get("bounds", {})
            def _range(name, n):
                if name in bounds:
                    lo, hi = bounds[name]
                else:
                    base_v = float(vals[name])
                    lo, hi = base_v * 0.8, base_v * 1.2
                return [lo + (hi - lo) * i / (n - 1) for i in range(n)]
            if sweep_mode == "2d":
                if not sweep_y:
                    return no_update, _msg("2D sweep needs a Y input.", RED)
                if sweep_y == sweep_x:
                    return no_update, _msg(
                        "X and Y must be different inputs for 2D sweep.", RED)
                z_kpi = sweep_kpis[0]   # contour shows one KPI at a time
                N = 5
                swp = ParameterSweep(hooks["builder"], params, hooks["kpi_fn"]).run(
                    {sweep_x: _range(sweep_x, N), sweep_y: _range(sweep_y, N)})
                sweep_contour(swp, p, kpi=z_kpi,
                              title=f"{z_kpi}  over  ({sweep_x}, {sweep_y})  [5×5]")
                label = f"2D sweep: {sweep_x} × {sweep_y} → {z_kpi}"
                chart_kwargs = {"kpi": z_kpi,
                                "title": f"{z_kpi} over ({sweep_x}, {sweep_y})"}
            else:
                # User-controlled range: min · max · steps for the X input.
                try:
                    n = int(float(sweep_steps))
                except (TypeError, ValueError):
                    n = 10
                n = max(2, min(n, 200))     # ≥2 points; cap so the solve stays sane
                if sweep_min is not None and sweep_max is not None:
                    lo, hi = float(sweep_min), float(sweep_max)
                    if lo == hi:
                        return no_update, _msg("Sweep min and max must differ.", RED)
                    rng = [lo + (hi - lo) * i / (n - 1) for i in range(n)]
                else:
                    rng = _range(sweep_x, n)   # fall back to the input's bounds
                lo, hi = rng[0], rng[-1]
                swp = ParameterSweep(hooks["builder"], params, hooks["kpi_fn"]).run(
                    {sweep_x: rng})
                title = f"Sweep over {sweep_x}  [{n} pts · {lo:g}–{hi:g}]"
                sweep_chart(swp, p, kpis=list(sweep_kpis), title=title, subplots=True)
                label = f"1D sweep: {sweep_x} {lo:g}→{hi:g} in {n} steps → {len(sweep_kpis)} KPIs"
                chart_kwargs = {"kpis": list(sweep_kpis),
                                "title": title,
                                "subplots": True}
            study_result = swp
            banner = _msg(label, NAVY)

        elif kind == "scenarios":
            scens = hooks.get("scenarios", {})
            if not scens:
                return no_update, _msg("No scenarios defined for this engine.", RED)
            res = ScenarioRunner(hooks["builder"], params, hooks["kpi_fn"]).run(scens)
            chart_kwargs = {"kpis": hooks["kpis"],
                            "title": "Scenario comparison (ratio vs current settings)"}
            scenarios_chart(res, p, **chart_kwargs)
            label = f"Scenarios: {', '.join(scens.keys())}"
            study_result = res
            banner = _msg(label, NAVY)
        else:
            return no_update, _msg(f"Unknown study kind: {kind}", RED)

    except Exception as e:
        import traceback as _tb
        print("[STUDY] ERROR:", _tb.format_exc())
        return no_update, _msg(f"Study failed: {e}", RED)

    # Stash the result with light metadata so it's self-describing for
    # report attach AND standalone CSV/Excel downloads. base_params is
    # converted to a JSON-friendly dict (the dataclass also remains inside
    # study_result.base_params for in-memory use).
    stash = {
        "kind":         kind,
        "result":       study_result,
        "chart_kwargs": chart_kwargs,
        "label":        label,
        "engine_key":   data["key"],
        "engine_name":  engine.name,
        "timestamp":    _dt.datetime.now().isoformat(timespec="seconds"),
        "base_params":  _dc.asdict(params),
    }
    _LATEST_STUDY[data["key"]] = stash
    _save_study_to_disk(data["key"], stash)
    return _png_data_uri(p), banner


@app.callback(Output("chart", "src", allow_duplicate=True),
              Output("banner", "children", allow_duplicate=True),
              Input("b-study-sens", "n_clicks"),
              State("last", "data"),
              State("study-sens-inputs", "value"),
              State("study-sens-kpis",   "value"),
              prevent_initial_call=True)
def _on_study_sens(_n, data, sens_inputs, sens_kpis):
    return _run_study("sensitivity", data,
                       sens_inputs=sens_inputs, sens_kpis=sens_kpis)


@app.callback(Output("chart", "src", allow_duplicate=True),
              Output("banner", "children", allow_duplicate=True),
              Input("b-study-sweep", "n_clicks"),
              State("last", "data"),
              State("study-sweep-mode", "value"),
              State("study-sweep-x",    "value"),
              State("study-sweep-y",    "value"),
              State("study-sweep-kpis", "value"),
              State("sweep-min",   "value"),
              State("sweep-max",   "value"),
              State("sweep-steps", "value"),
              prevent_initial_call=True)
def _on_study_sweep(_n, data, mode, sweep_x, sweep_y, sweep_kpis,
                    sweep_min, sweep_max, sweep_steps):
    return _run_study("sweep", data, sweep_mode=mode,
                       sweep_x=sweep_x, sweep_y=sweep_y,
                       sweep_kpis=sweep_kpis, sweep_min=sweep_min,
                       sweep_max=sweep_max, sweep_steps=sweep_steps)


@app.callback(Output("sweep-min", "value"),
              Output("sweep-max", "value"),
              Input("study-sweep-x", "value"),
              State("system", "value"),
              prevent_initial_call=True)
def _sweep_range_defaults(sweep_x, engine_key):
    """When the X input changes, pre-fill min/max from that input's bounds so the
    user starts from a sensible range (they can override). Inputs without bounds
    leave the fields as they are."""
    if not sweep_x or not engine_key:
        return no_update, no_update
    _, hooks = _engine_hooks(engine_key)
    bounds = (hooks or {}).get("bounds", {})
    if sweep_x in bounds:
        lo, hi = bounds[sweep_x]
        return lo, hi
    return no_update, no_update


@app.callback(Output("chart", "src", allow_duplicate=True),
              Output("banner", "children", allow_duplicate=True),
              Input("b-study-scen", "n_clicks"),
              State("last", "data"),
              prevent_initial_call=True)
def _on_study_scen(_n, data):
    return _run_study("scenarios", data)


# ─── Latest-study status + standalone Study CSV / Excel downloads ─────────────

@app.callback(Output("study-status", "children"),
              Input("system", "value"),
              Input("b-study-sens",  "n_clicks"),
              Input("b-study-sweep", "n_clicks"),
              Input("b-study-scen",  "n_clicks"))
def _study_status(engine_key, _n1, _n2, _n3):
    if not engine_key:
        return "No engine selected."
    s = _LATEST_STUDY.get(engine_key)
    if not s:
        return "No study yet for this engine."
    return f"Latest study: {s['kind']} · {s.get('timestamp','')}"


def _dl_study(data, kind):
    """Shared logic for the two Download Study buttons."""
    if not data:
        return no_update, _msg("Pick an engine and run it first.")
    s = _LATEST_STUDY.get(data["key"])
    if not s:
        return no_update, _msg(
            "No study yet — click Sensitivity / Sweep / Scenarios first.", RED)
    d = tempfile.mkdtemp()
    ext = "csv" if kind == "csv" else "xlsx"
    p = os.path.join(d, f"{data['key']}_{s['kind']}.{ext}")
    try:
        if kind == "csv":
            study_to_csv(s, p)
        else:
            study_to_xlsx(s, p)
    except Exception as e:
        import traceback as _tb
        print("[STUDY DL] ERROR:", _tb.format_exc())
        return no_update, _msg(f"Study download failed: {e}", RED)
    return dcc.send_file(p), _msg(f"Study {ext.upper()} downloaded: {s['kind']}", NAVY)


@app.callback(Output("d-study-csv", "data"),
              Output("banner", "children", allow_duplicate=True),
              Input("b-study-csv", "n_clicks"),
              State("last", "data"),
              prevent_initial_call=True)
def _dl_study_csv(_n, data):
    return _dl_study(data, "csv")


@app.callback(Output("d-study-xlsx", "data"),
              Output("banner", "children", allow_duplicate=True),
              Input("b-study-xlsx", "n_clicks"),
              State("last", "data"),
              prevent_initial_call=True)
def _dl_study_xlsx(_n, data):
    return _dl_study(data, "xlsx")


if __name__ == "__main__":
    app.run(debug=True, port=8050, use_reloader=True)
