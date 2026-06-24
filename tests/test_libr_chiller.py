"""OEM-compliance checks for the LiBr-H2O absorption chiller (single + double effect).

Reference: BROAD XII Non-Electric Chiller datasheet (1711), rated condition
chilled water 7/14 degC, cooling water 30/37 degC.
  single-effect : COP 0.76 (hot-water 98/88 drive), solution conc. ~43 %
  double-effect : COP 1.42 (direct-fired ~150 degC drive), solution conc. ~54 %
"""
from nexa_toolkit.engine.libr_chiller import DesignPoint, solve


def _rated(effect, t_hot):
    return solve(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0,
                             t_hot_c=t_hot, q_evap_kw=233.0, effect=effect))


def test_single_effect_rated_matches_oem():
    r = _rated("single", 98.0)
    assert abs(r["cop"] - 0.76) < 0.01          # OEM nameplate COP
    assert abs(r["x_nominal_pct"] - 43.0) < 0.01  # OEM nominal concentration


def test_double_effect_rated_matches_oem():
    r = _rated("double", 150.0)
    assert abs(r["cop"] - 1.42) < 0.01
    assert abs(r["x_nominal_pct"] - 54.0) < 0.01


def test_energy_balance_closes():
    for effect, t_hot in (("single", 98.0), ("double", 150.0)):
        r = _rated(effect, t_hot)
        bal = r["q_evap_kw"] + r["q_gen_kw"] - r["q_cond_kw"] - r["q_abs_kw"]
        assert abs(bal) < 1e-6                   # closes by construction


def test_no_false_crystallisation_at_rated():
    for effect, t_hot in (("single", 98.0), ("double", 150.0)):
        r = _rated(effect, t_hot)
        assert r["cryst_margin_pct"] > 0         # rated OEM point must be safe


def test_no_crash_at_high_drive_temperature():
    # The old solver raised brentq sign errors above ~110 degC; calibrated cycle
    # must run the full double-effect drive range.
    for t_hot in (110.0, 140.0, 180.0):
        r = _rated("double", t_hot)
        assert r["cop"] > 0


def test_double_effect_cop_exceeds_single():
    s = _rated("single", 98.0)
    d = _rated("double", 150.0)
    assert d["cop"] > s["cop"]


def test_burner_fuel_matches_oem_dfa_gas_table():
    # OEM DFA direct-fired BZ20: 233 kW cooling -> 16.2 Nm3/h gas.
    # Capped source at ~0 with the burner on => burner supplies the full generator
    # heat; NG = Q_gen/10 must reproduce the nameplate gas figure.
    r = solve(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=150.0,
                          q_evap_kw=233.0, effect="double",
                          burner_on=True, q_source_avail_kw=0.01))
    assert abs(r["fuel_nm3h"] - 16.2) < 0.5      # ~16.4 Nm3/h vs OEM 16.2


def test_make_up_burner_covers_shortfall():
    # Source capped below demand, burner on -> full duty met, burner makes up the gap.
    r = solve(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=150.0,
                          q_evap_kw=233.0, effect="double",
                          burner_on=True, q_source_avail_kw=100.0))
    assert abs(r["q_evap_kw"] - 233.0) < 1e-6    # full cooling delivered
    assert abs(r["burner_heat_kw"] - (r["q_gen_kw"] - 100.0)) < 1e-6
    assert r["cooling_deficit_kw"] == 0.0


def test_no_burner_reports_cooling_deficit():
    # Source capped below demand, burner off -> cooling is limited, deficit reported.
    r = solve(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=150.0,
                          q_evap_kw=233.0, effect="double",
                          burner_on=False, q_source_avail_kw=100.0))
    assert r["q_evap_kw"] < 233.0
    assert r["cooling_deficit_kw"] > 0.0
    assert r["fuel_nm3h"] == 0.0


def test_uncapped_source_is_legacy_behaviour():
    # Default (uncapped) -> full duty, no burner, no deficit.
    r = solve(DesignPoint(t_chw_out_c=7.0, t_cw_in_c=30.0, t_hot_c=98.0,
                          q_evap_kw=233.0, effect="single"))
    assert abs(r["q_evap_kw"] - 233.0) < 1e-6
    assert r["fuel_nm3h"] == 0.0 and r["cooling_deficit_kw"] == 0.0
