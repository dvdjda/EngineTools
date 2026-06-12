"""
nexablock.blocks.med — MED (Multi-Effect Distillation) thermal desalination.

Ports
-----
steam_in   (WATER_STEAM,   in)  : low-grade steam / hot water
condensate (WATER_STEAM,   out) : steam condensate (~65°C)
seawater   (GENERIC_FLUID, in)  : seawater feed
fresh      (GENERIC_FLUID, out) : fresh water product
brine      (GENERIC_FLUID, out) : brine reject

Physics (screening)
-------------------
  GOR   = 0.8 × n_effects   (thin-film falling-film, screening rule)
  ṁ_dist = ṁ_steam × GOR
  ṁ_sw   = ṁ_dist / recovery_ratio   (default 35%)
  ṁ_brine= ṁ_sw − ṁ_dist
  SEC_elec = 1.5 kWh/m³ (pump/controls electricity, not thermal)
  Condensate returns at ~65°C (top brine temperature)

Reference: El-Dessouky & Ettouney — Fundamentals of Salt Water Desalination (2002).
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param
from ..core import props as _props
from ..validation.reference import Reference

_P_ATM   = 101325.0  # Pa
_SEC     = 1.5       # kWh/m³  specific electrical consumption
_RECOV   = 0.35      # MED water recovery ratio
_RHO_SW  = 1020.0    # kg/m³  seawater density
_RHO_BR  = 1030.0    # kg/m³  brine density
_T_COND  = 65.0      # °C  steam condensate return temperature (top brine T)


class MED(Block):
    category = "Desalination"
    label    = "MED Desalination"

    def __init__(self,
                 n_effects:     int   = 8,
                 sw_t_C:        float = 28.0,
                 recovery:      float = _RECOV) -> None:
        super().__init__()
        self._n_effects = n_effects
        self._sw_t      = sw_t_C + 273.15
        self._recovery  = recovery

    def _build_params(self) -> dict[str, Param]:
        return {
            "n_effects": Param(float(self._n_effects), "-", min=2, max=20),
            "sw_t":      Param(self._sw_t, "K", desc="Seawater feed temperature"),
            "recovery":  Param(self._recovery, "-", min=0.1, max=0.6),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {
            "steam_in":  Port("steam_in",  StreamKind.WATER_STEAM,   "in"),
            "seawater":  Port("seawater",  StreamKind.GENERIC_FLUID, "in", required=False),
        }

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "condensate": Port("condensate", StreamKind.WATER_STEAM,   "out"),
            "fresh":      Port("fresh",      StreamKind.GENERIC_FLUID, "out"),
            "brine":      Port("brine",      StreamKind.GENERIC_FLUID, "out"),
        }

    def compute(self) -> None:
        s        = self._in("steam_in")
        n        = int(round(self._p("n_effects")))
        sw_t     = self._p("sw_t")
        recovery = self._p("recovery")

        if s is None or s.mdot is None or s.mdot == 0:
            self._out_set("condensate", Stream.water_steam(0.0, 338.15, _P_ATM))
            self._out_set("fresh",      Stream.fluid(0.0, 313.15, _P_ATM))
            self._out_set("brine",      Stream.fluid(0.0, 333.15, _P_ATM))
            return

        gor        = 0.8 * n
        t_cond_K   = _T_COND + 273.15
        h_cond     = _props.h_water(_P_ATM, t_cond_K)      # J/kg

        q_med      = s.mdot * (s.h - h_cond)               # W  thermal input
        mdot_dist  = s.mdot * gor                           # kg/s distillate
        mdot_sw    = mdot_dist / max(recovery, 1e-3)        # kg/s seawater
        mdot_brine = mdot_sw - mdot_dist                    # kg/s brine

        # Fresh water production
        m3pd = mdot_dist * 86400 / 1000                     # m³/day
        m3ph = mdot_dist * 3600  / 1000                     # m³/h
        p_elec = _SEC * m3pd / 24 * 1e3                     # W

        # NB: the seawater inlet seed (if connected) is a solver-side tear
        # initialiser only — the actual seawater required is computed from
        # distillate / recovery and reported below. Overriding mdot_sw here
        # used to desynchronise "Seawater feed" from "Brine reject" since the
        # brine outlet was already built from the unforced value.

        self._out_set("condensate", Stream.water_steam(
            mdot=s.mdot, T=t_cond_K, P=_P_ATM,
            h=h_cond, label="MED condensate"))
        self._out_set("fresh", Stream.fluid(
            mdot=mdot_dist, T=313.15, P=_P_ATM,
            cp=4187.0, rho=992.0, label="Fresh water"))
        self._out_set("brine", Stream.fluid(
            mdot=mdot_brine, T=333.15, P=_P_ATM,
            cp=3900.0, rho=_RHO_BR, label="Brine reject"))

        self._result("GOR",                gor,             "-",     "screening")
        self._result("MED thermal input",  q_med/1e3,       "kW",    "verified")
        self._result("Water production m3/day", m3pd,        "m³/day","verified")
        self._result("Water production m3/h",   m3ph,        "m³/h",  "verified")
        self._result("Seawater feed",      mdot_sw*3.6,     "m³/h",  "verified")
        self._result("Brine reject",       mdot_brine*3.6,  "m³/h",  "verified")
        self._result("MED electrical",     p_elec/1e3,      "kW",    "screening")
        self._result("Number of effects",  float(n),        "-",     "input")

    def references(self):
        return [Reference(
            "El-Dessouky & Ettouney — Fundamentals of Salt Water Desalination (2002)",
            kind="standard")]

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import (mass_balance, energy_balance, pass_fail,
                              bounds_check)
        r = self.results
        gor       = r["GOR"].value
        q_med     = r["MED thermal input"].value          # kW
        mdot_dist = r["Water production m3/h"].value * 1000.0 / 3600.0   # m³/h → kg/s
        mdot_sw   = r["Seawater feed"].value * 1000.0 / 3600.0
        mdot_br   = r["Brine reject"].value * 1000.0 / 3600.0
        n_eff     = int(round(self._p("n_effects")))
        sw_t_C    = self._p("sw_t") - 273.15
        recovery  = self._p("recovery")
        steam_in  = self.inlets["steam_in"].stream
        steam_mdot = steam_in.mdot if steam_in is not None and steam_in.mdot else 0.0
        # Latent heat of vapourisation at 1 atm ≈ 2257 kJ/kg
        h_fg      = 2257.0   # kJ/kg
        # MED steam side T (~100 °C at 1 atm screening)
        t_steam_low_C = 100.0
        # Brine T (block sets 333.15 K = 60 °C)
        t_brine_C = 60.0
        return [
            energy_balance("E8: Q_steam ≈ ṁ_dist · h_fg / GOR  (screening)",
                supply=q_med,
                demand=mdot_dist * h_fg / max(gor, 1e-6),
                affects=["MED water production"], tol_rel=0.15),
            mass_balance("M4: seawater = distillate + brine",
                supply=mdot_sw, demand=mdot_dist + mdot_br,
                affects=["MED water production"], tol_rel=5e-3),
            bounds_check("M5: GOR in (4, 10) screening band",
                value=gor, lo=4.0, hi=10.0, unit="-",
                category="Mass closure",
                affects=["MED water production"]),
            pass_fail("T4: ΔT per effect ≥ 3°C",
                passed=(t_steam_low_C - sw_t_C) / max(n_eff, 1) >= 3.0,
                detail=f"(T_steam {t_steam_low_C:.0f} − T_sw {sw_t_C:.0f}) / "
                       f"{n_eff} = {(t_steam_low_C-sw_t_C)/max(n_eff,1):.2f}°C",
                category="Second law", affects=["MED water production"]),
            pass_fail("T10: T_brine > T_seawater (concentration step)",
                passed=t_brine_C > sw_t_C,
                detail=f"T_brine={t_brine_C:.0f}°C > T_sw={sw_t_C:.0f}°C",
                category="Second law", affects=["MED water production"]),
            bounds_check("P5: GOR plausibility (4, 10)",
                value=gor, lo=4.0, hi=10.0, unit="-",
                affects=["MED water production"]),
            bounds_check("P6: recovery in (0, 0.5)",
                value=recovery, lo=0.0, hi=0.5, unit="-",
                affects=["MED water production"]),
        ]
