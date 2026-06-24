"""Generic REST exposure of the tool registry — a sibling to the UI and reporting layers.

It reads the one contract, so a tool shows up over HTTP with zero per-tool code (the same way it
gets its UI panel and its reports for free). This is how APEX (the AI surface) discovers tools
DYNAMICALLY: promote a tool to `trusted` and it appears here; demote it to `draft` and it vanishes.
**Draft tools are never exposed** — APEX must never see unverified work.

Mounted on the existing Dash Flask server (`app.server`) — no new service/port.
See the apex repo's `ENGINETOOLS_APEX_CONTRACT.md` for the consuming side.
"""
from flask import jsonify, request

from .contract import REGISTRY


def _manifest(e):
    """Serialize a tool's contract for APEX (the discovery 'manifest' is generated from code,
    not hand-authored)."""
    return {
        "id": e.key,
        "title": e.name,
        "notes": getattr(e, "notes", "") or "",
        "kind": getattr(e, "kind", "simulator"),
        "status": getattr(e, "status", "draft"),
        "provenance": getattr(e, "provenance", None),
        "inputs": [
            {"key": i.key, "label": i.label, "unit": i.unit, "default": i.default,
             "min": i.min, "max": i.max, "choices": i.choices}
            for i in e.inputs
        ],
    }


def _trusted():
    return [e for e in REGISTRY.values() if getattr(e, "status", "draft") == "trusted"]


def attach_rest(server):
    """Add the read-only discovery routes to the Flask server. Phase 1 = discovery + the draft gate;
    /simulate, /requests and report endpoints come in later phases of the contract."""

    @server.route("/simulators")
    def _list_simulators():                       # trusted only — drafts excluded by construction
        return jsonify({"simulators": [_manifest(e) for e in _trusted()]})

    @server.route("/simulators/<key>")
    def _get_simulator(key):                      # call-time gate: draft/unknown → 404 (never run)
        e = REGISTRY.get(key)
        if e is None or getattr(e, "status", "draft") != "trusted":
            return jsonify({"error": "not found or not trusted"}), 404
        return jsonify(_manifest(e))

    @server.route("/simulate", methods=["POST"])
    def _simulate():
        """Run a TRUSTED tool with a config and return its KPIs (deterministic — code owns the
        numbers). Draft/unknown → 404 (never run). Unknown config keys are ignored (echoed back);
        the rest fall back to the tool's defaults."""
        body = request.get_json(silent=True) or {}
        e = REGISTRY.get(body.get("simulator_id") or body.get("id"))
        if e is None or getattr(e, "status", "draft") != "trusted":
            return jsonify({"error": "not found or not trusted"}), 404
        cfg = body.get("config") or {}
        keys = {i.key for i in e.inputs}
        ignored = [k for k in cfg if k not in keys]
        values = {**e.defaults(), **{k: v for k, v in cfg.items() if k in keys}}
        try:
            result = e.solve(values)
            outs = e.outputs(result)
        except Exception as exc:                              # solver ran but failed → 422
            return jsonify({"error": f"solve failed: {exc}", "simulator_id": e.key}), 422
        return jsonify({
            "simulator_id": e.key, "title": e.name, "status": e.status,
            "config_used": {k: values[k] for k in keys if k in values},
            "ignored_inputs": ignored,
            "kpis": [{"label": o.label, "value": o.value, "unit": o.unit,
                      "basis": o.basis, "text": o.text()} for o in outs],
        })

    @server.route("/healthz")
    def _healthz():
        return jsonify({"ok": True, "trusted": len(_trusted()), "total": len(REGISTRY)})

    return server
