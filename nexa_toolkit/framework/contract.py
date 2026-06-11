"""
Engine contract for the Nexa toolkit.

Every system (LiBr chiller, GPU cassette, desalination, gas turbine, whole plant)
implements this one interface. The reporting layer, the UI and the MCP exposure
are all generic - they read the contract, so a new system is a drop-in module,
not a new app.
"""
from dataclasses import dataclass


@dataclass
class InputSpec:
    key: str
    label: str
    unit: str
    default: float
    min: float = None
    max: float = None
    choices: dict = None   # {label: numeric_value} — renders as dropdown; None → plain number input


@dataclass
class OutputSpec:
    label: str
    value: float
    unit: str
    basis: str = "screening"      # verified | screening | input
    fmt: str = "{:.2f}"

    def text(self):
        try:
            return self.fmt.format(self.value)
        except Exception:
            return str(self.value)


class Engine:
    """Base tool. Subclasses set key/name/notes/inputs and implement solve+outputs.

    kind       : "simulator" | "document" | "integration"  - drives review + permissions
    status     : "trusted" | "draft"                        - draft = generated, unverified
    provenance : the request text a generated tool came from (None for hand-authored)
    """
    key = "base"
    name = "Base engine"
    notes = ""
    inputs = []
    kind = "simulator"
    status = "trusted"
    provenance = None

    def defaults(self):
        return {i.key: i.default for i in self.inputs}

    def solve(self, values: dict) -> dict:
        raise NotImplementedError

    def outputs(self, result: dict):          # -> list[OutputSpec]  (full results)
        raise NotImplementedError

    def highlights(self, result: dict):       # -> list[OutputSpec]  (KPI subset)
        return self.outputs(result)[:3]

    def chart(self, result: dict, path: str):  # optional signature chart -> path or None
        return None


REGISTRY = {}


def register(engine_cls):
    inst = engine_cls()
    REGISTRY[inst.key] = inst
    return engine_cls


def get(key):
    return REGISTRY[key]


def list_engines():
    return [(e.key, e.name) for e in REGISTRY.values()]
