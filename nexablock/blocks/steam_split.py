"""
nexablock.blocks.steam_split — Calorifier + Mixer, for the LiBr-priority steam
split that handles the "chiller over-performing" case.

When GPU cooling demand falls below what the HRSG steam would drive, a steam
3-way valve (SteamSplitter) feeds the LiBr chiller only the steam it needs and
routes the SURPLUS steam to a CALORIFIER — a steam-to-hot-water heat exchanger
that delivers ~95 °C hot water into the MED rejection loop. A MIXER combines the
LiBr rejection and the calorifier hot water into MED's single loop feed.

This respects the heat-grade interfaces: the LiBr runs on steam, MED runs on hot
water; the calorifier is "a LiBr without the chilling" that converts the surplus
steam into the hot water MED actually wants.
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param
from ..core import props as _props

_P_ATM = 101325.0
_CP_W  = 4187.0


class Calorifier(Block):
    category = "Utility"
    label    = "Calorifier"

    def __init__(self, hot_t_C: float = 95.0, return_t_C: float = 80.0) -> None:
        super().__init__()
        self._hot_t = hot_t_C + 273.15
        self._ret_t = return_t_C + 273.15

    def _build_params(self) -> dict[str, Param]:
        return {
            "hot_t": Param(self._hot_t, "K", desc="hot-water delivery temperature"),
            "ret_t": Param(self._ret_t, "K", desc="loop cold side (HRSG return set-point)"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {"steam_in": Port("steam_in", StreamKind.WATER_STEAM, "in", required=False)}

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "hot_out":    Port("hot_out",    StreamKind.WATER_STEAM, "out"),
            "condensate": Port("condensate", StreamKind.WATER_STEAM, "out"),
        }

    def compute(self) -> None:
        s = self._in("steam_in")
        hot_t = self._p("hot_t"); ret_t = self._p("ret_t")
        if s is None or not s.mdot:
            self._out_set("hot_out",    Stream.water_steam(0.0, hot_t, 2e5))
            self._out_set("condensate", Stream.water_steam(0.0, 373.15, _P_ATM))
            self._result("Calorifier duty", 0.0, "kW",   "verified")
            self._result("Hot water flow",  0.0, "m³/h", "verified")
            self._result("Hot water temp",  hot_t - 273.15, "°C", "input")
            return
        h_cond = _props.h_sat_liq(_P_ATM)
        q_cal  = s.mdot * (s.h - h_cond)                 # W — steam condensing heat
        dt     = max(1.0, hot_t - ret_t)
        mdot_hw = q_cal / (_CP_W * dt)                   # kg/s hot water
        self._out_set("hot_out", Stream.water_steam(
            mdot=mdot_hw, T=hot_t, P=2e5, label="Calorifier hot water"))
        self._out_set("condensate", Stream.water_steam(
            mdot=s.mdot, T=373.15, P=_P_ATM, h=h_cond, label="Calorifier condensate"))
        self._result("Calorifier duty",     q_cal / 1e3,  "kW",   "verified",
                     "surplus steam condensing heat → MED hot water")
        self._result("Hot water flow",      mdot_hw * 3.6, "m³/h", "verified")
        self._result("Hot water temp",      hot_t - 273.15, "°C",  "input")
        self._result("Condensate flow m3/h", s.mdot * 3.6, "m³/h", "verified")

    def audit_checks(self) -> list:
        from ..audit import pass_fail
        s = self.inlets["steam_in"].stream
        t_steam = (s.T - 273.15) if (s is not None and s.T) else 0.0
        hot_C   = self._p("hot_t") - 273.15
        return [pass_fail(
            "T12: calorifier steam hotter than its hot-water output",
            passed=t_steam > hot_C,
            detail=f"steam {t_steam:.0f}°C > hot water {hot_C:.0f}°C",
            category="Second law", affects=["MED water production"])]


class Mixer(Block):
    """Adiabatic two-stream mixer (WATER_STEAM) — combines the LiBr rejection and
    the calorifier hot water into MED's single loop feed."""
    category = "Utility"
    label    = "Loop mixer"

    def _build_params(self) -> dict[str, Param]:
        return {}

    def _build_inlets(self) -> dict[str, Port]:
        return {"in_a": Port("in_a", StreamKind.WATER_STEAM, "in"),
                "in_b": Port("in_b", StreamKind.WATER_STEAM, "in", required=False)}

    def _build_outlets(self) -> dict[str, Port]:
        return {"out": Port("out", StreamKind.WATER_STEAM, "out")}

    def compute(self) -> None:
        a = self._in("in_a"); b = self._in("in_b")
        ma = a.mdot if (a is not None and a.mdot) else 0.0
        mb = b.mdot if (b is not None and b.mdot) else 0.0
        m  = ma + mb
        if m <= 0:
            self._out_set("out", Stream.water_steam(0.0, 368.15, 2e5))
            self._result("Mixed flow", 0.0, "m³/h", "verified")
            self._result("Mixed temp", 95.0, "°C", "verified")
            return
        Ta = a.T if (a is not None and a.T) else 368.15
        Tb = b.T if (b is not None and b.T) else Ta
        T  = (ma * Ta + mb * Tb) / m                     # energy-weighted (cp const)
        self._out_set("out", Stream.water_steam(mdot=m, T=T, P=2e5, label="MED loop feed"))
        self._result("Mixed flow", m * 3.6,     "m³/h", "verified")
        self._result("Mixed temp", T - 273.15,  "°C",   "verified")

    def audit_checks(self) -> list:
        from ..audit import mass_balance
        a = self.inlets["in_a"].stream; b = self.inlets["in_b"].stream
        out = self.outlets["out"].stream
        ma = a.mdot if (a and a.mdot) else 0.0
        mb = b.mdot if (b and b.mdot) else 0.0
        mo = out.mdot if (out and out.mdot) else 0.0
        return [mass_balance("M9: mixer out = in_a + in_b",
                             supply=mo, demand=ma + mb,
                             affects=["MED water production"], tol_rel=1e-3)]
