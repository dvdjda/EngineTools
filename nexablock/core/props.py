"""
nexablock.core.props — thin thermodynamic property helpers.

Primary backend: DWSIM SteamTables2.dll (IAPWS-IF97) via dwsim_props.py.
All functions accept and return SI units (Pa, K, J/kg, J/(kg·K), kg/m³).
"""
from __future__ import annotations
import math
import os
import sys

# ── Bootstrap dwsim_props from the EngineTools path ──────────────────────────
def _bootstrap():
    """Make nexa_toolkit importable if not already on path."""
    here = os.path.dirname(__file__)                    # nexablock/core/
    et   = os.path.normpath(os.path.join(here, "..", "..", ".."))  # EngineTools/
    if et not in sys.path:
        sys.path.insert(0, et)

_bootstrap()

try:
    import nexa_toolkit.dwsim_props as _dp
    _DP_OK = True
except Exception:
    _DP_OK = False

# ── CoolProp fallback ─────────────────────────────────────────────────────────
try:
    import CoolProp.CoolProp as _CP
    _CP_OK = True
except ImportError:
    _CP_OK = False


# ── Public API (SI units throughout) ─────────────────────────────────────────

def t_sat(P_Pa: float) -> float:
    """Saturation temperature (K) at pressure P (Pa). IAPWS-IF97."""
    P_bar = P_Pa / 1e5
    if _DP_OK:
        return _dp.t_sat(P_bar) + 273.15
    if _CP_OK:
        return _CP.PropsSI("T", "P", P_Pa, "Q", 0, "Water")
    # Antoine fallback
    import math
    p = max(P_bar, 0.001)
    return 1_730.63 / (5.19622 - math.log10(p)) - 233.426 + 273.15


def h_sat_liq(P_Pa: float) -> float:
    """Saturated liquid specific enthalpy (J/kg) at pressure P (Pa)."""
    P_bar = P_Pa / 1e5
    if _DP_OK:
        return _dp.h_liq(P_bar) * 1e3
    if _CP_OK:
        return _CP.PropsSI("H", "P", P_Pa, "Q", 0, "Water")
    return 4.19 * (t_sat(P_Pa) - 273.15) * 1e3


def h_sat_vap(P_Pa: float) -> float:
    """Saturated vapour specific enthalpy (J/kg) at pressure P (Pa)."""
    P_bar = P_Pa / 1e5
    if _DP_OK:
        return _dp.h_vap(P_bar) * 1e3
    if _CP_OK:
        return _CP.PropsSI("H", "P", P_Pa, "Q", 1, "Water")
    ts = t_sat(P_Pa) - 273.15
    return (4.19 * ts + 2501.4 - 2.3694 * ts) * 1e3


def h_steam(P_Pa: float, T_K: float) -> float:
    """Superheated (or sat.) steam specific enthalpy (J/kg)."""
    P_bar = P_Pa / 1e5
    T_C   = T_K - 273.15
    if _DP_OK:
        return _dp.h_steam(P_bar, T_C) * 1e3
    if _CP_OK:
        Ts = t_sat(P_Pa)
        T_K2 = max(T_K, Ts)
        return _CP.PropsSI("H", "P", P_Pa, "T", T_K2, "Water")
    # Linear correlation fallback
    ts = t_sat(P_Pa) - 273.15
    sh = max(T_C - ts, 0.0)
    return (4.19 * ts + 2501.4 - 2.3694 * ts + 2.10 * sh) * 1e3


def h_water(P_Pa: float, T_K: float) -> float:
    """Sub-cooled / compressed water specific enthalpy (J/kg)."""
    P_bar = P_Pa / 1e5
    T_C   = T_K - 273.15
    if _DP_OK:
        return _dp.h_feedwater(T_C, P_bar) * 1e3
    if _CP_OK:
        return _CP.PropsSI("H", "P", P_Pa, "T", T_K, "Water")
    return 4.19 * T_C * 1e3


def s_steam(P_Pa: float, T_K: float) -> float:
    """Steam specific entropy (J/(kg·K))."""
    if _DP_OK:
        s = _dp.s_steam(P_Pa / 1e5, T_K - 273.15)
        return s * 1e3 if s is not None else 0.0
    if _CP_OK:
        Ts = t_sat(P_Pa)
        T_K2 = max(T_K, Ts)
        return _CP.PropsSI("S", "P", P_Pa, "T", T_K2, "Water")
    return 0.0


def rho_steam(P_Pa: float, T_K: float) -> float:
    """Steam density (kg/m³)."""
    if _DP_OK:
        r = _dp.rho_steam(P_Pa / 1e5, T_K - 273.15)
        return r if r is not None else 5.0
    if _CP_OK:
        Ts = t_sat(P_Pa)
        T_K2 = max(T_K, Ts)
        return _CP.PropsSI("D", "P", P_Pa, "T", T_K2, "Water")
    return 5.0


def cp_exhgas(T_K: float) -> float:
    """Exhaust gas (air proxy) cp (J/(kg·K))."""
    if _DP_OK:
        return _dp.exh_cp(T_K - 273.15) * 1e3
    if _CP_OK:
        return _CP.PropsSI("Cpmass", "P", 101325.0, "T", T_K, "Air")
    # JANAF polynomial for air
    return (1.0575 + 1.47e-4 * T_K - 4.8e-8 * T_K**2) * 1e3


def ng_density(P_Pa: float, T_K: float, sg: float = 0.60) -> float:
    """Natural gas real-gas density (kg/m³). Methane proxy via CoolProp."""
    if _DP_OK:
        return _dp.ng_props(P_Pa / 1e5, T_K - 273.15, sg)["rho"]
    if _CP_OK:
        return _CP.PropsSI("D", "P", P_Pa, "T", T_K, "Methane")
    MW = sg * 28.97
    return P_Pa * (MW / 1e3) / (8314.0 * T_K)


def backend_status() -> dict:
    """Return which property backends are active."""
    s = {"dwsim_props": _DP_OK, "coolprop": _CP_OK}
    if _DP_OK:
        st = _dp.status()
        s["SteamTables2"] = st.get("SteamTables2_IAPWS97", False)
    return s
