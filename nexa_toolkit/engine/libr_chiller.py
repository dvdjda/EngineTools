"""
Nexa Block v1 - process toolkit
Module 1: LiBr-water absorption chiller - balance engine (single + double effect)

What it does
------------
Given a design point (chilled-water, cooling-water and heat-source temperatures,
the required cooling duty, and the cycle EFFECT) it returns:
  - weak / strong LiBr concentrations
  - circulation ratio and mass flows
  - the four duties: evaporator, condenser, generator, absorber
  - COP
  - crystallisation margin on the cold strong-solution point

OEM calibration (BROAD XII Non-Electric Chiller, datasheet 1711 - treated as truth)
-----------------------------------------------------------------------------------
The cycle is calibrated to the BROAD XII rated points. At the common rated
condition (chilled water 7/14 degC, cooling water 30/37 degC) the model
reproduces the nameplate:

  single-effect : COP 0.76 (hot-water 98/88 degC drive), solution conc. ~43 %
  double-effect : COP 1.42 (direct-fired, exhaust ~160 degC), solution conc. ~54 %

(BROAD single-stage steam variant is COP 0.79 at 0.1 MPa; we anchor single-effect
to the hot-water 0.76 figure.) Off the rated point, COP follows an ideal-cycle
shape factor anchored to the nameplate, and the LiBr concentration band is the
OEM nominal concentration with a lift-scaled swing. The four duties close on the
overall energy balance (Qe + Qg = Qc + Qa) by construction.

Property data and references
----------------------------
  - Pure water / steam saturation pressure : CoolProp (IAPWS-95).
  - LiBr-H2O equilibrium (Duhring T-X relation) and solution enthalpy : ASHRAE /
    Herold-Klein polynomials (kept below for reference / cross-checks).
  - Water vapour / liquid enthalpy : 0 degC-liquid reference
    (h_f = 4.186 T, h_g = 2501 + 1.88 T), the classic textbook screening basis.

Status: DRAFT, calibrated to OEM nameplate. The rated-point COP and nominal
concentration reproduce the verified BROAD datasheet; off-design values and the
duty / crystallisation breakdown are screening-grade. ChemCAD remains the system
of record for certifiable numbers. David verifies before promotion.
"""

from dataclasses import dataclass
from scipy.optimize import brentq
from CoolProp.CoolProp import PropsSI


# --- OEM anchor points (BROAD XII Non-Electric Chiller, datasheet 1711) ---
# Common rated condition for both effects: chilled water 7/14 degC, cooling 30/37.
_RATED_CHW_C = 7.0
_RATED_CW_C  = 30.0
# Natural-gas heating value, OEM basis (BROAD: 10 kWh/Nm3 = 8600 kcal/Nm3).
# With the gas-basis direct-fired COP, fuel = generator heat / 10 reproduces the
# DFA gas-consumption table (BZ20 233 kW -> 16.4 vs 16.2 Nm3/h).
_NG_KWH_PER_NM3 = 10.0
# cop_max = cop_rated: the OEM nameplate is the ceiling. COP holds at nameplate
# for any drive at/above the rated drive and degrades below it, so each cycle
# shows its nameplate at its design point and a too-cool drive (e.g. a 98 degC
# source on the double-effect cycle) reads a physically lower COP rather than
# exceeding the datasheet.
_OEM = {
    "single": dict(label="single-effect", cop_rated=0.76, x_nominal_pct=43.0,
                   t_hot_rated_c=98.0,  cop_max=0.76, swing_rated_pct=5.0),
    "double": dict(label="double-effect", cop_rated=1.42, x_nominal_pct=54.0,
                   t_hot_rated_c=150.0, cop_max=1.42, swing_rated_pct=6.0),
}
# Below this fraction of its rated drive a double-effect cycle is heat-quality
# limited (the HTG can't run); flagged on the diagram.
_DOUBLE_MIN_DRIVE_C = 135.0


# --- LiBr-H2O equilibrium: Duhring T-X relation (ASHRAE / Herold-Klein) ---
# Kept for reference / cross-checks. T_solution(degC) = sum B_i X^i + T_dew * sum A_i X^i
_A = (-2.00755, 0.16976, -3.133362e-3, 1.97668e-5)
_B = (124.937, -7.71649, 0.152286, -7.9509e-4)


