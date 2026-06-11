"""
Nexa process toolkit - generic UI with a tool-request box.

Pick a system and its inputs/results/chart/downloads build themselves from the
contract. "Request a tool" captures a description, records it, and scaffolds a
conforming DRAFT that appears in the dropdown badged "draft" - the agent (Cody)
fills its logic, sandboxed, and it stays draft until you promote it.

Run:
    pip install dash CoolProp scipy matplotlib reportlab openpyxl python-pptx
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
from nexa_toolkit.reporting.generic_report import (
    build_chart, build_excel, build_pdf, build_pptx)
try:
    from nexa_toolkit.dwsim_export import build_flowsheet as _dwsim_build_flowsheet
except Exception:
    _dwsim_build_flowsheet = None

NAVY = "#2E4E7E"; TEAL = "#2BB6A3"; LIGHT = "#EAF0F8"; GREY = "#5b6675"
INK = "#22303F"; BG = "#f4f7fb"; LINE = "#dbe2ee"; RED = "#C0392B"
BASIS = {"verified": "#2E7D4E", "screening": "#B26A00", "input": "#5b6675", "unverified": RED}

# AI model selector — add future models here; first entry is the default
AI_MODELS = [
    {"label": "Claude Haiku  (fast)",   "value": "claude-haiku-4-5"},
    {"label": "Claude Sonnet  (smart)", "value": "claude-sonnet-4-6"},
]
# Note: if a model isn't in the gateway catalog, calls fall back to the gateway's
# configured default model. The model_used label in the UI reflects the actual model used.
AI_MODEL_DEFAULT = AI_MODELS[0]["value"]

CARD = {"background": "white", "border": f"1px solid {LINE}", "borderRadius": "10px",
        "padding": "18px 20px", "boxShadow": "0 1px 3px rgba(20,40,80,0.06)"}

app = dash.Dash(__name__, title="EngineTools")
server = app.server


def build_options():
    opts = []
    for key, e in REGISTRY.items():
        label = e.name + ("  -  draft" if e.status == "draft" else "")
        opts.append({"label": label, "value": key})
    return opts


_INPUT_STYLE = {"width": "100%", "padding": "8px 10px", "border": f"1px solid {LINE}",
                "borderRadius": "6px", "fontSize": "14px", "boxSizing": "border-box"}


def input_fields(engine):
    out = []
    for s in engine.inputs:
        lbl = html.Label(f"{s.label}  ({s.unit})",
                         style={"fontSize": "13px", "color": GREY,
                                "display": "block", "marginBottom": "4px"})
        if s.choices:
            opts = [{"label": f"{name}  —  {val} mm", "value": val}
                    for name, val in s.choices.items()]
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
    return out


def highlight_cards(engine, r):
    cards = [html.Div([
        html.Div(o.label, style={"fontSize": "12px", "color": GREY, "marginBottom": "4px"}),
        html.Div(f"{o.text()} {o.unit}", style={"fontSize": "24px", "fontWeight": "700", "color": NAVY}),
    ], style={**CARD, "flex": "1", "padding": "14px 16px"}) for o in engine.highlights(r)]
    return html.Div(cards, style={"display": "flex", "gap": "14px", "marginBottom": "16px"})


def results_table(engine, r):
    head = html.Tr([html.Th(h, style={"textAlign": "left" if h == "Quantity" else "center",
                                       "padding": "8px 10px", "color": NAVY, "fontSize": "13px",
                                       "borderBottom": f"2px solid {LIGHT}"})
                    for h in ("Quantity", "Value", "Unit", "Basis")])
    rows = [head]
    for i, o in enumerate(engine.outputs(r)):
        bg = "white" if i % 2 == 0 else LIGHT
        rows.append(html.Tr([
            html.Td(o.label, style={"padding": "7px 10px", "fontSize": "13px", "color": INK}),
            html.Td(o.text(), style={"padding": "7px 10px", "fontSize": "13px", "textAlign": "center"}),
            html.Td(o.unit, style={"padding": "7px 10px", "fontSize": "13px", "textAlign": "center", "color": GREY}),
            html.Td(o.basis, style={"padding": "7px 10px", "fontSize": "12px", "textAlign": "center",
                                    "color": BASIS.get(o.basis, GREY)}),
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
    rows = [html.Tr([
        html.Td(spec.label,
                style={"padding": "4px 8px", "fontSize": "12px", "color": INK}),
        html.Td(f"{v[spec.key]:g} {spec.unit}",
                style={"padding": "4px 8px", "fontSize": "12px",
                       "textAlign": "right", "color": NAVY, "fontWeight": "600"}),
        html.Td((f"range {spec.min:g}\u2013{spec.max:g}" if spec.min is not None else ""),
                style={"padding": "4px 8px", "fontSize": "11px", "color": GREY}),
    ]) for spec in engine.inputs]
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


# ── OpenClaw gateway config (read once at import) ──────────────────────────
def _oc_gateway_config():
    """Return (base_url, bearer_token, provider_model) for the local OpenClaw gateway."""
    import json, os
    cfg_path = os.path.expanduser("~/.openclaw/openclaw.json")
    try:
        with open(cfg_path) as f:
            cfg = json.load(f)
        gw  = cfg.get("gateway", {})
        port  = gw.get("port", 18789)
        token = gw.get("auth", {}).get("token", "")
        return f"http://localhost:{port}/v1", token
    except Exception:
        return "http://localhost:18789/v1", ""

_OC_BASE_URL, _OC_TOKEN = _oc_gateway_config()


def call_ai_narrative(engine, v, r, model=None):
    """Call the OpenClaw local gateway (OpenAI-compat) for AI analysis. Falls back to direct Anthropic."""
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
    last_err = None

    # --- primary: OpenClaw local gateway via requests (no extra deps) ---
    try:
        import requests as _req
        url  = f"{_OC_BASE_URL}/chat/completions"
        body = {
            "model":      "openclaw/default",
            "max_tokens": 1400,
            "messages":   [{"role": "user", "content": prompt}],
        }
        auth_hdrs = {
            "Authorization": f"Bearer {_OC_TOKEN}",
            "Content-Type":  "application/json",
        }
        # Try with explicit model override first
        r = _req.post(url, headers={**auth_hdrs, "x-openclaw-model": f"anthropic/{model}"},
                      json=body, timeout=180)
        if r.status_code in (400, 404):
            # Model not in catalog or needs different params; retry with gateway default
            r = _req.post(url, headers=auth_hdrs, json=body, timeout=180)
            r.raise_for_status()
            model_used = f"gateway default  (anthropic/{model}: {r.status_code})"
        else:
            r.raise_for_status()
            model_used = f"anthropic/{model}  (via OpenClaw gateway)"
        text = r.json()["choices"][0]["message"]["content"]
    except Exception as e:
        last_err = f"{type(e).__name__}: {e}"

    # --- fallback: direct Anthropic SDK (needs ANTHROPIC_API_KEY in env) ---
    if text is None:
        try:
            import anthropic as _ant
            msg = _ant.Anthropic().messages.create(
                model=model, max_tokens=1400,
                messages=[{"role": "user", "content": prompt}])
            text = msg.content[0].text
            model_used = f"anthropic/{model}"
        except Exception as e:
            last_err = f"{last_err}  |  fallback: {type(e).__name__}: {e}"

    if text is None:
        return html.Div(
            f"AI unavailable. Error: {last_err}",
            style={"fontSize": "12px", "color": GREY}), None

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
        html.Button("+ Request a tool", id="req-open", n_clicks=0, style={
            "padding": "10px 16px", "borderRadius": "7px", "border": "1px solid white",
            "background": "transparent", "color": "white", "cursor": "pointer", "fontWeight": "600"}),
    ], style={"background": NAVY, "color": "white", "padding": "20px 28px", "display": "flex",
              "justifyContent": "space-between", "alignItems": "center"}),

    html.Div([
        html.Div([
            html.Label("System", style={"fontSize": "13px", "color": GREY, "fontWeight": "600"}),
            dcc.Dropdown(id="system", clearable=False, options=build_options(),
                         value=list_engines()[0][0], style={"marginBottom": "16px", "marginTop": "6px"}),
            html.Div(id="inputs"),
            _btn("Run", "run", primary=True),
        ], style={**CARD, "width": "300px", "alignSelf": "flex-start"}),

        html.Div([
            html.Div(id="status-bar"),
            html.Div(id="banner"),
            html.Div(id="highlights"),
            html.Div([
                dcc.Loading(type="circle", color=TEAL,
                            children=html.Img(id="chart", style={"width": "100%", "borderRadius": "8px"})),
            ], style={**CARD, "marginBottom": "16px"}),
            html.Div(id="results", style={**CARD, "marginBottom": "16px"}),
            html.Div(id="smart-section", style={"marginBottom": "16px"}),
            html.Div([
                html.Div([
                    html.Div("AI Analysis",
                             style={"fontWeight": "700", "color": NAVY, "fontSize": "14px"}),
                    dcc.Dropdown(
                        id="ai-model", clearable=False,
                        options=AI_MODELS, value=AI_MODEL_DEFAULT,
                        style={"width": "220px", "fontSize": "13px"}),
                ], style={"display": "flex", "alignItems": "center",
                          "justifyContent": "space-between", "marginBottom": "10px"}),
                _btn("\u26a1 AI Explain", "b-ai-explain"),
                dcc.Loading(type="dot", color=TEAL,
                            children=html.Div(id="ai-narrative",
                                             style={"marginTop": "12px", "minHeight": "20px"})),
            ], style={**CARD, "marginBottom": "16px"}),
            html.Div([
                _btn("Download PDF", "b-pdf"), _btn("Download Excel", "b-xlsx"), _btn("Download PPTX", "b-pptx"),
                html.Button("🧪 Open in DWSIM", id="b-dwsim", n_clicks=0, style={
                    "padding": "9px 16px", "borderRadius": "7px", "fontSize": "13px",
                    "fontWeight": "600", "marginRight": "10px", "cursor": "pointer",
                    "background": "#1A6B3C", "color": "white", "border": "1px solid #1A6B3C"}),
                dcc.Download(id="d-pdf"), dcc.Download(id="d-xlsx"), dcc.Download(id="d-pptx"), dcc.Download(id="d-dwsim"),
            ]),
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
            html.Div("Describe what you need. Cody drafts a conforming tool; it appears below as a draft "
                     "until you verify and promote it.", style={"fontSize": "13px", "color": GREY, "marginBottom": "12px"}),
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


@app.callback(
    Output("highlights", "children"), Output("results", "children"),
    Output("chart", "src"), Output("last", "data"), Output("banner", "children"),
    Output("status-bar", "children"), Output("smart-section", "children"),
    Input("run", "n_clicks"), Input("system", "value"),
    State({"type": "sysin", "key": ALL}, "value"), State({"type": "sysin", "key": ALL}, "id"))
def _run(_n, key, values, ids):
    engine = get(key)
    if values and ids and len(values) == len(engine.inputs):
        vals = {i["key"]: v for i, v in zip(ids, values)}
    else:
        vals = engine.defaults()
    r = engine.solve(vals)
    banner = None
    if engine.status == "draft":
        banner = html.Div(
            "Draft tool - generated skeleton, logic not filled, outputs unverified. "
            "Edit it through Request a tool, then verify and promote.",
            style={"background": "#FDEEEC", "border": f"1px solid {RED}", "color": RED,
                   "padding": "10px 14px", "borderRadius": "8px", "marginBottom": "14px", "fontSize": "13px"})
    status_bar = html.Div([
        html.Span("\u2713  ", style={"fontWeight": "700"}),
        html.Span(f"Calculation complete \u2014 {engine.name}"),
    ], style={"background": "#E8F8F5", "border": f"1px solid {TEAL}", "borderRadius": "8px",
              "padding": "9px 14px", "marginBottom": "14px", "fontSize": "13px",
              "color": TEAL, "fontWeight": "600"})
    return (highlight_cards(engine, r), results_table(engine, r), chart_src(engine, r),
            {"key": key, "vals": vals}, banner, status_bar,
            build_smart_section(engine, vals, r))


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
              prevent_initial_call=True)
def _ai_explain(_n, data, model):
    if not data:
        return html.Div("Run a calculation first, then click AI Explain.",
                        style={"fontSize": "12px", "color": GREY}), None
    engine = get(data["key"])
    vals   = data["vals"]
    r      = engine.solve(vals)
    html_div, plain_text = call_ai_narrative(engine, vals, r, model=model or AI_MODEL_DEFAULT)
    return html_div, plain_text


def _report(data, kind, ai_text=None):
    engine = get(data["key"]); vals = data["vals"]; r = engine.solve(vals)
    d = tempfile.mkdtemp(); slug = data["key"]
    if kind == "pdf":
        p = f"{d}/{slug}.pdf"; build_pdf(engine, vals, r, p, f"{d}/c.png", ai_text=ai_text)
    elif kind == "xlsx":
        p = f"{d}/{slug}.xlsx"; build_excel(engine, vals, r, p, ai_text=ai_text)
    else:
        p = f"{d}/{slug}.pptx"; build_pptx(engine, vals, r, p, f"{d}/c.png", ai_text=ai_text)
    return dcc.send_file(p)


@app.callback(Output("d-pdf", "data"), Input("b-pdf", "n_clicks"),
              State("last", "data"), State("ai-text", "data"), prevent_initial_call=True)
def _dl_pdf(_n, data, ai_text):
    return _report(data, "pdf", ai_text=ai_text)


@app.callback(Output("d-xlsx", "data"), Input("b-xlsx", "n_clicks"),
              State("last", "data"), State("ai-text", "data"), prevent_initial_call=True)
def _dl_xlsx(_n, data, ai_text):
    return _report(data, "xlsx", ai_text=ai_text)


@app.callback(Output("d-pptx", "data"), Input("b-pptx", "n_clicks"),
              State("last", "data"), State("ai-text", "data"), prevent_initial_call=True)
def _dl_pptx(_n, data, ai_text):
    return _report(data, "pptx", ai_text=ai_text)


@app.callback(Output("d-dwsim", "data"), Input("b-dwsim", "n_clicks"),
              State("last", "data"), prevent_initial_call=True)
def _dl_dwsim(_n, data):
    import traceback
    try:
        if not data:
            print("[DWSIM] No simulation data — run first")
            return no_update
        if _dwsim_build_flowsheet is None:
            print("[DWSIM] Export module not loaded")
            return no_update
        print(f"[DWSIM] Building flowsheet for {data['key']}")
        engine = get(data["key"])
        vals   = data["vals"]
        r      = engine.solve(vals)
        xml    = _dwsim_build_flowsheet(engine, vals, r)
        slug   = engine.name.replace(" ", "_").replace("—", "-")[:50]
        fname  = f"{slug}.dwxml"
        print(f"[DWSIM] Generated {len(xml):,} chars → {fname}")
        return dict(content=xml, filename=fname, type="application/xml", base64=False)
    except Exception:
        print("[DWSIM] ERROR:", traceback.format_exc())
        return no_update


if __name__ == "__main__":
    app.run(debug=True, port=8050, use_reloader=True)
