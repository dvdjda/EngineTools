"""
nexablock.core.stream — Stream and StreamKind.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Optional


class StreamKind(Enum):
    WATER_STEAM    = auto()  # IAPWS water / steam
    ENERGY         = auto()  # heat duty (W)
    ELECTRICAL     = auto()  # electrical power (W)
    GENERIC_FLUID  = auto()  # seawater, brine, coolant — simple props only


@dataclass
class Stream:
    """
    A process stream. All quantities in SI:
      mdot [kg/s], T [K], P [Pa], h [J/kg], power [W].
    For WATER_STEAM: any two of {T,P,h,x} fully specify state via props.py.
    For ENERGY/ELECTRICAL: use `power` only.
    For GENERIC_FLUID: mdot + T + P + props (cp, rho, salinity, etc.).
    """
    kind:  StreamKind
    mdot:  Optional[float] = None    # kg/s
    T:     Optional[float] = None    # K
    P:     Optional[float] = None    # Pa
    h:     Optional[float] = None    # J/kg
    x:     Optional[float] = None    # vapour quality [0,1]
    power: Optional[float] = None    # W (ENERGY / ELECTRICAL)
    props: dict            = field(default_factory=dict)
    label: str             = ""

    # ── convenience constructors ──────────────────────────────────────────────

    @classmethod
    def water_steam(cls, mdot: float, T: float, P: float,
                    h: Optional[float] = None, label: str = "") -> "Stream":
        return cls(kind=StreamKind.WATER_STEAM,
                   mdot=mdot, T=T, P=P, h=h, label=label)

    @classmethod
    def energy(cls, power: float, label: str = "") -> "Stream":
        return cls(kind=StreamKind.ENERGY, power=power, label=label)

    @classmethod
    def electrical(cls, power: float, label: str = "") -> "Stream":
        return cls(kind=StreamKind.ELECTRICAL, power=power, label=label)

    @classmethod
    def fluid(cls, mdot: float, T: float, P: float,
              cp: float = 4187.0, rho: float = 1000.0,
              label: str = "") -> "Stream":
        return cls(kind=StreamKind.GENERIC_FLUID,
                   mdot=mdot, T=T, P=P,
                   props={"cp": cp, "rho": rho}, label=label)

    def copy(self) -> "Stream":
        import copy
        return copy.deepcopy(self)

    # ── property helpers ──────────────────────────────────────────────────────

    @property
    def T_C(self) -> Optional[float]:
        return (self.T - 273.15) if self.T is not None else None

    @property
    def P_bar(self) -> Optional[float]:
        return (self.P / 1e5) if self.P is not None else None

    @property
    def mdot_tph(self) -> Optional[float]:
        return (self.mdot * 3600 / 1000) if self.mdot is not None else None

    @property
    def power_kW(self) -> Optional[float]:
        return (self.power / 1000) if self.power is not None else None

    def residual(self, other: "Stream") -> float:
        """Max relative residual against another stream (for convergence check)."""
        checks = []
        for attr in ("mdot", "T", "P", "h", "power"):
            a = getattr(self, attr)
            b = getattr(other, attr)
            if a is not None and b is not None and a != 0:
                checks.append(abs(a - b) / abs(a))
        return max(checks) if checks else 0.0

    def __repr__(self) -> str:
        if self.kind == StreamKind.WATER_STEAM:
            T_str = f"{self.T_C:.1f}°C" if self.T is not None else "T=?"
            P_str = f"{self.P_bar:.2f}bar" if self.P is not None else "P=?"
            m_str = f"{self.mdot_tph:.2f}t/h" if self.mdot is not None else "m=?"
            return f"Stream(WaterSteam {m_str} {T_str} {P_str})"
        if self.kind in (StreamKind.ENERGY, StreamKind.ELECTRICAL):
            return f"Stream({self.kind.name} {self.power_kW:.1f}kW)"
        return f"Stream({self.kind.name} mdot={self.mdot}kg/s)"
