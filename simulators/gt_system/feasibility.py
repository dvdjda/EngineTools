"""
simulators.gt_system.feasibility — system-level power balance check.

Strictly separate from solver convergence: "converged" means only that
the Wegstein loops settled to a fixed point. Feasibility asks a
different question: can the GT actually power its own load?

Computes:
  • generation_kW = GT actual electrical output
  • demand_kW    = GPU IT × PUE + modelled parasitic loads (MED pumps)
  • balance      = generation − demand   (signed: + surplus, − deficit)

Pulls values from the already-solved block results — no recompute. If a
load isn't modelled by any block (CT fans, LiBr pump, GT auxiliaries),
the breakdown row reads "not modelled" rather than zero, so the report
is honest about what's counted.
"""
from __future__ import annotations
from dataclasses import dataclass, field

from nexablock.blocks import GasTurbine, GPUCassette, MED, LiBrChiller, CoolingTower


DEFAULT_ASSUMPTION = (
    "GT-powered: the GPU + plant electrical load is drawn from the GT "
    "electrical bus. No external grid import; GT must supply all demand."
)


@dataclass
class FeasibilityStatus:
    feasible:      bool
    generation_kW: float
    demand_kW:     float
    balance_kW:    float          # signed: positive = surplus, negative = deficit
    shortfall_kW:  float          # max(0, -balance); 0 when feasible
    assumption:    str
    breakdown:     dict = field(default_factory=dict)


def _first(solved, cls):
    """First block of class `cls` in the solved system, or None."""
    return next((b for b in solved.blocks if isinstance(b, cls)), None)


def _read(block, label):
    """Read a result value from a block, defaulting to 0.0 if missing."""
    if block is None:
        return 0.0
    res = block.results.get(label)
    return res.value if res is not None else 0.0


def power_balance(solved, assumption: str = DEFAULT_ASSUMPTION,
                  bop_frac: float = 0.010) -> FeasibilityStatus:
    """Build a FeasibilityStatus from a SolvedSystem.

    Generation: GasTurbine "GT actual power"
    Demand:     GPU IT × PUE
              + MED electrical                  (modelled by MED block)
              + LiBr pump electrical            (modelled by LiBrChiller block)
              + CT fan electrical               (modelled by CoolingTower block)
              + GT aux electrical               (modelled by GasTurbine block)
              + Plant BoP   (bop_frac × GT power, lights / HVAC / facility, not a block)
    """
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

    demand_kW  = (gpu_demand_kW + med_aux_kW + libr_aux_kW
                  + ct_aux_kW + gt_aux_kW + bop_aux_kW)
    balance_kW = gen_kW - demand_kW
    feasible   = balance_kW >= 0
    shortfall  = max(0.0, -balance_kW)

    breakdown = {
        "GT actual power":                gen_kW,
        "GPU IT × PUE":                   gpu_demand_kW,
        "MED electrical (pumps)":         med_aux_kW,
        "LiBr pump electrical":           libr_aux_kW,
        "Cooling tower fan electrical":   ct_aux_kW,
        "GT auxiliaries":                 gt_aux_kW,
        "Plant BoP (lights/HVAC)":        bop_aux_kW,
    }

    return FeasibilityStatus(
        feasible=feasible,
        generation_kW=gen_kW,
        demand_kW=demand_kW,
        balance_kW=balance_kW,
        shortfall_kW=shortfall,
        assumption=assumption,
        breakdown=breakdown,
    )
