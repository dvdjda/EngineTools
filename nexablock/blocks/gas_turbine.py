"""
nexablock.blocks.gas_turbine — Simple-cycle gas turbine.

Ports
-----
exhaust (GENERIC_FLUID, out): hot exhaust gas → HRSG
power   (ELECTRICAL,    out): net electrical output
gt_cw   (ENERGY,        out): GT cooling water duty (lube oil/intercooler)

Physics
-------
  Ambient derating: -0.7%/°C above ISO 15°C (conservative screening)
  Fuel input = P_actual / η_GT  (LHV basis, NG ≈ methane, LHV=50 050 kJ/kg)
  Exhaust heat = waste_heat × 0.85  (CCGT-optimised GT insulation)
  Exhaust mass flow: Q_exh = ṁ_exh × cp_exh × (T_exh − T_amb)
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param
from ..core import props as _props
from ..validation.reference import Reference, TestCase

_NG_LHV   = 50_050e3  # J/kg  NG LHV (methane basis)
_NG_RHO   = 0.75       # kg/Nm³
_EXH_FRAC = 0.85       # fraction of waste heat in exhaust (CCGT GT)


class GasTurbine(Block):
    category = "Power"
    label    = "Gas Turbine"

    def __init__(self,
                 p_rated_kW:   float = 10_000.0,
                 load_pct:     float = 85.0,
                 gt_eff:       float = 0.35,
                 t_ambient_C:  float = 25.0,
                 t_exhaust_C:  float = 530.0) -> None:
        super().__init__()
        self._p_rated  = p_rated_kW * 1e3
        self._load_pct = load_pct
        self._gt_eff   = gt_eff
        self._t_amb    = t_ambient_C + 273.15
        self._t_exh    = t_exhaust_C + 273.15

    def _build_params(self) -> dict[str, Param]:
        return {
            "p_rated_W":  Param(self._p_rated,  "W",   desc="GT ISO rated power"),
            "load_pct":   Param(self._load_pct, "%",   min=10, max=100),
            "gt_eff":     Param(self._gt_eff,   "-",   min=0.15, max=0.45),
            "t_amb_K":    Param(self._t_amb,    "K",   desc="Ambient temperature"),
            "t_exh_K":    Param(self._t_exh,    "K",   desc="Exhaust gas temperature"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {}  # GT is a source block — no process inlets

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "exhaust": Port("exhaust", StreamKind.GENERIC_FLUID, "out"),
            "power":   Port("power",   StreamKind.ELECTRICAL,     "out"),
            "gt_cw":   Port("gt_cw",   StreamKind.ENERGY,         "out"),
        }

    def compute(self) -> None:
        t_amb = self._p("t_amb_K");  t_exh = self._p("t_exh_K")
        eff   = max(self._p("gt_eff"), 1e-6)

        derate   = max(0.50, 1.0 - 0.007 * max(0.0, t_amb - 288.15))
        p_derate = self._p("p_rated_W") * derate
        p_gt     = p_derate * self._p("load_pct") / 100.0

        fuel_W       = p_gt / eff
        ng_kgps      = fuel_W / _NG_LHV
        waste_heat_W = fuel_W - p_gt
        exh_heat_W   = waste_heat_W * _EXH_FRAC
        gt_cw_W      = waste_heat_W * (1.0 - _EXH_FRAC)

        cp_exh       = _props.cp_exhgas(t_exh)           # J/kg·K
        dt_exh       = max(t_exh - t_amb, 1.0)
        exh_mdot     = exh_heat_W / (cp_exh * dt_exh)    # kg/s

        # Outlets
        self._out_set("exhaust", Stream.fluid(
            mdot=exh_mdot, T=t_exh, P=101325.0,
            cp=cp_exh, rho=0.45, label="GT exhaust"))
        self._out_set("power", Stream.electrical(power=p_gt, label="GT electrical"))
        self._out_set("gt_cw", Stream.energy(power=gt_cw_W, label="GT CW duty"))

        # Results
        self._result("GT derated capacity", p_derate/1e3,    "kW", "verified")
        self._result("GT actual power",     p_gt/1e3,        "kW", "verified")
        self._result("Fuel energy input",   fuel_W/1e3,      "kW", "verified")
        self._result("NG consumption kg/h",  ng_kgps*3600,         "kg/h",  "verified")
        self._result("NG consumption Nm3/h", ng_kgps*3600/_NG_RHO, "Nm³/h", "verified")
        self._result("GT SFC",              ng_kgps*3600*1e6/max(p_gt/1e3,1), "g/kWh","verified")
        self._result("Exhaust mass flow",   exh_mdot*3.6,    "t/h","verified")
        self._result("Exhaust heat",        exh_heat_W/1e3,  "kW","verified")
        self._result("GT cooling water",    gt_cw_W/1e3,     "kW","verified")
        self._result("GT efficiency",       eff*100,         "%", "verified")
        self._result("Derate factor",       derate,          "-", "verified")

    def references(self):
        return [Reference("ISO 3977-2  Performance testing for gas turbines",
                          kind="standard")]
