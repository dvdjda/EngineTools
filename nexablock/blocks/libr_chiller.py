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
                 pump_frac:  float = 0.015,             # 1.5% of cooling (screening)
                 reject_t_C: float = 95.0,              # hot cooling-loop temperature
                 reject_return_C: float = 80.0) -> None: # loop cold side (HRSG return set-point)
        super().__init__()
        self._cop       = cop
        self._chw_sup   = chw_sup_C + 273.15
        self._chw_dt    = chw_dt_K
        self._chw_cp    = chw_cp
        self._pump_frac = pump_frac
        self._reject_t  = reject_t_C + 273.15
        self._reject_ret= reject_return_C + 273.15

    def _build_params(self) -> dict[str, Param]:
        return {
            "cop":       Param(self._cop,    "-",   min=0.5, max=1.3),
            "chw_sup":   Param(self._chw_sup,"K",   desc="CHW supply temperature"),
            "chw_dt":    Param(self._chw_dt, "K",   min=3, max=15),
            "chw_cp":    Param(self._chw_cp, "J/(kg·K)"),
            "pump_frac": Param(self._pump_frac, "-", min=0.0, max=0.05,
                                desc="Solution + refrigerant pump electrical as fraction of cooling"),
            "reject_t":   Param(self._reject_t,   "K", desc="Cooling-loop hot temperature (rejection)"),
            "reject_ret": Param(self._reject_ret, "K", desc="Cooling-loop cold side (HRSG return set-point)"),
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
            # Heat rejection now leaves as a hot WATER stream into the cooling
            # loop (drives MED, then the radiator, then back to HRSG feedwater).
            "reject_out":   Port("reject_out",   StreamKind.WATER_STEAM,   "out"),
        }

    def compute(self) -> None:
        s   = self._in("steam_in")
        cop = self._p("cop"); chw_sup = self._p("chw_sup"); chw_dt = self._p("chw_dt")
        chw_cp = self._p("chw_cp")

        if s is None or s.mdot is None or s.mdot == 0:
            self._out_set("condensate", Stream.water_steam(0.0, 373.15, _P_ATM))
            self._out_set("chw_supply", Stream.fluid(0.0, chw_sup, 3e5))
            self._out_set("reject_out", Stream.water_steam(0.0, self._p("reject_t"), 2e5))
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
        # Heat rejection → hot cooling-loop water. mdot sized so the loop carries
        # Q_cond across the (reject_t − return) window. This water drives MED,
        # is trimmed by the radiator, and returns to the HRSG feedwater.
        cp_w     = 4187.0
        reject_t = self._p("reject_t"); reject_ret = self._p("reject_ret")
        loop_dt  = max(1.0, reject_t - reject_ret)
        mdot_cw  = q_cond_ct / (cp_w * loop_dt)            # kg/s
        self._out_set("reject_out", Stream.water_steam(
            mdot=mdot_cw, T=reject_t, P=2e5, label="LiBr rejection (hot loop water)"))

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
        self._result("Rejection loop flow", mdot_cw*3.6,    "m³/h","verified")
        self._result("Rejection loop temp", reject_t-273.15,"°C",  "input")
        self._result("Condensate flow m3/h", s.mdot*3.6,    "m³/h","verified",
                     "steam condensate return")

    def references(self):
        return [Reference(
            "Herold, Radermacher, Klein — Absorption Chillers & Heat Pumps, 2016",
            kind="standard")]

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import (mass_balance, energy_balance, pass_fail,
                              bounds_check)
        r = self.results
        q_gen   = r["Generator duty"].value
        q_cool  = r["Cooling capacity kW"].value
        q_cond  = r["Condenser duty"].value
        cop     = self._p("cop")
        chw_sup = self._p("chw_sup") - 273.15
        dt_chw  = self._p("chw_dt")
        chw_ret = chw_sup + dt_chw
        steam_in = self.inlets["steam_in"].stream
        cond_out = self.outlets["condensate"].stream
        steam_mdot = steam_in.mdot if steam_in is not None and steam_in.mdot else 0.0
        cond_mdot  = cond_out.mdot if cond_out is not None and cond_out.mdot else 0.0
        t_steam_C  = (steam_in.T - 273.15) if steam_in is not None and steam_in.T else 0.0
        t_cond_C   = 100.0    # condensate at 1 atm saturation
        return [
            energy_balance("E5: Q_gen · COP = Q_cool",
                supply=q_gen * cop, demand=q_cool,
                affects=["LiBr cooling capacity"], tol_rel=1e-3),
            energy_balance("E6: Q_cond = Q_gen + Q_cool (chiller 1st law)",
                supply=q_cond, demand=q_gen + q_cool,
                affects=["LiBr cooling capacity"], tol_rel=5e-3),
            mass_balance("M3: steam_in = condensate_out (water mass)",
                supply=steam_mdot, demand=cond_mdot,
                affects=["LiBr cooling capacity"], tol_rel=1e-4),
            pass_fail("T6: T_CHW_supply ≥ 5°C",
                passed=chw_sup >= 5.0,
                detail=f"T_chw_supply={chw_sup:.1f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
            pass_fail("T7: T_CHW_return > T_CHW_supply",
                passed=chw_ret > chw_sup,
                detail=f"T_ret={chw_ret:.1f} > T_sup={chw_sup:.1f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
            pass_fail("T9: T_steam_in > T_condensate (generator driving force)",
                passed=t_steam_C > t_cond_C,
                detail=f"T_steam={t_steam_C:.0f}°C > T_cond={t_cond_C:.0f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
            bounds_check("P4: LiBr COP in (0.5, 1.3)",
                value=cop, lo=0.5, hi=1.3, unit="-",
                affects=["LiBr cooling capacity"]),
        ]
