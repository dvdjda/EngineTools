"""
Nexa Block v1 - process toolkit
Module 1: single-effect LiBr-water absorption chiller - balance engine

What it does
------------
Given a design point (chilled-water, cooling-water and heat-source temperatures
plus the required cooling duty) it returns:
  - weak / strong LiBr concentrations  (Duhring equilibrium)
  - circulation ratio and mass flows
  - the four duties: evaporator, condenser, generator, absorber
  - COP
  - crystallisation margin on the cold strong-solution point

Property data and references (VERIFY before any certifiable use)
----------------------------------------------------------------
  - Pure water / steam saturation pressure and temperature : CoolProp (IAPWS-95).
  - LiBr-H2O equilibrium (Duhring T-X relation)            : ASHRAE / Herold-Klein
    polynomial coefficients (A_i, B_i below). Confident set, valid ~45-70 % LiBr.
  - LiBr solution enthalpy h(T,X)                          : ASHRAE polynomial
    (A_n, B_n, C_n below). Coefficients transcribed from memory - flagged VERIFY.
  - Water vapour / liquid enthalpy in the energy balance   : simple 0 degC-liquid
    reference (h_f = 4.186 T, h_g = 2501 + 1.88 T) to stay consistent with the
    solution-enthalpy reference. This is the classic textbook screening method.

Status: SCREENING ONLY. The concentration / crystallisation outputs are solid
screening numbers. The absolute duties depend on the enthalpy correlations above
and are screening-grade. ChemCAD remains the system of record for certifiable
numbers. Verify duties and the enthalpy coefficients against Herold/ASHRAE/ChemCAD.
"""

from dataclasses import dataclass
from scipy.optimize import brentq
from CoolProp.CoolProp import PropsSI


# --- LiBr-H2O equilibrium: Duhring T-X relation (ASHRAE / Herold-Klein) ---
# T_solution(degC) = sum B_i X^i + T_refrig_dew(degC) * sum A_i X^i ,  X in mass %
_A = (-2.00755, 0.16976, -3.133362e-3, 1.97668e-5)
_B = (124.937, -7.71649, 0.152286, -7.9509e-4)


def _poly(coeffs, x):
    return sum(c * x ** i for i, c in enumerate(coeffs))


def solution_temp(x_pct, t_dew_c):
    """Equilibrium solution temperature (degC) for LiBr mass % and refrigerant dew temp."""
    return _poly(_B, x_pct) + t_dew_c * _poly(_A, x_pct)


def concentration(t_sol_c, t_dew_c):
    """Invert Duhring: LiBr mass % at given solution temp and refrigerant dew temp."""
    f = lambda x: solution_temp(x, t_dew_c) - t_sol_c
    return brentq(f, 40.0, 70.0)


# --- LiBr solution enthalpy h(T,X) - ASHRAE polynomial (VERIFY coefficients) ---
# h(kJ/kg) = sum A_n X^n + T sum B_n X^n + T^2 sum C_n X^n ;  T in degC, X mass %
_HA = (-2024.33, 163.309, -4.88161, 6.302948e-2, -2.913705e-4)
_HB = (18.2829, -1.1691757, 3.248041e-2, -4.034184e-4, 1.8520569e-6)
_HC = (-3.7008214e-2, 2.8877666e-3, -8.1313015e-5, 9.9116628e-7, -4.4441207e-9)


def solution_enthalpy(t_c, x_pct):
    """LiBr solution specific enthalpy (kJ/kg), 0 degC-liquid-water reference basis."""
    return _poly(_HA, x_pct) + t_c * _poly(_HB, x_pct) + t_c ** 2 * _poly(_HC, x_pct)


# --- water side (0 degC liquid reference, consistent with solution enthalpy) ---
def water_psat_kpa(t_c):
    return PropsSI("P", "T", t_c + 273.15, "Q", 0, "Water") / 1000.0


def hf_water(t_c):
    return 4.186 * t_c          # saturated liquid, kJ/kg


def hg_water(t_c):
    return 2501.0 + 1.88 * t_c  # saturated/low-pressure vapour, kJ/kg


