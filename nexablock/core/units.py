"""
nexablock.core.units — unit conversion table (no external binary required).

All internal calculations use SI. Convert at block boundaries only.
"""
from __future__ import annotations

# Conversion factors: multiply *from* the key *to* SI
_TO_SI: dict[str, float] = {
    # Pressure
    "Pa": 1.0, "kPa": 1e3, "MPa": 1e6, "bar": 1e5, "bar a": 1e5,
    "psi": 6894.76, "atm": 101325.0,
    # Temperature offsets handled separately (see to_K / from_K)
    "K": 1.0,
    # Mass flow
    "kg/s": 1.0, "kg/h": 1/3600, "t/h": 1000/3600, "g/s": 1e-3,
    # Volume flow
    "m3/s": 1.0, "m3/h": 1/3600, "L/s": 1e-3, "L/min": 1e-3/60,
    # Energy / Power
    "W": 1.0, "kW": 1e3, "MW": 1e6, "J": 1.0, "kJ": 1e3, "MJ": 1e6,
    # Specific enthalpy
    "J/kg": 1.0, "kJ/kg": 1e3,
    # Specific entropy
    "J/(kg·K)": 1.0, "kJ/(kg·K)": 1e3,
    # Length / area / volume
    "m": 1.0, "mm": 1e-3, "m2": 1.0, "m3": 1.0,
    # Density
    "kg/m3": 1.0,
    # Dimensionless
    "-": 1.0, "%": 0.01,
    # Heat transfer coeff
    "W/(m2·K)": 1.0, "kW/(m2·K)": 1e3,
}

_TEMP_OFFSETS = {"°C": 273.15, "C": 273.15, "°F": None, "F": None}


def to_si(value: float, unit: str) -> float:
    """Convert *value* expressed in *unit* to SI."""
    if unit in _TEMP_OFFSETS:
        if unit in ("°C", "C"):
            return value + 273.15
        # Fahrenheit
        return (value - 32) * 5 / 9 + 273.15
    if unit in _TO_SI:
        return value * _TO_SI[unit]
    raise ValueError(f"Unknown unit '{unit}'")


def from_si(value_si: float, unit: str) -> float:
    """Convert *value_si* (SI) to *unit*."""
    if unit in _TEMP_OFFSETS:
        if unit in ("°C", "C"):
            return value_si - 273.15
        return (value_si - 273.15) * 9 / 5 + 32
    if unit in _TO_SI:
        return value_si / _TO_SI[unit]
    raise ValueError(f"Unknown unit '{unit}'")


def convert(value: float, from_unit: str, to_unit: str) -> float:
    return from_si(to_si(value, from_unit), to_unit)
