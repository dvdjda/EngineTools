# EngineTools — GT System v2 (GT + HRSG + 2×LiBr + GPU + MED + Backup)
### Reference note for a Private AI

This note describes one EngineTools simulator end to end: every **input**, every
**output**, and every **control** (mode switch). It is self-contained — a Private
AI can answer questions about the tool from this note alone, without the source.

- **Tool key:** `gt_system_v2_de_backup`
- **Display name:** GT System v2 — nexablock (GT + HRSG + 2×LiBr + GPU + MED + Backup)
- **Kind:** simulator · **Status:** trusted (promoted by David)
- **What it models:** a Nexa Block prime-power island/grid plant —
  Gas Turbine → HRSG (steam) → **double-effect** LiBr absorption chiller (×2 generators,
  COP ≈ 1.2) → immersed-GPU cassette cooling → MED desalination, **plus a Tier-3
  backup architecture**: a diesel standby genset, a wet cooling tower (replacing the
  dry radiator), diesel-fuel + fresh-water storage, a UPS battery, and a thermal
  accumulator. Two failure switches simulate a GT trip and a LiBr trip.
- **Heritage:** subclass chain `GTSystemV2` → `GTSystemV2DE` (double-effect) →
  `GTSystemV2DEBackup` (this tool). It inherits all base inputs/outputs and adds the
  double-effect chiller and the backup hardware.
- **Resilience KPIs basis:** screening (design-sizing estimates). Core energy/mass
  KPIs are verified (validated vs the v1 trusted GT tool within ±2%, 14/14 checks).

---

## 1. Inputs

`(key, label, unit, default, min, max)`. The chiller-COP default/range is the
double-effect band. The dry-radiator inputs (`radiator_approach_K`, `fan_rated_frac`)
are **removed** here because the wet cooling tower supersedes the dry radiator.

### Prime mover (GT)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `p_rated_kW` | GT rated power | kW | 10000 | 100 | 500000 |
| `load_pct` | GT load | % | 85 | 10 | 100 |
| `gt_eff` | GT efficiency | – | 0.35 | 0.15 | 0.45 |
| `t_ambient_C` | Ambient temperature | °C | 25 | −20 | 55 |
| `t_exhaust_C` | Exhaust temperature | °C | 530 | 300 | 700 |

### HRSG / steam
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `hrsg_eff_pct` | HRSG effectiveness | % | 85 | 50 | 95 |
| `steam_p_bar` | Steam pressure | bar | 10 | 1 | 40 |
| `fw_t_C` | HRSG feedwater / loop return set-point | °C | 80 | 20 | 150 |

### LiBr chiller (double-effect)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `libr_cop` | LiBr COP (double-effect) | – | 1.20 | 0.90 | 1.60 |
| `libr_reject_t_C` | LiBr rejection temperature | °C | 95 | 60 | 130 |

### GPU cassette (immersion)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `gpu_t_in_C` | GPU coolant T_in (dielectric) | °C | 30 | 5 | 45 |
| `gpu_t_out_C` | GPU coolant T_out (dielectric) | °C | 42 | 10 | 60 |
| `coolant_cp` | Dielectric coolant cp | J/(kg·K) | 2100 | 1000 | 4500 |
| `coolant_rho` | Dielectric coolant density | kg/m³ | 780 | 600 | 1800 |
| `gpu_it_kW` | GPU IT load | kW | 5000 | 100 | 200000 |
| `cassette_pue` | Cassette PUE | – | 1.05 | 1.0 | 2.0 |

### MED desalination
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `med_effects` | MED effects | – | 8 | 1 | 16 |
| `sw_t_C` | Seawater temp | °C | 28 | 0 | 45 |
| `med_bypass_frac` | MED bypass (manual, 0–1) | – | 0.0 | 0.0 | 1.0 |
| `med_cold_pinch_K` | MED cold-end approach above seawater (auto) | K | 15 | 5 | 40 |

### Plant-electrical / parasitics (IT- & flow-driven)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `gt_aux_frac` | GT aux fraction (of derated cap) | – | 0.010 | 0.0 | 0.05 |
| `pump_eta` | Pump efficiency (all pumps) | – | 0.70 | 0.30 | 0.90 |
| `dp_diel_bar` | Dielectric coolant loop head | bar | 1.5 | 0.5 | 8.0 |
| `dp_loop_bar` | Cooling-water loop head | bar | 3.0 | 0.5 | 8.0 |
| `dp_bfp_bar` | HRSG feed-water pump head | bar | 9.0 | 1.0 | 30.0 |
| `dp_sw_bar` | Seawater / MED pump head (drives all low-head desal + condensate pumps) | bar | 2.0 | 0.5 | 8.0 |

### Container envelope (HVAC + lights)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `containers_per_MW` | 40' containers per MW IT | – | 3.0 | 1.0 | 10.0 |
| `container_area_m2` | Container external area | m² | 70 | 30 | 150 |
| `container_U` | Envelope U-value | W/(m²·K) | 0.5 | 0.1 | 2.0 |
| `container_inside_C` | Container inside set-point | °C | 27 | 15 | 35 |
| `lights_frac` | Lights (fraction of HVAC) | – | 0.25 | 0.0 | 1.0 |
| `external_load_kW` | External load — island mode only | kW | 0 | 0 | 1000000 |