def _poly(coeffs, x):
    return sum(c * x ** i for i, c in enumerate(coeffs))


def solution_temp(x_pct, t_dew_c):
    """Equilibrium solution temperature (degC) for LiBr mass % and refrigerant dew temp."""
    return _poly(_B, x_pct) + t_dew_c * _poly(_A, x_pct)


def concentration(t_sol_c, t_dew_c):
    """Invert Duhring: LiBr mass % at given solution temp and refrigerant dew temp.
    Reference helper; the calibrated cycle anchors concentration to the OEM nominal
    instead, so this is no longer on the solve() critical path."""
    f = lambda x: solution_temp(x, t_dew_c) - t_sol_c
    return brentq(f, 40.0, 70.0)


# --- LiBr solution enthalpy h(T,X) - ASHRAE polynomial (reference) ---
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


# --- crystallisation line (approximate solubility boundary, screening) ---
def x_crystallisation(t_c):
    """Approx LiBr mass % at the crystallisation line for a given temperature."""
    return 57.0 + 0.13 * t_c


def _ideal_cop(t_evap_c, t_cond_c, t_abs_c, t_gen_c):
    """Reversible single-stage absorption COP (the cycle 'shape' factor).
    Used as a ratio against the rated point, so the absolute level is set by the
    OEM nameplate, not by this expression. Returns 0 if the cycle cannot run."""
    Te, Tc, Ta, Tg = (t + 273.15 for t in (t_evap_c, t_cond_c, t_abs_c, t_gen_c))
    if Tg <= Ta or Tc <= Te:
        return 0.0
    return (Te * (Tg - Ta)) / (Tg * (Tc - Te))


@dataclass
class DesignPoint:
    t_chw_out_c: float      # chilled-water supply temperature
    t_cw_in_c: float        # cooling-water inlet temperature
    t_hot_c: float          # heat-source (waste-heat hot water / steam) temp
    q_evap_kw: float        # required cooling duty
    effect: str = "single"  # "single" | "double"  - cycle effect
    # optional backup burner (make-up: waste heat first, gas tops up the shortfall)
    burner_on: bool = False             # gas burner makes up any generator-heat shortfall
    q_source_avail_kw: float = float("inf")  # waste-heat duty cap to the generator;
                                        # inf (default) = uncapped -> legacy behaviour
    # approaches (defaults are reasonable starting points)
    dt_evap: float = 5.0    # refrigerant colder than chilled water
    dt_cond: float = 8.0    # condensing temp above cooling water
    dt_abs: float = 5.0     # absorber temp above cooling water
    dt_gen: float = 5.0     # generator temp below hot source
    shx_eff: float = 0.7    # solution heat-exchanger effectiveness (reference)


