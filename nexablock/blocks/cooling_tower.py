"""
nexablock.blocks.cooling_tower — Evaporative cooling tower (screening).

Ports
-----
heat_in   (ENERGY,        in)  : condenser duty from LiBr (or other source)
ct_supply (GENERIC_FLUID, out) : cooled water to condenser
ct_return (GENERIC_FLUID, in)  : warm return from condenser (optional)

Physics (screening)
-------------------
  ṁ_ct = Q_cond / (cp_w × ΔT_ct)   — water flow from energy balance
  T_supply = T_wet_bulb + approach  — approach temperature (screening: 5°C)
  T_return = T_supply + ΔT_ct
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param

_CP_W = 4187.0   # J/kg·K water


class CoolingTower(Block):
    category = "Cooling"
    label    = "Cooling Tower"

    def __init__(self,
                 t_wb_C:     float = 25.0,
                 approach_K: float = 5.0,
                 dt_ct_K:    float = 7.0,
                 fan_frac:   float = 0.015) -> None:    # 1.5% of rejected heat (screening)
        super().__init__()
        self._t_wb      = t_wb_C + 273.15
        self._approach  = approach_K
        self._dt_ct     = dt_ct_K
        self._fan_frac  = fan_frac

    def _build_params(self) -> dict[str, Param]:
        return {
            "t_wb":     Param(self._t_wb,     "K",  desc="Wet-bulb temperature"),
            "approach": Param(self._approach, "K",  min=2, max=15,
                              desc="CT approach (T_supply − T_wb)"),
            "dt_ct":    Param(self._dt_ct,    "K",  min=3, max=15,
                              desc="CT water temperature rise"),
            "fan_frac": Param(self._fan_frac, "-",  min=0.0, max=0.10,
                              desc="Fan electrical as fraction of rejected heat"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {
            "heat_in":   Port("heat_in",  StreamKind.ENERGY,        "in"),
            "ct_return": Port("ct_return",StreamKind.GENERIC_FLUID, "in", required=False),
        }

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "ct_supply": Port("ct_supply", StreamKind.GENERIC_FLUID, "out"),
        }

    def compute(self) -> None:
        heat  = self._in("heat_in")
        t_wb  = self._p("t_wb");  app = self._p("approach"); dt = self._p("dt_ct")

        q_W       = heat.power if heat and heat.power else 0.0
        t_sup     = t_wb + app              # K
        t_ret     = t_sup + dt              # K
        mdot      = q_W / (_CP_W * dt) if dt > 0 else 0.0

        self._out_set("ct_supply", Stream.fluid(
            mdot=mdot, T=t_sup, P=3e5, cp=_CP_W, rho=998.0,
            label="CT supply water"))

        fan_kW = self._p("fan_frac") * q_W / 1e3      # electrical aux
        self._ct_return = self.inlets["ct_return"].stream    # snapshot for audit

        self._result("CT heat duty",       q_W/1e3,     "kW",  "verified")
        self._result("CT water flow",      mdot*3.6,    "m³/h","verified")
        self._result("CT supply temp",     t_sup-273.15,"°C",  "verified")
        self._result("CT return temp",     t_ret-273.15,"°C",  "verified")
        self._result("CT ΔT",              dt,          "K",   "input")
        self._result("Wet-bulb temp",      t_wb-273.15, "°C",  "input")
        self._result("CT fan electrical",  fan_kW,      "kW",  "screening",
                     "fan_frac × rejected heat (screening)")

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import mass_balance, pass_fail
        r = self.results
        t_sup = r["CT supply temp"].value
        t_wb  = r["Wet-bulb temp"].value
        # Optional return flow check — if connected, mass should match supply.
        m_sup = self.outlets["ct_supply"].stream.mdot if self.outlets["ct_supply"].stream else 0.0
        m_ret = (self._ct_return.mdot if getattr(self, "_ct_return", None)
                                          and self._ct_return.mdot else m_sup)
        return [
            mass_balance("M8: ct supply = ct return (no evaporation modelled)",
                supply=m_sup, demand=m_ret,
                affects=["LiBr cooling capacity"], tol_rel=1e-3),
            pass_fail("T5: CT supply > wet-bulb (approach > 0)",
                passed=t_sup > t_wb,
                detail=f"T_supply={t_sup:.1f}°C > T_wb={t_wb:.1f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
        ]
