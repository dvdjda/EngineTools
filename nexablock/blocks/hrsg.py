"""
nexablock.blocks.hrsg — Heat Recovery Steam Generator.

Ports
-----
exhaust_in  (GENERIC_FLUID, in) : hot exhaust from GT
stack       (GENERIC_FLUID, out): cooled flue gas
feedwater   (WATER_STEAM,   in) : cold feedwater
steam       (WATER_STEAM,   out): superheated steam

Physics
-------
  Q_hrsg = Q_exhaust × η_hrsg
  Steam generation: ṁ_steam = Q_hrsg / (h_steam − h_fw)
  Stack T (linear approx): T_stack = T_exh − (T_exh − T_amb) × η_hrsg
  Steam properties via IAPWS-IF97 (dwsim_props → CoolProp fallback)
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param
from ..core import props as _props
from ..validation.reference import Reference

_DT_SH = 30.0   # °C superheat above saturation (fixed CCGT screening)


class HRSG(Block):
    category = "HeatExchange"
    label    = "HRSG"

    def __init__(self,
                 hrsg_eff_pct:  float = 85.0,
                 steam_p_bar:   float = 10.0,
                 fw_t_C:        float = 80.0) -> None:
        super().__init__()
        self._eff    = hrsg_eff_pct / 100.0
        self._p_st   = steam_p_bar * 1e5   # Pa
        self._fw_t   = fw_t_C + 273.15     # K

    def _build_params(self) -> dict[str, Param]:
        return {
            "hrsg_eff": Param(self._eff,   "-",  min=0.5, max=0.95),
            "p_steam":  Param(self._p_st,  "Pa", desc="Steam drum pressure"),
            "fw_t":     Param(self._fw_t,  "K",  desc="Feedwater temperature"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {
            "exhaust_in": Port("exhaust_in", StreamKind.GENERIC_FLUID, "in"),
            "feedwater":  Port("feedwater",  StreamKind.WATER_STEAM,   "in"),
        }

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "stack": Port("stack", StreamKind.GENERIC_FLUID, "out"),
            "steam": Port("steam", StreamKind.WATER_STEAM,   "out"),
        }

    def compute(self) -> None:
        exh  = self._in("exhaust_in")
        fw_s = self._in("feedwater")

        eff  = self._p("hrsg_eff")
        p_st = self._p("p_steam")
        fw_t = self._p("fw_t")

        # Exhaust heat available
        if exh is not None:
            cp_exh    = exh.props.get("cp", _props.cp_exhgas(exh.T))
            t_amb     = 298.15   # reference ambient
            exh_heat  = exh.mdot * cp_exh * (exh.T - t_amb)   # W
            t_exh     = exh.T
        else:
            exh_heat  = 0.0; t_exh = 800.0

        q_hrsg    = exh_heat * eff                              # W
        q_stack   = exh_heat * (1.0 - eff)

        # Stack temperature (linear approx)
        t_stack   = t_exh - (t_exh - 298.15) * eff

        # Steam properties (IAPWS-IF97)
        t_sat     = _props.t_sat(p_st)                         # K
        t_steam   = t_sat + _DT_SH                             # K  superheated
        h_steam   = _props.h_steam(p_st, t_steam)              # J/kg
        h_fw      = _props.h_water(p_st, fw_t)                 # J/kg
        dh        = max(h_steam - h_fw, 1.0)

        # Steam generation
        mdot_steam = q_hrsg / dh                               # kg/s
        if fw_s is not None:
            mdot_steam = min(mdot_steam, fw_s.mdot * 0.999)   # can't exceed FW supply

        # Outlets
        self._out_set("stack", Stream.fluid(
            mdot=exh.mdot if exh else 0.0, T=t_stack, P=101325.0,
            cp=exh.props.get("cp", 1080.0) if exh else 1080.0,
            rho=0.60, label="Stack flue gas"))

        self._out_set("steam", Stream.water_steam(
            mdot=mdot_steam, T=t_steam, P=p_st,
            h=h_steam, label="HRSG steam"))

        # Results
        self._result("HRSG duty",          q_hrsg/1e3,        "kW",  "verified")
        self._result("Stack heat loss",    q_stack/1e3,       "kW",  "verified")
        self._result("Stack temperature",  t_stack-273.15,    "°C",  "verified")
        self._result("Steam temperature",  t_steam-273.15,    "°C",  "verified")
        self._result("Steam saturation T", t_sat-273.15,      "°C",  "verified",
                     "IAPWS-IF97 via SteamTables2")
        self._result("Steam enthalpy",     h_steam/1e3,       "kJ/kg","verified",
                     "IAPWS-IF97 via SteamTables2")
        self._result("Steam generation",   mdot_steam*3.6,    "t/h", "verified")
        self._result("Feedwater enthalpy", h_fw/1e3,          "kJ/kg","verified")

    def references(self):
        return [Reference("IAPWS-IF97 via DWSIM SteamTables2 / CoolProp",
                          kind="standard")]