def solve(dp: DesignPoint):
    effect = (dp.effect or "single").lower()
    if effect not in _OEM:
        raise ValueError(f"effect must be 'single' or 'double', got {dp.effect!r}")
    oem = _OEM[effect]

    # saturation temperatures from the design point
    t_evap = dp.t_chw_out_c - dp.dt_evap
    t_cond = dp.t_cw_in_c + dp.dt_cond
    t_abs = dp.t_cw_in_c + dp.dt_abs
    t_gen = dp.t_hot_c - dp.dt_gen

    p_low = water_psat_kpa(t_evap)   # evaporator + absorber
    p_high = water_psat_kpa(t_cond)  # generator + condenser

    # rated reference temperatures for this effect (same chilled/cooling, OEM drive)
    te_r = _RATED_CHW_C - dp.dt_evap
    tc_r = _RATED_CW_C + dp.dt_cond
    ta_r = _RATED_CW_C + dp.dt_abs
    tg_r = oem["t_hot_rated_c"] - dp.dt_gen

    # --- COP: OEM nameplate anchor x ideal-cycle shape factor (calibrated) ---
    shape_now = _ideal_cop(t_evap, t_cond, t_abs, t_gen)
    shape_rated = _ideal_cop(te_r, tc_r, ta_r, tg_r)
    if shape_now <= 0.0:
        raise ValueError(
            f"Heat source too cool to drive the {oem['label']} cycle: generator "
            f"{t_gen:.0f} degC must exceed absorber {t_abs:.0f} degC.")
    cop = oem["cop_rated"] * shape_now / shape_rated
    cop = max(0.05, min(cop, oem["cop_max"]))

    # --- concentrations: OEM nominal band with lift-scaled swing (calibrated) ---
    lift_now = t_cond - t_evap
    lift_rated = tc_r - te_r
    swing = oem["swing_rated_pct"] * (lift_now / lift_rated) if lift_rated > 0 else \
        oem["swing_rated_pct"]
    x_nominal = oem["x_nominal_pct"]
    x_weak = x_nominal - swing / 2.0
    x_strong = x_nominal + swing / 2.0
    f = x_strong / (x_strong - x_weak) if x_strong > x_weak else float("nan")

    # --- heat source + optional make-up burner --------------------------------
    # Generator heat demanded by the requested cooling duty (OEM-COP basis).
    q_evap_req = dp.q_evap_kw
    q_gen_demand = q_evap_req / cop
    avail = dp.q_source_avail_kw
    if avail >= q_gen_demand:                 # waste heat alone meets demand
        q_gen, q_evap = q_gen_demand, q_evap_req
        burner_heat = 0.0
        cooling_deficit = 0.0
    elif dp.burner_on:                        # source short -> gas burner makes it up
        q_gen, q_evap = q_gen_demand, q_evap_req
        burner_heat = q_gen_demand - avail
        cooling_deficit = 0.0
    else:                                     # source short, no burner -> cooling limited
        q_gen = avail
        q_evap = avail * cop
        burner_heat = 0.0
        cooling_deficit = q_evap_req - q_evap
    # OEM gas basis (10 kWh/Nm3) reproduces the direct-fired DFA gas table.
    fuel_nm3h = burner_heat / _NG_KWH_PER_NM3

    # --- refrigerant + solution mass flows (on the delivered cooling duty) ---
    h_refrig_in = hf_water(t_cond)   # throttled liquid entering evaporator
    h_refrig_out = hg_water(t_evap)  # saturated vapour leaving evaporator
    m_refrig = q_evap / (h_refrig_out - h_refrig_in)  # kg/s
    m_weak = f * m_refrig
    m_strong = m_weak - m_refrig

    # --- duties: COP sets the generator input, energy balance closes the rest ---
    q_cond = m_refrig * (hg_water(t_cond) - hf_water(t_cond))  # latent rejected
    q_abs = q_evap + q_gen - q_cond                            # overall balance closes

    # --- double-effect generator staging (HTG + LTG, three pressure levels) ----
    # In a single-effect machine the generator and condenser share the high side
    # (p_high = Psat(T_cond)); the solution sits well above pure-water saturation
    # because of the LiBr boiling-point elevation, so e.g. 93 degC solution at
    # 6.6 kPa is consistent. A double-effect machine adds a high-temperature
    # generator (HTG) at a THIRD, higher pressure: its vapour condenses at an
    # intermediate temperature and that latent heat drives the low-temperature
    # generator (LTG), which boils at the condenser pressure. Hence three levels:
    #   HTG (high)  >  LTG = condenser (mid = p_high)  >  evaporator = absorber (low)
    stage = {}
    if effect == "double":
        # LTG solution boils at the condenser pressure, Duhring-elevated.
        t_ltg = min(max(solution_temp(x_strong, t_cond), t_cond + 5.0), t_gen - 10.0)
        t_int = min(t_ltg + 8.0, t_gen - 3.0)          # HTG-vapour condensing temp
        p_htg = water_psat_kpa(t_int)                  # HTG operates at this pressure
        # Internal heat recovery: the HTG-generated refrigerant (~half the total)
        # gives up its latent heat to boil the LTG. Screening estimate.
        q_internal = 0.5 * m_refrig * (hg_water(t_int) - hf_water(t_int))
        stage = {
            "htg_t_c": t_gen,  "htg_p_kpa": p_htg,
            "ltg_t_c": t_ltg,  "ltg_p_kpa": p_high,
            "int_cond_t_c": t_int, "q_internal_kw": q_internal,
        }

    # --- crystallisation margin at the coldest strong point (-> absorber temp) ---
    t_strong_cold = t_abs
    x_crys = x_crystallisation(t_strong_cold)
    cryst_margin = x_crys - x_strong   # positive = safe; negative = crystallising

    return {
        "effect": effect, "effect_label": oem["label"],
        "t_evap_c": t_evap, "t_cond_c": t_cond, "t_abs_c": t_abs, "t_gen_c": t_gen,
        "p_low_kpa": p_low, "p_high_kpa": p_high,
        "x_nominal_pct": x_nominal,
        "x_weak_pct": x_weak, "x_strong_pct": x_strong,
        "circulation_ratio": f,
        "m_refrig_kgps": m_refrig, "m_weak_kgps": m_weak, "m_strong_kgps": m_strong,
        "q_evap_kw": q_evap, "q_cond_kw": q_cond, "q_gen_kw": q_gen, "q_abs_kw": q_abs,
        "q_evap_req_kw": q_evap_req,
        "cop": cop, "cop_rated": oem["cop_rated"],
        "drive_low": (effect == "double" and dp.t_hot_c < _DOUBLE_MIN_DRIVE_C),
        "double_min_drive_c": _DOUBLE_MIN_DRIVE_C,
        "stage": stage,
        "burner_on": dp.burner_on,
        "source_capped": avail != float("inf"),
        "q_source_avail_kw": avail,
        "burner_heat_kw": burner_heat,
        "fuel_nm3h": fuel_nm3h,
        "cooling_deficit_kw": cooling_deficit,
        "t_strong_cold_c": t_strong_cold,
        "x_crystallisation_pct": x_crys, "cryst_margin_pct": cryst_margin,
    }


