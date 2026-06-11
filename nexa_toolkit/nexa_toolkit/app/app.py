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
import os
import tempfile
import time

import dash
from dash import dcc, html, Input, Output, State, ALL, ctx

import nexa_toolkit.engines  # noqa: F401  (registers the systems)
from nexa_toolkit.framework import list_engines, get, REGISTRY
from nexa_toolkit.framework.builder import save_request, scaffold_tool, _slug, load_kinds, add_kind
from nexa_toolkit.reporting.generic_report import (
    build_chart, build_excel, build_pdf, build_pptx)

NAVY = "#2E4E7E"; TEAL = "#2BB6A3"; LIGHT = "#EAF0F8"; GREY = "#5b6675"
INK = "#22303F"; BG = "#f4f7fb"; LINE = "#dbe2ee"; RED = "#C0392B"
BASIS = {"verified": "#2E7D4E", "screening": "#B26A00", "input": "#5b6675", "unverified": RED}

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


def input_fields(engine):
    out = []
    for s in engine.inputs:
        out.append(html.Div([
            html.Label(f"{s.label}  ({s.unit})",
                       style={"fontSize": "13px", "color": GREY, "display": "block", "marginBottom": "4px"}),
            dcc.Input(id={"type": "sysin", "key": s.key}, type="number", value=s.default,
                      style={"width": "100%", "padding": "8px 10px", "border": f"1px solid {LINE}",
                             "borderRadius": "6px", "fontSize": "14px", "boxSizing": "border-box"}),
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
    d = tempfile.mkdtemp(); p = os.path.join(d, "c.png")
    build_chart(engine, r, p)
    return "data:image/png;base64," + base64.b64encode(open(p, "rb").read()).decode()


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
            html.Div(id="banner"),
            html.Div(id="highlights"),
            html.Div([html.Img(id="chart", style={"width": "100%", "borderRadius": "8px"})],
                     style={**CARD, "marginBottom": "16px"}),
            html.Div(id="results", style={**CARD, "marginBottom": "16px"}),
            html.Div([
                _btn("Download PDF", "b-pdf"), _btn("Download Excel", "b-xlsx"), _btn("Download PPTX", "b-pptx"),
                dcc.Download(id="d-pdf"), dcc.Download(id="d-xlsx"), dcc.Download(id="d-pptx"),
            ]),
        ], style={"flex": "1"}),
    ], style={"display": "flex", "gap": "20px", "padding": "22px 28px", "maxWidth": "1200px", "margin": "0 auto"}),

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
], style={"background": BG, "minHeight": "100vh", "fontFamily": "Arial, Helvetica, sans-serif"})


@app.callback(Output("inputs", "children"), Input("system", "value"))
def _build_inputs(key):
    return input_fields(get(key))


@app.callback(
    Output("highlights", "children"), Output("results", "children"),
    Output("chart", "src"), Output("last", "data"), Output("banner", "children"),
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
    return (highlight_cards(engine, r), results_table(engine, r), chart_src(engine, r),
            {"key": key, "vals": vals}, banner)


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


def _report(data, kind):
    engine = get(data["key"]); vals = data["vals"]; r = engine.solve(vals)
    d = tempfile.mkdtemp(); slug = data["key"]
    if kind == "pdf":
        p = f"{d}/{slug}.pdf"; build_pdf(engine, vals, r, p, f"{d}/c.png")
    elif kind == "xlsx":
        p = f"{d}/{slug}.xlsx"; build_excel(engine, vals, r, p)
    else:
        p = f"{d}/{slug}.pptx"; build_pptx(engine, vals, r, p, f"{d}/c.png")
    return dcc.send_file(p)


@app.callback(Output("d-pdf", "data"), Input("b-pdf", "n_clicks"), State("last", "data"), prevent_initial_call=True)
def _dl_pdf(_n, data):
    return _report(data, "pdf")


@app.callback(Output("d-xlsx", "data"), Input("b-xlsx", "n_clicks"), State("last", "data"), prevent_initial_call=True)
def _dl_xlsx(_n, data):
    return _report(data, "xlsx")


@app.callback(Output("d-pptx", "data"), Input("b-pptx", "n_clicks"), State("last", "data"), prevent_initial_call=True)
def _dl_pptx(_n, data):
    return _report(data, "pptx")


if __name__ == "__main__":
    app.run(debug=False, port=8050)