# --- crystallisation line (approximate solubility boundary, VERIFY) ---
def x_crystallisation(t_c):
    """Approx LiBr mass % at the crystallisation line for a given temperature."""
    # rough fit through textbook solubility points; screening guide only
    return 57.0 + 0.13 * t_c


@dataclass
class DesignPoint:
    t_chw_out_c: float      # chilled-water supply temperature
    t_cw_in_c: float        # cooling-water inlet temperature
    t_hot_c: float          # heat-source (e.g. turbine waste-heat hot water) temp
    q_evap_kw: float        # required cooling duty
    # approaches (defaults are reasonable starting points)
    dt_evap: float = 5.0    # refrigerant colder than chilled water
    dt_cond: float = 8.0    # condensing temp above cooling water
    dt_abs: float = 5.0     # absorber temp above cooling water
    dt_gen: float = 5.0     # generator temp below hot source
    shx_eff: float = 0.7    # solution heat-exchanger effectiveness


def solve(dp: DesignPoint):
    # saturation temperatures from the design point
    t_evap = dp.t_chw_out_c - dp.dt_evap
    t_cond = dp.t_cw_in_c + dp.dt_cond
    t_abs = dp.t_cw_in_c + dp.dt_abs
    t_gen = dp.t_hot_c - dp.dt_gen

    p_low = water_psat_kpa(t_evap)   # evaporator + absorber
    p_high = water_psat_kpa(t_cond)  # generator + condenser

    # concentrations from equilibrium
    x_weak = concentration(t_abs, t_evap)    # dilute, leaves absorber
    x_strong = concentration(t_gen, t_cond)  # concentrated, leaves generator
    if x_strong <= x_weak:
        raise ValueError("No concentration swing - check temperatures "
                         "(generator too cool or absorber too warm).")

    # refrigerant flow from evaporator duty
    h_refrig_in = hf_water(t_cond)   # throttled liquid entering evaporator
    h_refrig_out = hg_water(t_evap)  # saturated vapour leaving evaporator
    m_refrig = dp.q_evap_kw / (h_refrig_out - h_refrig_in)  # kg/s

    # solution mass balance (LiBr conserved)
    f = x_strong / (x_strong - x_weak)   # circulation ratio = m_weak / m_refrig
    m_weak = f * m_refrig
    m_strong = m_weak - m_refrig

    # solution heat exchanger: strong (hot) preheats weak (cold)
    h_weak_abs = solution_enthalpy(t_abs, x_weak)
    h_strong_gen = solution_enthalpy(t_gen, x_strong)
    # weak heated, strong cooled, by SHX effectiveness on the smaller stream (strong)
    cp_min_stream = m_strong
    t_weak_in_gen = t_abs + dp.shx_eff * (t_gen - t_abs)  # simplified temp-based
    t_strong_to_abs = t_gen - dp.shx_eff * (t_gen - t_abs) * (m_weak / m_strong) \
        if m_strong > 0 else t_abs
    h_weak_in_gen = solution_enthalpy(t_weak_in_gen, x_weak)
    h_strong_to_abs = solution_enthalpy(max(t_strong_to_abs, t_abs), x_strong)

    # generator vapour leaves at generator temperature
    h_vap_gen = hg_water(t_gen)

    # duties by component energy balance
    q_gen = m_strong * h_strong_gen + m_refrig * h_vap_gen - m_weak * h_weak_in_gen
    q_cond = m_refrig * (h_vap_gen - hf_water(t_cond))
    q_abs = m_refrig * h_refrig_out + m_strong * h_strong_to_abs - m_weak * h_weak_abs
    q_evap = dp.q_evap_kw

    cop = q_evap / q_gen if q_gen > 0 else float("nan")

    # crystallisation margin at the coldest strong point (strong leaving SHX -> absorber)
    t_strong_cold = max(t_strong_to_abs, t_abs)
    x_crys = x_crystallisation(t_strong_cold)
    cryst_margin = x_crys - x_strong   # positive = safe; negative = crystallising

    return {
        "t_evap_c": t_evap, "t_cond_c": t_cond, "t_abs_c": t_abs, "t_gen_c": t_gen,
        "p_low_kpa": p_low, "p_high_kpa": p_high,
        "x_weak_pct": x_weak, "x_strong_pct": x_strong,
        "circulation_ratio": f,
        "m_refrig_kgps": m_refrig, "m_weak_kgps": m_weak, "m_strong_kgps": m_strong,
        "q_evap_kw": q_evap, "q_cond_kw": q_cond, "q_gen_kw": q_gen, "q_abs_kw": q_abs,
        "cop": cop,
        "t_strong_cold_c": t_strong_cold,
        "x_crystallisation_pct": x_crys, "cryst_margin_pct": cryst_margin,
    }


