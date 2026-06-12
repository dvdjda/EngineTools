"""
simulators.gt_system.feasibility — system-level resource balance checks.

Strictly separate from solver convergence. "Converged" only means the
Wegstein loops settled to a fixed point. Feasibility asks a different
question per resource:

  Power balance   — can the GT supply its own electrical load
                    (GPU IT × PUE + itemised plant aux)?
  Cooling balance — does the LiBr deliver enough cooling capacity to
                    absorb the GPU heat dump?

A single FeasibilityStatus aggregates a list of ResourceBalance objects.
Adding a future resource (steam, seawater, ...) is one new helper that
returns a ResourceBalance — the renderer iterates whatever's in the list.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from nexablock.blocks import (GasTurbine, GPUCassette, MED, LiBrChiller,
                              CoolingTower)


POWER_ASSUMPTION = (
    "GT-powered: the GPU + plant electrical load is drawn from the GT "
    "electrical bus. No external grid import; GT must supply all demand."
)

COOLING_ASSUMPTION = (
    "Single-phase immersion: all GPU electrical input dissipates as heat "
    "into the coolant. LiBr Q_cool is the only modelled cooling source — "
    "no economiser, no dry cooler, no free-cooling bypass."
)


# ── data types ───────────────────────────────────────────────────────────────

@dataclass
class ResourceBalance:
    """One resource (power, cooling, ...) reduced to a supply/demand balance."""
    resource:   str               # title that the renderer uses, e.g. "Power"
    unit:       str
    feasible:   bool
    supply:     float
    demand:     float
    balance:    float             # signed; + surplus, − deficit
    shortfall:  float             # max(0, -balance); 0 when feasible
    assumption: str
    breakdown:  dict = field(default_factory=dict)


@dataclass
class FeasibilityStatus:
    """Aggregate over every modelled resource balance."""
    balances: list = field(default_factory=list)

    @property
    def feasible(self) -> bool:
        return all(b.feasible for b in self.balances)

    def by(self, resource: str) -> ResourceBalance:
        for b in self.balances:
            if b.resource == resource:
                return b
        raise KeyError(
            f"resource {resource!r} not found; "
            f"have {[b.resource for b in self.balances]}")


# ── helpers ──────────────────────────────────────────────────────────────────

def _first(solved, cls):
    return next((b for b in solved.blocks if isinstance(b, cls)), None)


def _read(block, label):
    if block is None:
        return 0.0
    res = block.results.get(label)
    return res.value if res is not None else 0.0


def _make(resource, unit, supply, demand, assumption, breakdown):
    """Common assembly path for a ResourceBalance."""
    balance   = supply - demand
    feasible  = balance >= 0
    shortfall = max(0.0, -balance)
    return ResourceBalance(
        resource=resource, unit=unit,
        feasible=feasible,
        supply=supply, demand=demand,
        balance=balance, shortfall=shortfall,
        assumption=assumption, breakdown=breakdown,
    )


# ── per-resource balances ────────────────────────────────────────────────────

def power_balance(solved, assumption: str = POWER_ASSUMPTION,
                  bop_frac: float = 0.010) -> ResourceBalance:
    """Electrical supply/demand. Supply: GT actual power. Demand: GPU IT × PUE
    plus itemised aux (MED, LiBr pumps, CT fans, GT aux, Plant BoP)."""
    gt   = _first(solved, GasTurbine)
    gpu  = _first(solved, GPUCassette)
    med  = _first(solved, MED)
    libr = _first(solved, LiBrChiller)
    ct   = _first(solved, CoolingTower)

    gen_kW = _read(gt, "GT actual power")

    it_kW         = _read(gpu, "IT power")
    pue           = _read(gpu, "PUE  (approx)") if gpu is not None else 1.0
    gpu_demand_kW = it_kW * (pue if pue > 0 else 1.0)

    med_aux_kW  = _read(med,  "MED electrical")
    libr_aux_kW = _read(libr, "LiBr pump electrical")
    ct_aux_kW   = _read(ct,   "CT fan electrical")
    gt_aux_kW   = _read(gt,   "GT aux electrical")
    bop_aux_kW  = max(0.0, bop_frac) * gen_kW

    demand_kW = (gpu_demand_kW + med_aux_kW + libr_aux_kW
                 + ct_aux_kW + gt_aux_kW + bop_aux_kW)

    breakdown = {
        "GT actual power":                gen_kW,
        "GPU IT × PUE":                   gpu_demand_kW,
        "MED electrical (pumps)":         med_aux_kW,
        "LiBr pump electrical":           libr_aux_kW,
        "Cooling tower fan electrical":   ct_aux_kW,
        "GT auxiliaries":                 gt_aux_kW,
        "Plant BoP (lights/HVAC)":        bop_aux_kW,
    }
    return _make("Power", "kW", gen_kW, demand_kW, assumption, breakdown)


def cooling_balance(solved, assumption: str = COOLING_ASSUMPTION) -> ResourceBalance:
    """Cooling supply/demand. Supply: LiBr Q_cool. Demand: GPU heat dump.

    Heat dump = IT × (1 + aux_frac) = the "Heat load" the GPU block already
    computes. Equals the GPU's electrical demand for immersion cooling
    (all electrical → heat), but the two checks are independent: GT could
    supply the kW and still not have enough Q_cool, or vice versa."""
    libr = _first(solved, LiBrChiller)
    gpu  = _first(solved, GPUCassette)

    supply_kW = _read(libr, "Cooling capacity kW")
    demand_kW = _read(gpu,  "Heat load")

    breakdown = {
        "LiBr cooling capacity":  supply_kW,
        "GPU heat load":          demand_kW,
    }
    return _make("Cooling capacity", "kW", supply_kW, demand_kW,
                 assumption, breakdown)


# ── aggregate ────────────────────────────────────────────────────────────────

def feasibility(solved, *, bop_frac: float = 0.010) -> FeasibilityStatus:
    """Run every resource balance and return the aggregate. Order matters
    only for renderer display: power first, then cooling."""
    return FeasibilityStatus(balances=[
        power_balance(solved,   bop_frac=bop_frac),
        cooling_balance(solved),
    ])
