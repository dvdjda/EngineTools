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
    "Supply is the GT derated capacity at site ambient (the available "
    "envelope). Operating point and operating headroom shown for context. "
    "Demand is itemised at the current operating point; aux loads scale "
    "with current output, not with the derated ceiling."
)

COOLING_ASSUMPTION = (
    "Single-phase immersion: all GPU silicon power plus cassette overhead "
    "dissipate as heat into the coolant. LiBr Q_cool is the only modelled "
    "cooling source — no economiser, no dry cooler, no free-cooling bypass."
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
    """Electrical supply/demand.

    Supply: GT *derated* capacity (the ambient-corrected ceiling — what the
            GT can deliver at full load), not the current operating point.
    Demand: GPU silicon + cassette overhead + itemised plant aux
            (MED pumps, LiBr pumps, CT fans, GT aux, plant BoP).
    """
    gt   = _first(solved, GasTurbine)
    gpu  = _first(solved, GPUCassette)
    med  = _first(solved, MED)
    libr = _first(solved, LiBrChiller)
    ct   = _first(solved, CoolingTower)

    derated_kW = _read(gt, "GT derated capacity")            # supply ceiling
    actual_kW  = _read(gt, "GT actual power")                # operating point (info)
    headroom_kW = derated_kW - actual_kW

    silicon_kW   = _read(gpu, "IT power")
    overhead_kW  = _read(gpu, "Cassette overhead electrical")

    med_aux_kW  = _read(med,  "MED electrical")
    libr_aux_kW = _read(libr, "LiBr pump electrical")
    ct_aux_kW   = _read(ct,   "CT fan electrical")
    gt_aux_kW   = _read(gt,   "GT aux electrical")
    bop_aux_kW  = max(0.0, bop_frac) * actual_kW             # scales with current operating point

    demand_kW = (silicon_kW + overhead_kW + med_aux_kW + libr_aux_kW
                 + ct_aux_kW + gt_aux_kW + bop_aux_kW)

    breakdown = {
        "GT derated capacity (available)": derated_kW,
        "GT current output (info)":        actual_kW,
        "Operating headroom (info)":       headroom_kW,
        "GPU silicon (IT power)":          silicon_kW,
        "Cassette overhead (pumps/ctl)":   overhead_kW,
        "MED electrical (pumps)":          med_aux_kW,
        "LiBr pump electrical":            libr_aux_kW,
        "Cooling tower fan electrical":    ct_aux_kW,
        "GT auxiliaries":                  gt_aux_kW,
        "Plant BoP (lights/HVAC)":         bop_aux_kW,
    }
    return _make("Power", "kW", derated_kW, demand_kW, assumption, breakdown)


def cooling_balance(solved, assumption: str = COOLING_ASSUMPTION) -> ResourceBalance:
    """Cooling supply/demand. Supply: LiBr Q_cool. Demand: GPU silicon heat
    + cassette overhead heat. Both dissipate into the immersion coolant."""
    libr = _first(solved, LiBrChiller)
    gpu  = _first(solved, GPUCassette)

    supply_kW   = _read(libr, "Cooling capacity kW")
    silicon_kW  = _read(gpu,  "IT power")
    overhead_kW = _read(gpu,  "Cassette overhead electrical")
    demand_kW   = silicon_kW + overhead_kW

    breakdown = {
        "LiBr cooling capacity":  supply_kW,
        "GPU silicon heat":       silicon_kW,
        "Cassette overhead heat": overhead_kW,
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