### Backup hardware (added by this variant)
| key | label | unit | default | min | max |
|---|---|---|---|---|---|
| `diesel_rated_kW` | Diesel genset rating | kW | 1500 | 200 | 50000 |
| `diesel_eff` | Diesel efficiency | – | 0.40 | 0.30 | 0.48 |
| `diesel_exhaust_C` | Diesel exhaust temp | °C | 480 | 350 | 600 |
| `tower_wetbulb_C` | Cooling-tower wet-bulb | °C | 25 | 5 | 35 |
| `tower_approach_K` | Cooling-tower approach | K | 5 | 2 | 12 |
| `diesel_tank_m3` | Diesel fuel storage | m³ | 25 | 1 | 500 |
| `water_tank_m3` | Backup water storage | m³ | 250 | 10 | 5000 |
| `backup_hours_target` | Backup autonomy target | h | 72 | 1 | 720 |
| `ups_kwh` | UPS battery (usable) | kWh | 150 | 10 | 5000 |
| `accumulator_m3` | Cooling accumulator | m³ | 15 | 0 | 500 |

---

## 2. Controls (mode selectors)

These are integer-coded two/multi-state selectors. The paired manual input is read
but **ignored** when the matching mode is on "auto".

| key | label | options (value) | effect |
|---|---|---|---|
| `operating_mode` | Operating mode | Island (0) · Grid-tied (1) | Island ⇒ GT follows `external_load_kW`; Grid-tied ⇒ surplus is exported. |
| `gt_power_mode` | GT power control | Auto — follow NEXA demand (0) · Manual — use `load_pct` (1) | Auto derives `load_pct` from demand; Manual uses the `load_pct` input. |
| `steam_split_mode` | Steam split | Off — all steam → LiBr (0) · Auto — LiBr-priority, surplus → calorifier → MED (1) | Routes surplus HRSG steam to MED via a calorifier. |
| `med_bypass_mode` | MED bypass control | Manual — use `med_bypass_frac` (0) · Auto — hold HRSG return set-point (1) | Auto cascades MED bypass to hold the HRSG return at `fw_t_C`. |
| `gt_status` | GT status | Normal (0) · Failed → diesel (1) | On failure the diesel genset becomes prime mover; its exhaust drives the LiBr; the tower covers the cooling balance. |
| `libr_status` | LiBr status | Normal (0) · Failed → cooling tower (1) | On failure the wet cooling tower carries the full GPU cooling, scaled to wet-bulb. |

---

## 3. Outputs

Basis tags: **verified** (validated physics) · **screening** (design estimate) ·
**input** (echo of an input).

### Core energy / mass KPIs (verified)
| label | unit | basis |
|---|---|---|
| GT actual power | kW | verified |
| NG consumption | Nm³/h | verified |
| Steam generation | t/h | verified |
| LiBr cooling capacity | kW | verified |
| GPU IT load | kW | verified |
| MED water production | m³/day | verified |
| Plant PUE (electrical, export excluded) | – | screening |

### Mode-dependent rows (shown only when relevant)
| label | unit | when |
|---|---|---|
| GT load_pct (auto-derived) | % | `gt_power_mode` = Auto |
| libr_frac (auto-derived) | – | auto LiBr split active |
| Grid export | kW | `operating_mode` = Grid-tied |
| External load (island) | kW | `operating_mode` = Island |

### Double-effect chiller rows
| label | unit | basis |
|---|---|---|
| LiBr COP (double-effect) | – | input |
| Second-effect cooling gain | kW | verified |

### Plant-aux electrical breakdown (one row per driver)
- `↳ <pump/fan name>` … kW (screening) — every pump and the cooling-tower fan, itemised.
- `↳ Plant aux TOTAL` … kW (screening).

### Resilience / backup KPIs (screening)
| label | unit | meaning |
|---|---|---|
| Cooling-tower top-up duty | kW | tower duty beyond normal reject |
| Tower supply temp (direct cool ✓/✗) | °C | tower supply temperature; ✓ if direct cooling is feasible |
| Tower make-up water | m³/h | evaporative make-up demand |
| Diesel fuel autonomy (target N h ✓/✗) | h | run-hours on stored fuel; ✓ if ≥ `backup_hours_target` |
| Fresh-water buffer | days | days of stored water |
| UPS ride-through (covers diesel start ✓/✗) | min | battery bridge; ✓ if ≥ diesel start time |
| Thermal accumulator bridge (covers ramp ✓/✗) | min | cooling bridge; ✓ if ≥ diesel-start / tower-ramp time |

**Headline cards:** GT actual power · Steam generation · GPU IT load · MED water production.

### Chart
On-screen and report chart is an **SVG process-flow diagram (PFD)** of the plant
topology — same topology in the UI and the report.

---

## 4. Studies the tool exposes
- **Sensitivity / sweep inputs:** `load_pct`, `gt_eff`, `libr_cop`, `libr_reject_t_C`,
  `hrsg_eff_pct`, `med_effects`, `med_bypass_frac`, `t_ambient_C`, `gpu_it_kW`, `external_load_kW`.
- **Built-in scenarios:** *summer peak* (`t_ambient_C`=40, `load_pct`=100);
  *winter low load* (`t_ambient_C`=5, `load_pct`=40).

---

## 5. The four GT System v2 variants (so the Private AI doesn't confuse them)
| key | LiBr | backup | status |
|---|---|---|---|
| `gt_system_v2` | single-effect (COP ~0.7) | none | **draft** |
| `gt_system_v2_de` | double-effect (COP ~1.2) | none | **draft** |
| **`gt_system_v2_de_backup`** | double-effect | **diesel + tower + UPS + accumulator** | **trusted** *(this note)* |
| `gt_system_v2_loadsweep` | load-sweep study harness | — | **draft** |

> **Status note:** as of the latest demotion, the **… + Backup** engine is the only `trusted` GT engine; the other three GT variants and the standalone GPU cassette are `draft` pending re-verification. There is also a separate standalone **LiBr-H₂O absorption chiller** tool (single/double-effect, BROAD XII-calibrated, optional make-up burner) — `draft` — not to be confused with the LiBr block embedded in these GT systems.
