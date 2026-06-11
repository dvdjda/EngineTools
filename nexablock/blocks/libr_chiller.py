"""
nexablock.blocks.libr_chiller — LiBr absorption chiller (single-effect screening).

Ports
-----
steam_in     (WATER_STEAM,   in)  : generator steam
condensate   (WATER_STEAM,   out) : condensate return (~100°C)
chw_return   (GENERIC_FLUID, in)  : chilled water return (warm)
chw_supply   (GENERIC_FLUID, out) : chilled water supply (cold, cooled)
ct_water_out (ENERGY,        out) : condenser heat to cooling tower

Physics
-------
  Q_gen  = ṁ_steam × (h_steam − h_cond_100C)
  Q_cool = Q_gen × COP_LiBr
  Q_cond = Q_gen + Q_cool   (energy balance)
  CHW flow: ṁ_chw = Q_cool / (cp_chw × ΔT_chw)
  Condensate: IAPWS h at 100°C / 1.013 bar

Reference: Herold, Radermacher, Klein — Absorption Chillers and Heat Pumps, 2016.
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param
from ..core import props as _props
from ..validation.reference import Reference, TestCase

_P_ATM = 101325.0   # Pa atmospheric condensate return pressure


class LiBrChiller(Block):
    category = "Cooling"
    label    = "LiBr Chiller"

    def __init__(self,
                 cop:        float = 0.70,
                 chw_sup_C:  float = 7.0,
                 chw_dt_K:   float = 6.0,
                 chw_cp:     float = 4187.0,
                 pump_frac:  float = 0.015) -> None:    # 1.5% of cooling (screening)
        super().__init__()
        self._cop       = cop
        self._chw_sup   = chw_sup_C + 273.15
        self._chw_dt    = chw_dt_K
        self._chw_cp    = chw_cp
        self._pump_frac = pump_frac

    def _build_params(self) -> dict[str, Param]:
        return {
            "cop":       Param(self._cop,    "-",   min=0.5, max=1.3),
            "chw_sup":   Param(self._chw_sup,"K",   desc="CHW supply temperature"),
            "chw_dt":    Param(self._chw_dt, "K",   min=3, max=15),
            "chw_cp":    Param(self._chw_cp, "J/(kg·K)"),
            "pump_frac": Param(self._pump_frac, "-", min=0.0, max=0.05,
                                desc="Solution + refrigerant pump electrical as fraction of cooling"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {
            "steam_in":   Port("steam_in",  StreamKind.WATER_STEAM,   "in"),
            "chw_return": Port("chw_return",StreamKind.GENERIC_FLUID, "in", required=False),
        }

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "condensate":   Port("condensate",   StreamKind.WATER_STEAM,   "out"),
            "chw_supply":   Port("chw_supply",   StreamKind.GENERIC_FLUID, "out"),
            "ct_water_out": Port("ct_water_out", StreamKind.ENERGY,        "out"),
        }

    def compute(self) -> None:
        s   = self._in("steam_in")
        cop = self._p("cop"); chw_sup = self._p("chw_sup"); chw_dt = self._p("chw_dt")
        chw_cp = self._p("chw_cp")

        if s is None or s.mdot is None or s.mdot == 0:
            self._out_set("condensate",   Stream.water_steam(0.0, 373.15, _P_ATM))
            self._out_set("chw_supply",   Stream.fluid(0.0, chw_sup, 3e5))
            self._out_set("ct_water_out", Stream.energy(0.0))
            return

        h_cond_100 = _props.h_sat_liq(_P_ATM)              # J/kg  condensate at 100°C (saturated liquid; h_water at T_sat picks vapour)
        q_gen      = s.mdot * (s.h - h_cond_100)           # W
        q_cool     = q_gen * cop                            # W
        q_cond_ct  = q_gen + q_cool                        # W

        # CHW flow
        mdot_chw   = q_cool / (chw_cp * chw_dt)            # kg/s
        chw_ret_t  = chw_sup + chw_dt                       # K return temp

        # Outlets
        self._out_set("condensate", Stream.water_steam(
            mdot=s.mdot, T=373.15, P=_P_ATM,
            h=h_cond_100, label="LiBr condensate"))
        self._out_set("chw_supply", Stream.fluid(
            mdot=mdot_chw, T=chw_sup, P=3e5, cp=chw_cp, rho=1000.0,
            label="CHW supply"))
        self._out_set("ct_water_out", Stream.energy(power=q_cond_ct, label="LiBr condenser→CT"))

        pump_kW = self._p("pump_frac") * q_cool / 1e3      # solution + refrigerant pumps

        self._result("Generator duty",       q_gen/1e3,     "kW",  "verified")
        self._result("Cooling capacity kW",  q_cool/1e3,    "kW",  "verified", "COP×Q_gen")
        self._result("Cooling capacity TR",  q_cool/3517,   "TR",  "verified")
        self._result("Condenser duty",       q_cond_ct/1e3, "kW",  "verified")
        self._result("CHW flow",             mdot_chw*3.6,  "m³/h","verified")
        self._result("CHW supply temp",      chw_sup-273.15,"°C",  "input")
        self._result("CHW return temp",      chw_ret_t-273.15,"°C","verified")
        self._result("COP achieved",         cop,           "-",   "input")
        self._result("LiBr pump electrical", pump_kW,       "kW",  "screening",
                     "pump_frac × Q_cool (screening)")

    def references(self):
        return [Reference(
            "Herold, Radermacher, Klein — Absorption Chillers & Heat Pumps, 2016",
            kind="standard")]
