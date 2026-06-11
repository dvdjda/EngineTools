"""
nexablock.core.recycle — Explicit Recycle / EnergyRecycle block.

User-placed tear block that makes recycle loops self-documenting.
The solver will treat any connection through a Recycle block as a tear stream.
"""
from __future__ import annotations
from .block  import Block
from .port   import Port
from .stream import Stream, StreamKind
from .quantity import Param, Result


class Recycle(Block):
    """
    One inlet → one outlet of the same StreamKind.
    Inlet ≈ outlet at convergence (verified by the solver).
    Place this block in a loop to make the tear stream explicit.
    """
    category = "Utility"

    def __init__(self, kind: StreamKind = StreamKind.WATER_STEAM,
                 tol: float = 1e-4, label: str = "Recycle") -> None:
        super().__init__()
        self._kind = kind
        self._tol  = tol
        self.label = label

    def _build_params(self) -> dict[str, Param]:
        return {"tol": Param(self._tol, "-", desc="convergence tolerance")}

    def _build_inlets(self) -> dict[str, Port]:
        return {"inlet": Port("inlet", self._kind, "in")}

    def _build_outlets(self) -> dict[str, Port]:
        return {"outlet": Port("outlet", self._kind, "out")}

    def compute(self) -> None:
        s = self._in("inlet")
        if s is not None:
            self._out_set("outlet", s.copy())
        else:
            self._out_set("outlet",
                Stream(kind=self._kind, mdot=0.0, T=300.0, P=101325.0))

        # Report convergence status
        inlet  = self.inlets["inlet"].stream
        outlet = self.outlets["outlet"].stream
        res = inlet.residual(outlet) if inlet and outlet else float("nan")
        self._result("Recycle residual", res, "-",
                     "verified" if res < self._p("tol") else "screening")


class EnergyRecycle(Recycle):
    """Recycle for energy / electrical streams."""
    category = "Utility"

    def __init__(self, label: str = "Energy Recycle") -> None:
        super().__init__(kind=StreamKind.ENERGY, label=label)