def report(dp: DesignPoint):
    r = solve(dp)
    print("Single-effect LiBr-H2O absorption chiller - screening balance")
    print("=" * 60)
    print("DESIGN POINT (input)")
    print(f"  chilled-water supply : {dp.t_chw_out_c:6.1f} degC")
    print(f"  cooling-water inlet  : {dp.t_cw_in_c:6.1f} degC")
    print(f"  heat source          : {dp.t_hot_c:6.1f} degC")
    print(f"  cooling duty         : {dp.q_evap_kw:6.1f} kW")
    print("-" * 60)
    print("SATURATION CONDITIONS")
    print(f"  evaporator  {r['t_evap_c']:6.1f} degC   absorber  {r['t_abs_c']:6.1f} degC")
    print(f"  condenser   {r['t_cond_c']:6.1f} degC   generator {r['t_gen_c']:6.1f} degC")
    print(f"  low side  {r['p_low_kpa']:7.3f} kPa   high side {r['p_high_kpa']:7.3f} kPa")
    print("-" * 60)
    print("SOLUTION")
    print(f"  weak (dilute)   {r['x_weak_pct']:5.1f} % LiBr")
    print(f"  strong (conc.)  {r['x_strong_pct']:5.1f} % LiBr")
    print(f"  swing           {r['x_strong_pct']-r['x_weak_pct']:5.1f} %")
    print(f"  circulation ratio f = {r['circulation_ratio']:5.2f}")
    print("-" * 60)
    print("MASS FLOWS")
    print(f"  refrigerant {r['m_refrig_kgps']:6.3f} kg/s")
    print(f"  weak sol.   {r['m_weak_kgps']:6.3f} kg/s   strong sol. {r['m_strong_kgps']:6.3f} kg/s")
    print("-" * 60)
    print("DUTIES  (screening-grade - verify vs ChemCAD)")
    print(f"  evaporator  {r['q_evap_kw']:7.1f} kW")
    print(f"  condenser   {r['q_cond_kw']:7.1f} kW")
    print(f"  generator   {r['q_gen_kw']:7.1f} kW")
    print(f"  absorber    {r['q_abs_kw']:7.1f} kW")
    bal = r['q_evap_kw'] + r['q_gen_kw'] - r['q_cond_kw'] - r['q_abs_kw']
    print(f"  energy check (Qe+Qg-Qc-Qa) = {bal:7.2f} kW  (should be ~0)")
    print(f"  COP = {r['cop']:.3f}")
    print("-" * 60)
    print("CRYSTALLISATION")
    print(f"  cold strong point {r['t_strong_cold_c']:5.1f} degC")
    print(f"  crystallisation line {r['x_crystallisation_pct']:5.1f} % ; "
          f"margin {r['cryst_margin_pct']:+5.1f} % "
          f"({'SAFE' if r['cryst_margin_pct'] > 0 else 'AT RISK'})")
    return r


if __name__ == "__main__":
    # PLACEHOLDER data-centre case - replace with your real design point
    demo = DesignPoint(
        t_chw_out_c=10.0,   # chilled water supply
        t_cw_in_c=30.0,     # cooling water inlet
        t_hot_c=90.0,       # turbine waste-heat hot water
        q_evap_kw=500.0,    # cooling duty
    )
    report(demo)
