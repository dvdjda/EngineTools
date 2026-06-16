"""
nexablock.blocks.libr_chiller_de — Double-effect LiBr-H2O absorption chiller.

A double-effect machine stages TWO generators: high-grade steam drives the
high-temperature generator (HTG); the high-pressure refrigerant vapour boiled
off there condenses in the low-temperature generator (LTG) and its latent heat
boils a *second* batch of refrigerant out of solution. The driving heat does
work twice, so COP ≈ 1.1-1.4 (vs ~0.7 single-effect) — but the HTG needs a
higher steam grade (≈ medium-pressure steam, ~8-10 bar / ~170-180°C).

This block reuses the single-effect envelope physics (same ports, same
result labels, same first-law balance Q_cond = Q_gen + Q_cool) so the rest of
the GT-system composition, feasibility, audit, reporting and plant_loads all
work unchanged — the only differences are the higher COP, a steam-grade
adequacy check, and a few descriptive double-effect result rows.

Reference: Herold, Radermacher, Klein — Absorption Chillers and Heat Pumps, 2016
(double-effect cycle, §double-effect performance).
"""
from __future__ import annotations
from ..core.quantity import Param
from .libr_chiller   import LiBrChiller

# Baseline single-effect COP used only to express the "second-effect gain" as
# an informative result row (how much extra cooling the second effect buys).
_SINGLE_EFFECT_COP = 0.70


class DoubleEffectLiBrChiller(LiBrChiller):
    category = "Cooling"
    label    = "2x LiBr (double-effect)"

    def __init__(self,
                 cop:             float = 1.20,   # double-effect range 1.1-1.4
                 chw_sup_C:       float = 30.0,
                 chw_dt_K:        float = 12.0,
                 chw_cp:          float = 4187.0,
                 pump_frac:       float = 0.015,
                 reject_t_C:      float = 95.0,
                 reject_return_C: float = 80.0,
                 min_htg_steam_C: float = 155.0) -> None:   # min steam temp for the HTG
        super().__init__(cop=cop, chw_sup_C=chw_sup_C, chw_dt_K=chw_dt_K,
                         chw_cp=chw_cp, pump_frac=pump_frac,
                         reject_t_C=reject_t_C, reject_return_C=reject_return_C)
        self._min_htg = min_htg_steam_C + 273.15

    def _build_params(self) -> dict[str, Param]:
        p = super()._build_params()
        # Double-effect COP runs higher than single-effect — widen the bound.
        p["cop"] = Param(self._cop, "-", min=0.9, max=1.6,
                         desc="Double-effect LiBr COP (Q_cool / Q_gen)")
        p["min_htg"] = Param(self._min_htg, "K",
                             desc="Minimum HTG steam temperature for double-effect")
        return p

    def compute(self) -> None:
        # Single-effect envelope physics handle everything (Q_gen, Q_cool=COP·Q_gen,
        # Q_cond=Q_gen+Q_cool, CHW flow, rejection loop) — for any COP. We just
        # layer the double-effect descriptive rows + the steam-grade margin on top.
        super().compute()
        if "Generator duty" not in self.results:
            return   # zero-steam branch: parent set no result rows

        q_gen = self.results["Generator duty"].value          # kW (HTG driving duty)
        cop   = self._p("cop")
        s     = self._in("steam_in")
        t_steam_C = (s.T - 273.15) if (s is not None and s.T) else 0.0
        min_htg_C = self._p("min_htg") - 273.15

        # The second effect is the extra cooling beyond a single-effect machine
        # working off the same generator duty.
        second_effect_gain = max(0.0, (cop - _SINGLE_EFFECT_COP) * q_gen)

        self._result("Number of effects",       2.0,            "-",  "input",
                     "double-effect: HTG + LTG, driving heat used twice")
        self._result("HTG driving steam temp",  t_steam_C,      "°C", "verified",
                     "high-temp generator inlet steam")
        self._result("Min steam temp (HTG)",    min_htg_C,      "°C", "input")
        self._result("Steam-grade margin",      t_steam_C - min_htg_C, "°C", "verified",
                     "steam temp − HTG minimum (negative ⇒ heat too low-grade)")
        self._result("Second-effect cooling gain", second_effect_gain, "kW", "verified",
                     "extra cooling vs single-effect (COP 0.70) at the same Q_gen")

    def audit_checks(self) -> list:
        from ..audit import bounds_check, pass_fail
        # Reuse the parent's checks but swap the COP bound (double-effect range)
        # and add a steam-grade adequacy check.
        checks = [c for c in super().audit_checks() if not c.name.startswith("P4")]
        cop = self._p("cop")
        s   = self._in("steam_in")
        t_steam_C = (s.T - 273.15) if (s is not None and s.T) else 0.0
        min_htg_C = self._p("min_htg") - 273.15
        checks.append(bounds_check(
            "P4: double-effect LiBr COP in (0.9, 1.6)",
            value=cop, lo=0.9, hi=1.6, unit="-",
            affects=["LiBr cooling capacity"]))
        checks.append(pass_fail(
            "T11: HTG steam grade adequate for double-effect",
            passed=t_steam_C >= min_htg_C,
            detail=f"steam {t_steam_C:.0f}°C ≥ HTG min {min_htg_C:.0f}°C "
                   f"(margin {t_steam_C - min_htg_C:+.0f}°C)",
            category="Second law", affects=["LiBr cooling capacity"]))
        return checks
