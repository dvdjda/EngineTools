"""
nexablock.blocks.gpu_cassette — Immersed-GPU cassette mass/energy balance.

Single-phase immersion cooling block.

Ports
-----
inlet  (GENERIC_FLUID)  : coolant supply — mdot, T_supply, P
outlet (GENERIC_FLUID)  : coolant return — same mdot, T_return, same P
heat   (ENERGY, out)    : heat load handed to the chiller (= q_kW)

Physics
-------
  IT power   = n_gpu × p_gpu
  Heat load  = IT_power × (1 + aux_frac)          [all IT → heat + overhead]
  mdot       = q / (cp × ΔT)
  T_return   = T_supply + ΔT

Reference
---------
  ASHRAE TC 9.9 — Thermal Guidelines for Data Processing Environments, 4th ed.
"""
from __future__ import annotations
from ..core.block    import Block
from ..core.port     import Port
from ..core.stream   import Stream, StreamKind
from ..core.quantity import Param, Result
from ..validation.reference import Reference, TestCase


class GPUCassette(Block):
    """Immersed-GPU cassette cooling block."""

    category = "DataCenter"
    label    = "GPU Cassette"

    def __init__(
        self,
        n_gpu:       int   = 72,
        p_gpu_kW:    float = 1.0,
        aux_frac:    float = 0.15,
        coolant_cp:  float = 2100.0,   # J/kg·K  (dielectric fluid, e.g. Novec)
        coolant_rho: float = 780.0,    # kg/m³
        dt_K:        float = 12.0,     # coolant ΔT K
    ) -> None:
        super().__init__()
        self._n_gpu       = n_gpu
        self._p_gpu_kW    = p_gpu_kW
        self._aux_frac    = aux_frac
        self._coolant_cp  = coolant_cp
        self._coolant_rho = coolant_rho
        self._dt_K        = dt_K

    # ── contract ──────────────────────────────────────────────────────────────

    def _build_params(self) -> dict[str, Param]:
        return {
            "n_gpu":       Param(float(self._n_gpu),    "-",    min=1,   max=2000, desc="GPUs per cassette"),
            "p_gpu_W":     Param(self._p_gpu_kW * 1e3, "W",    min=100, max=5000, desc="Power per GPU"),
            "aux_frac":    Param(self._aux_frac,        "-",    min=0.0, max=1.0,  desc="Non-GPU overhead fraction"),
            "coolant_cp":  Param(self._coolant_cp,      "J/(kg·K)", min=500, max=5000, desc="Coolant specific heat"),
            "coolant_rho": Param(self._coolant_rho,     "kg/m³",    min=500, max=1400, desc="Coolant density"),
            "dt":          Param(self._dt_K,            "K",    min=2,   max=40,   desc="Coolant temperature rise"),
        }

    def _build_inlets(self) -> dict[str, Port]:
        return {
            "coolant_in": Port("coolant_in", StreamKind.GENERIC_FLUID, "in"),
        }

    def _build_outlets(self) -> dict[str, Port]:
        return {
            "coolant_out": Port("coolant_out", StreamKind.GENERIC_FLUID, "out"),
            "heat":        Port("heat",        StreamKind.ENERGY,         "out"),
        }

    # ── physics ───────────────────────────────────────────────────────────────

    def compute(self) -> None:
        # Params
        n    = self._p("n_gpu")
        p_W  = self._p("p_gpu_W")
        aux  = self._p("aux_frac")
        cp   = self._p("coolant_cp")
        rho  = self._p("coolant_rho")
        dt   = self._p("dt")

        # Inlet stream — T_supply and P from connected stream if provided
        s_in = self._in("coolant_in")
        if s_in is not None:
            T_sup = s_in.T or (30 + 273.15)
            P_in  = s_in.P or 3e5
        else:
            T_sup = 30 + 273.15    # K   default supply
            P_in  = 3e5            # Pa

        # Core energy balance
        it_power_W  = n * p_W                          # W
        q_W         = it_power_W * (1.0 + aux)        # W  total heat to remove
        mdot        = q_W / (cp * dt)                  # kg/s
        T_ret       = T_sup + dt                       # K
        vol_m3s     = mdot / rho                       # m³/s
        vol_Lpm     = vol_m3s * 1000 * 60              # L/min

        # Set outlet streams
        coolant_out = Stream.fluid(
            mdot=mdot, T=T_ret, P=P_in, cp=cp, rho=rho,
            label="GPU coolant return")
        self._out_set("coolant_out", coolant_out)
        self._out_set("heat", Stream.energy(power=q_W, label="GPU cassette heat load"))

        overhead_W = it_power_W * aux             # cassette overhead (pumps / ctrl / etc) inside the enclosure

        # Results
        self._result("IT power",        it_power_W / 1e3,  "kW",    "verified",
                     "GPUs × p_gpu (all IT → heat)")
        self._result("Cassette overhead electrical",
                     overhead_W / 1e3,    "kW",    "verified",
                     "IT × aux_frac (pumps/controls inside the cassette)")
        self._result("Heat load",       q_W        / 1e3,  "kW",    "verified",
                     "IT + cassette overhead — both dissipate into the coolant")
        self._result("Coolant mdot",    mdot,              "kg/s",  "verified")
        self._result("Coolant vol flow",vol_Lpm,           "L/min", "verified")
        self._result("Supply temp",     T_sup - 273.15,    "°C",    "input")
        self._result("Return temp",     T_ret - 273.15,    "°C",    "verified")
        self._result("ΔT coolant",      dt,                "K",     "input")
        self._result("PUE  (approx)",   (1.0 + aux),       "-",     "screening",
                     "≈ 1 for immersion (only pump overhead)")

    # ── metadata ──────────────────────────────────────────────────────────────

    def references(self) -> list:
        return [
            Reference("ASHRAE TC 9.9 Thermal Guidelines, 4th ed.",
                      "single-phase immersion cooling mass/energy balance",
                      kind="standard"),
        ]

    def test_cases(self) -> list:
        """
        Fixture §8.1 — 72 GPUs × 1 kW, dielectric (cp=2100, rho=780), ΔT=12K.
        Expected (within ±2%):
          IT power    = 72 kW
          Heat load   = 82.8 kW
          Coolant flow = 3.28 L/min
          Return temp  = 42 °C  (supply = 30 °C)
        """
        from ..core.stream import Stream, StreamKind
        inlet = Stream.fluid(mdot=0.066, T=303.15, P=3e5, cp=2100, rho=780,
                             label="supply")
        return [
            TestCase(
                params=dict(n_gpu=72, p_gpu_kW=1.0, aux_frac=0.15,
                            coolant_cp=2100.0, coolant_rho=780.0, dt_K=12.0),
                inlets={"coolant_in": inlet},
                expected={
                    "IT power":   72.0,
                    "Heat load":  82.8,
                    "Return temp":42.0,
                },
                tol=0.02,
                note="Baseline cassette fixture §8.1",
            )
        ]

    def render_ports(self) -> dict[str, tuple[float, float]]:
        return {
            "coolant_in":  (0.0, 0.5),   # left centre
            "coolant_out": (1.0, 0.5),   # right centre
            "heat":        (0.5, 0.0),   # top centre
        }

    # ── audit ───────────────────────────────────────────────────────────────

    def audit_checks(self) -> list:
        from ..audit import (mass_balance, energy_balance, pass_fail,
                              bounds_check)
        r = self.results
        it_kW       = r["IT power"].value
        overhead_kW = r["Cassette overhead electrical"].value
        heat_kW     = r["Heat load"].value
        pue         = r["PUE  (approx)"].value
        coolant_in  = self.inlets["coolant_in"].stream
        coolant_out = self.outlets["coolant_out"].stream
        m_in  = coolant_in.mdot  if coolant_in  is not None and coolant_in.mdot  else 0.0
        m_out = coolant_out.mdot if coolant_out is not None and coolant_out.mdot else 0.0
        return [
            energy_balance("E7: Heat_load = IT_power + Cassette_overhead",
                supply=heat_kW, demand=it_kW + overhead_kW,
                affects=["GPU IT load"], tol_rel=1e-3),
            pass_fail("M7: coolant inlet supply ≥ cassette flow demand",
                passed=m_in >= m_out * 0.999,
                detail=f"inlet {m_in:.2f} kg/s ≥ cassette {m_out:.2f} kg/s "
                       f"(headroom {m_in - m_out:+.2f} kg/s)",
                category="Mass closure", affects=["GPU IT load"]),
            bounds_check("P7: PUE ≥ 1.0",
                value=pue, lo=1.0, hi=10.0, unit="-",
                affects=["GPU IT load"]),
        ]
