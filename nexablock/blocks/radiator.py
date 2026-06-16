"""
nexablock.blocks.radiator — Dry, forced-air (fan) radiator with a 3-way bypass.

Replaces the evaporative CoolingTower for the closed cooling-water loop. The
loop water arrives hot (post-MED); a 3-way valve (auto) splits it between the
radiator core (cooled toward ambient dry-bulb) and a bypass (stays hot), then
remixes to a controlled outlet temperature — the HRSG feedwater return
set-point. So the radiator only rejects the *surplus* heat and never overcools
the feedwater.

Ports
-----
loop_in  (GENERIC_FLUID, in)  : hot loop water (mdot, T_in)
loop_out (GENERIC_FLUID, out) : blended return at the set-point

Physics (screening)
-------------------
  T_rad   = T_ambient + approach              radiator cold-branch outlet
  f       = (T_in − T_set) / (T_in − T_rad)   3-way split through the radiator, clamped [0,1]
  Q_rad   = f · mdot · cp · (T_in − T_rad)     heat rejected to ambient air
  T_out   = T_set  (=f·T_rad + (1−f)·T_in)     blended return
  Fan_el  = fan_frac · Q_rad
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param

_CP_W = 4187.0   # J/kg·K  cooling-water


class Radiator(Block):
    category = "Cooling"
    label    = "Radiator"

    def __init__(self,
                 t_ambient_C:  float = 25.0,
                 approach_K:   float = 15.0,    # radiator cold-side approach to ambient
                 t_return_C:   float = 80.0,    # HRSG feedwater return set-point (3-way blend target)
                 fan_frac:     float = 0.015,   # fan electrical as fraction of rejected heat
                 cp_w:         float = _CP_W) -> None:
        super().__init__()
        self._t_amb    = t_ambient_C + 273.15
        self._approach = approach_K
        self._t_return = t_return_C + 273.15
        self._fan_frac = fan_frac
        self._cp_w     = cp_w

    def _build_params(self) -> dict[str, Param]:
        return {
            "t_amb":    Param(self._t_amb,    "K", desc="Ambient dry-bulb air temperature"),
            "approach": Param(self._approach, "K", min=3, max=30,
                              desc="Radiator cold-branch approach to ambient"),
            "t_return": Param(self._t_return, "K", desc="HRSG return set-point (3-way blend target)"),
            "fan_frac": Param(self._fan_frac, "-", min=0.0, max=0.10,
                              desc="Fan electrical as fraction of rejected heat"),
            "cp_w":     Param(self._cp_w,     "J/(kg·K)"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {"loop_in": Port("loop_in", StreamKind.WATER_STEAM, "in")}

    def _build_outlets(self) -> dict[str, Port]:
        # WATER_STEAM so the cooled return can feed the HRSG feedwater inlet.
        return {"loop_out": Port("loop_out", StreamKind.WATER_STEAM, "out")}

    def compute(self) -> None:
        s    = self._in("loop_in")
        t_amb = self._p("t_amb"); app = self._p("approach")
        t_set = self._p("t_return"); cp = self._p("cp_w")

        mdot = (s.mdot if s and s.mdot else 0.0)
        t_in = (s.T if s and s.T else t_set)

        t_rad = t_amb + app                                  # radiator cold-branch outlet (K)
        # 3-way split so the blend hits the set-point. Clamp: if the loop is
        # already at/below the set-point the radiator idles (f=0); the radiator
        # can't blend warmer than t_in.
        denom = t_in - t_rad
        if denom > 1e-6 and t_in > t_set:
            f = (t_in - t_set) / denom
        else:
            f = 0.0
        f = min(1.0, max(0.0, f))

        q_rad_W = f * mdot * cp * (t_in - t_rad)             # W rejected to air
        t_out   = t_set if (mdot > 0 and t_in > t_set) else t_in
        fan_kW  = self._p("fan_frac") * q_rad_W / 1e3

        self._out_set("loop_out", Stream.water_steam(
            mdot=mdot, T=t_out, P=3e5, label="Radiator return (to HRSG feedwater)"))

        self._result("Radiator duty",       q_rad_W/1e3,        "kW",  "verified",
                     "heat rejected to ambient air")
        self._result("Loop flow",           mdot*3.6,           "m³/h","verified")
        self._result("Loop inlet temp",     t_in - 273.15,      "°C",  "verified")
        self._result("Radiator branch temp",t_rad - 273.15,     "°C",  "verified",
                     "ambient + approach")
        self._result("Return temp",         t_out - 273.15,     "°C",  "verified",
                     "3-way blend = set-point")
        self._result("Through-radiator split", f * 100.0,       "%",   "verified",
                     "3-way valve: fraction through the radiator")
        self._result("Ambient air temp",    t_amb - 273.15,     "°C",  "input")
        self._result("Radiator fan electrical", fan_kW,         "kW",  "screening",
                     "fan_frac × rejected heat (screening)")

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import pass_fail, bounds_check
        r = self.results
        t_out = r["Return temp"].value
        t_rad = r["Radiator branch temp"].value
        t_amb = r["Ambient air temp"].value
        split = r["Through-radiator split"].value
        return [
            pass_fail("T5: radiator branch > ambient (approach > 0)",
                passed=t_rad > t_amb,
                detail=f"T_rad={t_rad:.1f}°C > T_amb={t_amb:.1f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
            pass_fail("T5b: return ≥ radiator branch (can't blend below cold side)",
                passed=t_out >= t_rad - 1e-6,
                detail=f"T_return={t_out:.1f}°C ≥ T_rad={t_rad:.1f}°C",
                category="Second law", affects=["LiBr cooling capacity"]),
            bounds_check("P14: 3-way split in [0, 100]%",
                value=split, lo=0.0, hi=100.0, unit="%",
                affects=["LiBr cooling capacity"]),
        ]
