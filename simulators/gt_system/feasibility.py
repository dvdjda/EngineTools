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
                              Radiator)


POWER_ASSUMPTION_ISLAND = (
    "Island bus closure: GT actual power = GPU + cassette overhead + plant "
    "aux + external load. No grid backstop — excess electrical has nowhere "
    "to go (a non-zero positive imbalance means the flowsheet didn't close "
    "and convergence is suspect). Screening tolerance 2.5% absorbs "
    "controller-vs-block precision noise."
)

POWER_ASSUMPTION_GRID = (
    "Grid-tied (export-only) bus closure: GT actual power = NEXA demand + "
    "grid export. Surplus electrical exports automatically; imports are "
    "forbidden. Grid export equals GT actual − NEXA demand (positive only). "
    "Screening tolerance 2.5% absorbs controller-vs-block precision noise."
)

POWER_TOL_REL = 0.025      # 2.5% screening tolerance for bus closure

COOLING_ASSUMPTION = (
    "Single-phase immersion: all GPU silicon power plus cassette overhead "
    "dissipate as heat into the coolant. LiBr Q_cool is the only modelled "
    "cooling source — no economiser, no dry cooler, no free-cooling bypass. "
    "Screening tolerance: shortfalls within 2.5% of demand are below the "
    "controller-vs-block precision floor and read as OK; only larger gaps "
    "are flagged as cooling deficits."
)

COOLING_TOL_REL = 0.025      # 2.5% screening tolerance — see assumption above


# ── data types ───────────────────────────────────────────────────────────────

@dataclass
class ResourceBalance:
    """One resource (power, cooling, ...) reduced to a supply/demand balance.

    Screening tolerance: small gaps within `tol_rel × demand` are screening-
    fidelity noise (analytical-vs-block precision in the controller, prop-
    table rounding, fixed-reference t_amb approximations). They DO NOT
    constitute engineering deficits and don't flag the balance as
    infeasible. Real shortfalls beyond the tolerance do.
    """
    resource:   str               # title that the renderer uses, e.g. "Power"
    unit:       str
    feasible:   bool
    supply:     float
    demand:     float
    balance:    float             # signed; + surplus, − deficit
    shortfall:  float             # max(0, -balance); 0 when feasible
    assumption: str
    breakdown:  dict = field(default_factory=dict)
    tol_rel:    float = 0.0       # screening tolerance applied at construction


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


def _make(resource, unit, supply, demand, assumption, breakdown, *,
          tol_rel: float = 0.0, closure: bool = False):
    """Common assembly path for a ResourceBalance with optional screening tolerance.

    closure=False (default, used for cooling): only deficit (supply < demand)
        is a problem. Shortfalls within tol_rel × demand are screening noise.
    closure=True (used for power): the bus must CLOSE — both excess (supply >
        demand, no sink) and deficit (supply < demand, no source) violate
        conservation. |balance| within tol_rel × demand is OK; outside it,
        flag with the appropriate direction.
    """
    balance   = supply - demand
    threshold = tol_rel * max(abs(demand), 1e-12)
    if closure:
        feasible = abs(balance) <= threshold
        shortfall = 0.0 if feasible else abs(balance)
    else:
        raw_short = max(0.0, -balance)
        feasible = raw_short <= threshold
        shortfall = 0.0 if feasible else raw_short
    return ResourceBalance(
        resource=resource, unit=unit,
        feasible=feasible,
        supply=supply, demand=demand,
        balance=balance, shortfall=shortfall,
        assumption=assumption, breakdown=breakdown,
        tol_rel=tol_rel,
    )


# ── per-resource balances ────────────────────────────────────────────────────

def power_balance(solved, assumption: str | None = None,
                  bop_frac: float = 0.010) -> ResourceBalance:
    """Electrical supply/demand on the bus.

    Supply: GT *net* power = gross − GT auxiliaries. GT aux is the package's
            own parasitic (an internal de-rate), so it never appears on the
            bus — the bus sees the net output only.
    Demand: GPU silicon + cassette overhead + the itemised plant electrical
            from `plant_loads` (each pump P=Q·ΔP/η, the VSD dry-cooler fan,
            container HVAC, lights).
    """
    from .plant_loads import plant_loads
    gt  = _first(solved, GasTurbine)
    gpu = _first(solved, GPUCassette)

    derated_kW = _read(gt, "GT derated capacity")            # info only
    gross_kW   = _read(gt, "GT actual power")                # info only
    gt_aux_kW  = _read(gt, "GT aux electrical")              # internal derate
    net_kW     = _read(gt, "GT net power")                   # SUPPLY to the bus

    silicon_kW  = _read(gpu, "IT power")
    overhead_kW = _read(gpu, "Cassette overhead electrical")

    p  = getattr(solved, "params", None)
    pl = plant_loads(solved, p) if p is not None else {"items": {}, "total": 0.0}
    plant_total = pl["total"]

    cs = getattr(solved, "control", None)
    operating_mode = getattr(solved, "operating_mode", "island")
    external_load_kW = cs.external_load_kW if cs is not None else 0.0
    grid_export_kW   = cs.grid_export_kW   if cs is not None else 0.0

    if assumption is None:
        assumption = (POWER_ASSUMPTION_GRID if operating_mode == "grid_tied"
                       else POWER_ASSUMPTION_ISLAND)

    nexa_demand = silicon_kW + overhead_kW + plant_total

    # Breakdown reflects the bus equation: SUPPLY = GT net; DEMAND = consumers.
    # GT gross + GT aux are shown as info (the derate that produced net).
    breakdown = {
        "GT net power (supply)":            +net_kW,
        "GT gross power":                    gross_kW,        # info only
        "GT auxiliaries (internal derate)":  gt_aux_kW,       # info only
        "Derated capacity (max available)":  derated_kW,      # info only
        "GPU silicon (IT power)":            silicon_kW,
        "Cassette overhead (pumps/ctl)":     overhead_kW,
    }
    breakdown.update(pl.get("items", {}))                     # itemised plant aux
    if operating_mode == "island":
        breakdown["External load (island, manual)"] = external_load_kW
        demand_kW = nexa_demand + external_load_kW
    else:  # grid_tied
        breakdown["Grid export (sent to grid)"] = grid_export_kW
        demand_kW = nexa_demand + grid_export_kW

    # closure=True so BOTH excess and deficit flag (bus must close).
    return _make("Power", "kW", net_kW, demand_kW, assumption, breakdown,
                  tol_rel=POWER_TOL_REL, closure=True)


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
                 assumption, breakdown, tol_rel=COOLING_TOL_REL)


# ── aggregate ────────────────────────────────────────────────────────────────

def feasibility(solved, *, bop_frac: float = 0.010) -> FeasibilityStatus:
    """Run every resource balance and return the aggregate. Order matters
    only for renderer display: power first, then cooling."""
    return FeasibilityStatus(balances=[
        power_balance(solved,   bop_frac=bop_frac),
        cooling_balance(solved),
    ])
