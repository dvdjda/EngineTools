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
                 t_exhaust_C:  float = 530.0,
                 aux_frac:     float = 0.010) -> None:    # 1.0% of derated capacity
        super().__init__()
        self._p_rated  = p_rated_kW * 1e3
        self._load_pct = load_pct
        self._gt_eff   = gt_eff
        self._t_amb    = t_ambient_C + 273.15
        self._t_exh    = t_exhaust_C + 273.15
        self._aux_frac = aux_frac

    def _build_params(self) -> dict[str, Param]:
        return {
            "p_rated_W": Param(self._p_rated,  "W",   desc="GT ISO rated power"),
            "load_pct":  Param(self._load_pct, "%",   min=10, max=100),
            "gt_eff":    Param(self._gt_eff,   "-",   min=0.15, max=0.45),
            "t_amb_K":   Param(self._t_amb,    "K",   desc="Ambient temperature"),
            "t_exh_K":   Param(self._t_exh,    "K",   desc="Exhaust gas temperature"),
            "aux_frac":  Param(self._aux_frac, "-",   min=0.0, max=0.05,
                                desc="GT auxiliary electrical as fraction of derated capacity"),
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

        gt_aux_kW = self._p("aux_frac") * p_derate / 1e3       # GT auxiliaries (lube oil, fuel skid, controls)

        # Results
        self._result("GT derated capacity", p_derate/1e3,    "kW", "verified")
        self._result("GT actual power",     p_gt/1e3,        "kW", "verified")
        self._result("GT aux electrical",   gt_aux_kW,       "kW", "screening",
                     "aux_frac × derated capacity (integral to the GT package)")
        self._result("GT net power",        p_gt/1e3 - gt_aux_kW, "kW", "verified",
                     "gross − GT auxiliaries (the net output to the bus)")
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

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import energy_balance, pass_fail, bounds_check
        r = self.results
        p_actual = r["GT actual power"].value
        p_derate = r["GT derated capacity"].value
        fuel_kW  = r["Fuel energy input"].value
        exh_kW   = r["Exhaust heat"].value
        gt_cw_kW = r["GT cooling water"].value
        ng_kgph  = r["NG consumption kg/h"].value
        eff      = self._p("gt_eff")
        derate   = r["Derate factor"].value
        load_pct = self._p("load_pct")
        t_amb_K  = self._p("t_amb_K"); t_exh_K = self._p("t_exh_K")
        ng_kgps  = ng_kgph / 3600.0
        fuel_via_ng_kW = ng_kgps * (_NG_LHV / 1000.0)             # NG → fuel kW
        return [
            energy_balance("E1: NG · LHV · η = GT actual power",
                supply=fuel_via_ng_kW * eff, demand=p_actual,
                affects=["GT actual power", "NG consumption"], tol_rel=5e-3),
            energy_balance("E2: fuel = power + exhaust + GT cooling water",
                supply=fuel_kW, demand=p_actual + exh_kW + gt_cw_kW,
                affects=["GT actual power"], tol_rel=5e-3),
            energy_balance("M6: NG fuel/combustion → GT power closure",
                supply=fuel_via_ng_kW * eff, demand=p_actual,
                affects=["NG consumption"], tol_rel=5e-3),
            pass_fail("T8: GT exhaust > T_ambient + 100°C",
                passed=(t_exh_K - t_amb_K) > 100.0,
                detail=f"T_exh={t_exh_K-273.15:.0f}°C, T_amb={t_amb_K-273.15:.0f}°C, "
                       f"ΔT={t_exh_K-t_amb_K:.0f}°C",
                category="Second law", affects=["GT actual power"]),
            bounds_check("P1: GT efficiency in (0, 0.55)",
                value=eff, lo=0.0, hi=0.55, unit="-",
                affects=["GT actual power"]),
            bounds_check("P2: derate factor in (0, 1]",
                value=derate, lo=1e-3, hi=1.0, unit="-",
                affects=["GT actual power"]),
            bounds_check("P3: load_pct in [10, 100]",
                value=load_pct, lo=10.0, hi=100.0, unit="%",
                affects=["GT actual power"]),
            pass_fail("P11: GT actual ≤ GT derated capacity",
                passed=p_actual <= p_derate + 1e-6,
                detail=f"actual={p_actual:.0f} kW ≤ derated={p_derate:.0f} kW",
                category="Plausibility", affects=["GT actual power"]),
        ]
