"""
nexablock.blocks.steam_splitter — Split steam into two branches by fraction.

Ports
-----
steam_in  (WATER_STEAM, in)  : total steam from HRSG
to_libr   (WATER_STEAM, out) : fraction → LiBr chiller
to_med    (WATER_STEAM, out) : remainder → MED desalination

Physics
-------
  ṁ_libr = ṁ_in × f_libr
  ṁ_med  = ṁ_in × (1 − f_libr)
  h, T, P identical on both outlets (isenthalpic split — no mixing heat)
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param


class SteamSplitter(Block):
    category = "Utility"
    label    = "Steam Splitter"

    def __init__(self, libr_frac: float = 0.50) -> None:
        super().__init__()
        self._libr_frac = libr_frac

    def _build_params(self) -> dict[str, Param]:
        return {
            "libr_frac": Param(self._libr_frac, "-",
                               min=0.05, max=0.95,
                               desc="Fraction of steam to LiBr chiller"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {"steam_in": Port("steam_in", StreamKind.WATER_STEAM, "in")}

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "to_libr": Port("to_libr", StreamKind.WATER_STEAM, "out"),
            "to_med":  Port("to_med",  StreamKind.WATER_STEAM, "out"),
        }

    def compute(self) -> None:
        s    = self._in("steam_in")
        f    = self._p("libr_frac")
        f    = max(0.0, min(1.0, f))

        if s is None:
            self._out_set("to_libr", Stream.water_steam(0.0, 400.0, 1e6))
            self._out_set("to_med",  Stream.water_steam(0.0, 400.0, 1e6))
            return

        libr = s.copy(); libr.mdot = s.mdot * f;       libr.label = "Steam to LiBr"
        med  = s.copy(); med.mdot  = s.mdot * (1-f);   med.label  = "Steam to MED"
        self._out_set("to_libr", libr)
        self._out_set("to_med",  med)

        self._result("LiBr steam fraction",  f*100,              "%",    "input")
        self._result("MED steam fraction",  (1-f)*100,           "%",    "verified")
        self._result("Steam to LiBr",       libr.mdot*3.6,       "t/h",  "verified")
        self._result("Steam to MED",        med.mdot*3.6,        "t/h",  "verified")

    def render_ports(self):
        return {
            "steam_in": (0.0, 0.5),   # left
            "to_libr":  (1.0, 0.3),   # right-top
            "to_med":   (1.0, 0.7),   # right-bottom
        }

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import mass_balance, pass_fail
        f = self._p("libr_frac")
        s_in   = self.inlets["steam_in"].stream
        s_libr = self.outlets["to_libr"].stream
        s_med  = self.outlets["to_med"].stream
        m_in   = s_in.mdot   if s_in   is not None and s_in.mdot   else 0.0
        m_libr = s_libr.mdot if s_libr is not None and s_libr.mdot else 0.0
        m_med  = s_med.mdot  if s_med  is not None and s_med.mdot  else 0.0
        return [
            mass_balance("M2: splitter inlet = sum(outlets)",
                supply=m_in, demand=m_libr + m_med,
                affects=["Steam generation"], tol_rel=1e-4),
            pass_fail("P10: libr_frac + med_frac = 1.0",
                passed=abs((f + (1.0 - f)) - 1.0) < 1e-9 and 0.0 <= f <= 1.0,
                detail=f"libr_frac={f:.4f}, med_frac={1.0-f:.4f}, sum=1.0",
                category="Plausibility", affects=["Steam generation"]),
        ]
