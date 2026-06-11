"""
Tool-builder substrate.

This is the safe, deterministic half of "describe a tool and it appears":
 - save_request(text)        records what was asked for (provenance + audit)
 - scaffold_tool(spec)       writes a CONFORMING DRAFT module from a template and
                             registers it, so it shows up in the dropdown badged "draft"

The other half - turning a free-text request into a filled spec and real solve()
logic - is the agent's job (Cody), and it runs sandboxed and stays "draft" until you
verify and promote it. Cody fills the template; it never writes free-form architecture,
which is what keeps every generated tool uniform and reviewable.
"""
import json
import os
import re
import time
from dataclasses import dataclass, asdict

from .contract import InputSpec, OutputSpec, Engine, register

DRAFTS_DIR = os.path.join(os.path.dirname(__file__), "..", "engines", "drafts")
REQUESTS_LOG = os.path.join(os.path.dirname(__file__), "..", "data", "requests.jsonl")


@dataclass
class ToolRequest:
    id: str
    text: str
    kind: str
    created: float


def _slug(text):
    s = re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")
    return (s[:40] or "tool")


def save_request(text, kind="simulator"):
    os.makedirs(os.path.dirname(REQUESTS_LOG), exist_ok=True)
    req = ToolRequest(id=f"req_{int(time.time())}", text=text, kind=kind, created=time.time())
    with open(REQUESTS_LOG, "a") as f:
        f.write(json.dumps(asdict(req)) + "\n")
    return req


def scaffold_tool(key, name, kind, inputs, request_text, outdir=None):
    """Write a conforming DRAFT tool module and register it. Returns the module path.

    inputs: list of (key, label, unit, default). solve() is a stub the agent fills.
    """
    outdir = outdir or DRAFTS_DIR
    os.makedirs(outdir, exist_ok=True)
    open(os.path.join(outdir, "__init__.py"), "a").close()
    cls = "Draft_" + re.sub(r"[^A-Za-z0-9]", "_", key)
    in_lines = ",\n        ".join(
        f'InputSpec("{k}", "{lbl}", "{u}", {d})' for (k, lbl, u, d) in inputs)
    out_lines = ",\n            ".join(
        f'OutputSpec("{lbl}", v["{k}"], "{u}", "unverified", "{{:.2f}}")'
        for (k, lbl, u, d) in inputs)
    code = f'''"""DRAFT tool - generated from a request. Logic not filled. Not verified."""
from ...framework.contract import Engine, InputSpec, OutputSpec, register


@register
class {cls}(Engine):
    key = "{key}"
    name = "{name}"
    kind = "{kind}"
    status = "draft"
    provenance = {request_text!r}
    notes = ("Draft skeleton generated from a request. The agent has not filled the "
             "real logic yet, so outputs echo the inputs and are marked unverified. "
             "Review, fill solve(), verify, then promote to trusted.")
    inputs = [
        {in_lines}
    ]

    def solve(self, v):
        # TODO (Cody, sandboxed): implement the real logic for this tool.
        return dict(v)

    def outputs(self, v):
        return [
            {out_lines}
        ]
'''
    path = os.path.join(outdir, f"{key}.py")
    with open(path, "w") as f:
        f.write(code)
    # register at runtime by importing the freshly written module
    import importlib
    mod = importlib.import_module(f"nexa_toolkit.engines.drafts.{key}")
    return path


# --- tool kinds: expandable, new kinds added on the go ---
KINDS_FILE = os.path.join(os.path.dirname(__file__), "..", "data", "kinds.json")
_DEFAULT_KINDS = ["simulator", "document", "integration"]


def load_kinds():
    try:
        with open(KINDS_FILE) as f:
            ks = json.load(f)
    except Exception:
        ks = list(_DEFAULT_KINDS)
    for k in _DEFAULT_KINDS:
        if k not in ks:
            ks.append(k)
    return ks


def add_kind(kind):
    kind = (kind or "").strip().lower()
    if kind:
        ks = load_kinds()
        if kind not in ks:
            ks.append(kind)
            os.makedirs(os.path.dirname(KINDS_FILE), exist_ok=True)
            with open(KINDS_FILE, "w") as f:
                json.dump(ks, f)
    return load_kinds()