def report(dp: DesignPoint):
    r = solve(dp)
    print(f"LiBr-H2O absorption chiller - {r['effect_label']} - calibrated balance")
    print("=" * 60)
    print("DESIGN POINT (input)")
    print(f"  cycle effect         : {r['effect_label']}")
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
    print(f"  nominal (OEM)   {r['x_nominal_pct']:5.1f} % LiBr")
    print(f"  weak (dilute)   {r['x_weak_pct']:5.1f} % LiBr")
    print(f"  strong (conc.)  {r['x_strong_pct']:5.1f} % LiBr")
    print(f"  swing           {r['x_strong_pct']-r['x_weak_pct']:5.1f} %")
    print(f"  circulation ratio f = {r['circulation_ratio']:5.2f}")
    print("-" * 60)
    print("MASS FLOWS")
    print(f"  refrigerant {r['m_refrig_kgps']:6.3f} kg/s")
    print(f"  weak sol.   {r['m_weak_kgps']:6.3f} kg/s   strong sol. {r['m_strong_kgps']:6.3f} kg/s")
    print("-" * 60)
    print("DUTIES")
    print(f"  evaporator  {r['q_evap_kw']:7.1f} kW")
    print(f"  condenser   {r['q_cond_kw']:7.1f} kW")
    print(f"  generator   {r['q_gen_kw']:7.1f} kW")
    print(f"  absorber    {r['q_abs_kw']:7.1f} kW")
    bal = r['q_evap_kw'] + r['q_gen_kw'] - r['q_cond_kw'] - r['q_abs_kw']
    print(f"  energy check (Qe+Qg-Qc-Qa) = {bal:7.2f} kW  (should be ~0)")
    print(f"  COP = {r['cop']:.3f}   (OEM rated {r['cop_rated']:.2f})")
    print("-" * 60)
    print("CRYSTALLISATION")
    print(f"  cold strong point {r['t_strong_cold_c']:5.1f} degC")
    print(f"  crystallisation line {r['x_crystallisation_pct']:5.1f} % ; "
          f"margin {r['cryst_margin_pct']:+5.1f} % "
          f"({'SAFE' if r['cryst_margin_pct'] > 0 else 'AT RISK'})")
    return r


if __name__ == "__main__":
    print(">>> BROAD XII rated single-effect (hot water 98 degC)")
    report(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=98.0,
                       q_evap_kw=233.0, effect="single"))
    print()
    print(">>> BROAD XII rated double-effect (drive 150 degC)")
    report(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=150.0,
                       q_evap_kw=233.0, effect="double"))
