# NEXA Simulator — How It Works

The single most-referenced document in the project. Open this when you want to know what a number means, where it came from, and what the framework is asserting about it.

---

## 1. The big picture in one paragraph

The **GPU is the primary load**. It demands electrical power and dumps every watt of that electrical input as heat into the coolant (immersion cooling — first law). The **Gas Turbine (GT)** follows the GPU + plant aux load: in island mode it's pinned by what the bus can absorb, in grid-tied it can ramp higher and inject the surplus to the grid (export-only — imports are forbidden). The GT's exhaust feeds a **Heat Recovery Steam Generator (HRSG)**, which makes steam at a pressure you set. The steam is split between a **LiBr absorption chiller** (which makes the chilled water that cools the GPU) and a **Multi-Effect Distillation (MED)** unit (which makes fresh water). The split is **LiBr-priority**: the chiller takes exactly the steam it needs to absorb the GPU heat dump, and MED gets whatever is left over — it's a steam balancer, not a designed primary product. A **Cooling Tower (CT)** rejects the LiBr condenser heat to the wet bulb of the site.

Every solve runs three independent status layers:
- **Convergence** — did the solver loops settle?
- **Feasibility** — does supply ≥ demand for power and cooling? (with a 2.5 % screening tolerance on cooling for controller-vs-block precision noise)
- **Audit** — do all 44 first-principles checks pass? (mass closures, energy closures, second-law temperature feasibility, plausibility bounds)

The per-KPI "verified / unverified / screening" basis is **data-driven from audit coverage** — a KPI gets `verified` only if at least one audit check that names it actually passed. No hardcoded strings.

---

## 2. System flowsheet

```
                  ┌─────────────────────────────┐
                  │  Natural Gas  (LHV input)   │
                  └──────────────┬──────────────┘
                                 │
                                 ▼
                    ┌──────────────────────┐
                    │     GAS TURBINE      │──► GT electrical power → bus
                    │   (derated by site   │──► GT aux electrical  (1.0% of derated)
                    │      ambient)        │──► exhaust gas (hot)
                    └─────────────┬────────┘    GT cooling water (small heat)
                                  │ exhaust
                                  ▼
                    ┌──────────────────────┐
                    │        HRSG          │──► stack flue gas (cooled exhaust)
                    │  exhaust → steam     │
                    └─────────────┬────────┘
                       feedwater  │ steam (P_steam, t_sat+30°C)
                       (seeded)   │
                                  ▼
                       ┌──────────────────────┐
                       │   STEAM SPLITTER     │
                       │   libr_frac : 1−frac │
                       └───┬──────────────┬───┘
                           │              │
              steam_to_libr│              │steam_to_med
                           ▼              ▼
                ┌─────────────────┐  ┌─────────────────┐
                │  LiBr CHILLER   │  │       MED       │──► fresh water (residual product)
                │  Q_cool = COP   │  │  GOR ≈ 0.8·n    │──► brine reject
                │   × Q_gen       │  │  T_brine ≈ 60°C │──► MED electrical (pumps)
                │  Pump elect.    │  │       └─────────┴──► condensate return (~65°C)
                │  (1.5% Q_cool)  │  └─────────────────┘
                └──────┬──────────┘
                       │ CHW supply       │ LiBr condensate return (100°C, sat liq)
                       │ (low T)          │
                       ▼                  ▼ (informational, not connected)
                ┌─────────────────┐
                │  GPU CASSETTE   │──► coolant out (warm)
                │ silicon + over- │     ▲
                │  head → heat    │     │
                │  load (q_W)     │     │ heat to cool
                └──────┬──────────┘     │
                       │ heat (= Q_cool)│
                       └────────────────┘

         ┌─────────────────┐
         │  COOLING TOWER  │◄──── LiBr condenser duty (Q_gen + Q_cool)
         │  T_supply =     │      
         │  T_wb + approach│      
         │  CT fan elec    │      
         │  (1.5% Q_cond)  │      
         └─────────────────┘      

                   ─── Electrical bus ───
                   │
                   ▼
   GT power supplied  →  ─►  GPU silicon         (silicon × PUE)
                              GPU cassette overhead  (silicon × aux_frac)
                              MED electrical
                              LiBr pump electrical
                              CT fan electrical
                              GT auxiliaries
                              Plant BoP (lights/HVAC)
                              External load        (island only — manual scalar)
                              Grid export          (grid only — computed residual)
```

---

## 3. The seven blocks

Every block declares its **ports** (inlet / outlet streams), **params** (numeric inputs), the **physics** of its `compute()` method, and its **audit checks**.

### 3.1 GasTurbine — `nexablock/blocks/gas_turbine.py`

**Ports**:
- Outlet `exhaust` (generic fluid: hot exhaust to HRSG)
- Outlet `power` (electrical: GT actual power to bus)
- Outlet `gt_cw` (energy: small GT cooling-water duty)

**Params**: `p_rated_kW` (ISO rating), `load_pct`, `gt_eff` (LHV basis), `t_ambient_C`, `t_exhaust_C`, `aux_frac` (default 1.0 % of derated capacity for GT auxiliaries).

**Physics**:
```
derate factor = max(0.50, 1 − 0.007 × max(0, T_amb − 15°C))     # 0.7%/°C above ISO 15°C
GT derated capacity = p_rated_kW × derate
GT actual power = GT derated capacity × load_pct / 100
Fuel energy input = GT actual power / gt_eff
NG consumption = Fuel / LHV   (LHV = 50,050 kJ/kg)
Waste heat = Fuel − power
Exhaust heat = waste × 0.85   (CCGT GT, 15% lost to GT cooling water)
GT cooling water = waste × 0.15
Exhaust mdot = exhaust_heat / (cp_exh × (T_exh − T_amb))
GT aux electrical = aux_frac × GT derated capacity
```

**Audit checks**: E1 (NG·LHV·η=power), E2 (fuel = power + exhaust + GT_cw), M6 (NG closure), T8 (exhaust > ambient + 100°C), P1 (η in (0, 0.55)), P2 (derate in (0, 1]), P3 (load_pct in [10, 100]), **P11 (actual ≤ derated** — added when derated-as-supply concept landed).

### 3.2 HRSG — `nexablock/blocks/hrsg.py`

**Ports**: Inlet `exhaust_in` + `feedwater`; Outlet `stack` + `steam`.

**Params**: `hrsg_eff_pct` (effectiveness), `steam_p_bar` (drum pressure), `fw_t_C`.

**Physics**:
```
Q_exhaust = ṁ_exh × cp_exh × (T_exh − 298.15)        # 298.15 K = HRSG fixed reference
HRSG duty = Q_exhaust × η_hrsg
Stack loss = Q_exhaust × (1 − η_hrsg)
T_sat = IAPWS-IF97 saturation at P_steam
T_steam = T_sat + 30°C    (fixed superheat for CCGT screening)
h_steam = h(P_steam, T_steam)        # superheated enthalpy
h_fw = h(P_steam, T_fw)              # compressed liquid enthalpy
ṁ_steam = HRSG duty / (h_steam − h_fw)
ṁ_steam capped at 0.999 × ṁ_feedwater_supply   (can't exceed FW available)
```

**Audit checks**: E3 (exhaust·η=duty), E4 (duty = ṁ·Δh), **M1 (feedwater supply ≥ steam consumed — sufficiency form)**, T1 (hot pinch > 0), T2 (cold pinch > 0), T3 (T_steam ≥ T_sat), P8 (HRSG eff in [50, 95]%), P9 (subcritical P_steam).

### 3.3 SteamSplitter — `nexablock/blocks/steam_splitter.py`

**Ports**: Inlet `steam_in`; Outlets `to_libr` + `to_med`.

**Params**: `libr_frac` (resolved by the controller in auto mode; user input in manual).

**Physics**: pure mass split — `ṁ_to_libr = ṁ_in × libr_frac`; `ṁ_to_med = ṁ_in × (1 − libr_frac)`. h, T, P identical on both outlets (isenthalpic).

**Audit checks**: M2 (inlet = sum of outlets), P10 (libr_frac in [0, 1] AND libr_frac + med_frac = 1).

### 3.4 LiBrChiller — `nexablock/blocks/libr_chiller.py`

Single-effect LiBr-H₂O absorption chiller.

**Ports**: Inlet `steam_in` + optional `chw_return`; Outlet `condensate` + `chw_supply` + `ct_water_out` (energy to CT).

**Params**: `cop` (typical 0.65–0.75 single-effect), `chw_sup_C`, `chw_dt_K`, `chw_cp`, `pump_frac` (default 1.5 % of cooling for pump electrical).

**Physics**:
```
h_cond_100 = h_sat_liq at 1 atm  (≈ 419 kJ/kg)  ← was a bug-fix: previously used
                                                  h_water(P,T) which returns
                                                  vapour at the saturation
                                                  boundary; see commit 03fd968.
Q_gen  = ṁ_steam × (h_steam − h_cond_100)
Q_cool = Q_gen × COP
Q_cond = Q_gen + Q_cool                          # 1st law on chiller envelope
ṁ_chw  = Q_cool / (cp_chw × ΔT_chw)              # CHW flow sizing
LiBr pump electrical = pump_frac × Q_cool
```

**Audit checks**: E5 (Q_gen·COP=Q_cool), E6 (Q_cond = Q_gen + Q_cool), M3 (steam_in = condensate_out), T6 (T_chw_supply ≥ 5°C), T7 (T_chw_return > T_chw_supply), T9 (T_steam > T_condensate), P4 (COP in (0.5, 1.3)).

### 3.5 MED — `nexablock/blocks/med.py`

Multi-Effect Distillation thermal desalination.

**Ports**: Inlet `steam_in` + optional `seawater`; Outlet `condensate` + `fresh` + `brine`.

**Params**: `n_effects` (4–14 typical), `sw_t_C`, `recovery` (default 35 %).

**Physics (screening)**:
```
GOR = 0.8 × n_effects                            # thin-film falling-film rule
ṁ_dist = ṁ_steam × GOR
ṁ_sw   = ṁ_dist / recovery
ṁ_brine = ṁ_sw − ṁ_dist
m³/day = ṁ_dist × 86400 / 1000
MED electrical = 1.5 kWh/m³ × (m³/h)             # pumps + controls
Q_med = ṁ_steam × (h_steam − h_cond_65C)         # thermal input
```

When `libr_frac = 1.0` (auto mode, LiBr eats all steam), MED gets zero — the block now correctly populates zero-valued result rows so downstream audit doesn't crash.

**Audit checks**: E8 (Q_steam ≈ ṁ_dist · h_fg / GOR, 15 % screening tolerance), M4 (sw = dist + brine), M5 (GOR in (4, 10) band), T4 (ΔT/effect ≥ 3°C), T10 (T_brine > T_seawater), P5 (GOR plausibility), P6 (recovery in (0, 0.5)).

### 3.6 GPUCassette — `nexablock/blocks/gpu_cassette.py`

Single-phase immersion-cooled compute unit.

**Ports**: Inlet `coolant_in`; Outlet `coolant_out` + `heat` (energy).

**Params**: `n_gpu`, `p_gpu_kW`, `aux_frac` (cassette overhead — pumps/controls/switchgear inside the enclosure), `coolant_cp`, `coolant_rho`, `dt_K` (coolant ΔT).

**Physics**:
```
IT power = n_gpu × p_gpu_kW
Cassette overhead electrical = IT × aux_frac     ← split out from the old hidden
                                                   "IT × PUE" formula so reports
                                                   honestly show the overhead
                                                   line both in power demand
                                                   AND in cooling demand.
Heat load = IT + cassette overhead               # all electrical → heat by 1st law
PUE       = 1 + aux_frac
ṁ_coolant = Heat / (cp × ΔT)
```

**Audit checks**: **E7 (Heat = IT + Cassette_overhead)** — the cassette energy-closure check, explicit form. **M7 (coolant inlet supply ≥ cassette flow demand)** — sufficiency check with 2.5 % screening tolerance. P7 (PUE ≥ 1.0).

### 3.7 CoolingTower — `nexablock/blocks/cooling_tower.py`

Evaporative cooling tower (screening).

**Ports**: Inlet `heat_in` (energy = LiBr condenser duty) + optional `ct_return`; Outlet `ct_supply`.

**Params**: `t_wb_C` (site wet-bulb), `approach_K` (default 5°C), `dt_ct_K` (default 7°C), `fan_frac` (default 1.5 % of rejected heat for induced-draft fans).

**Physics**:
```
ṁ_ct = Q_cond / (cp_w × ΔT_ct)
T_supply = T_wb + approach
T_return = T_supply + ΔT_ct
CT fan electrical = fan_frac × Q_cond
```

**Audit checks**: M8 (ct supply = ct return — placeholder for future evaporation modelling), T5 (T_supply > T_wet_bulb).

---

## 4. Control modes — three switches, one external-load knob

The v2 GT engine has four operating-mode inputs. Defaults are island / auto / auto / 0 kW — the "real-plant" semantics.

### 4.1 Operating mode — Island / Grid-tied

| | Island | Grid-tied |
|---|---|---|
| External load input | manual scalar (user-entered) | hidden (grid absorbs) |
| Grid import allowed | n/a | NO (forbidden per spec) |
| GT cap on excess electrical | yes — can't go past elec demand | no — surplus exports |
| Cooling deficit at high GPU | possible (real engineering finding) | only if GT ≥ 100 % derated and still short |

### 4.2 GT power control — Auto / Manual

- **Auto**: controller picks `load_pct` from demand. Island: `min(elec_required, 100)`. Grid: `min(max(elec_required, steam_required), 100)`.
- **Manual**: user's `load_pct` input is used directly. The controller-derived line in the results table disappears.

The UI also offers a **GT load (kW)** field twinned to `load_pct` (kW = derated capacity × load% ÷ 100, the actual-power basis). It's a convenience mirror, not a separate input: in Manual it equals `GT actual power`; in Auto it's inert like `load_pct`. See [`MANUAL.md`](MANUAL.md) §3.1.

### 4.3 Steam split control — Auto (LiBr-priority) / Manual

- **Auto**: `libr_frac = min(steam_to_libr_needed / total_steam_at_load, 1.0)`. LiBr claims exactly what it needs to cover GPU heat. MED takes the residual.
- **Manual**: user's `libr_frac` is used. Fixed split, MED behaves like a designed product.

### 4.4 The controller — `simulators/gt_system/control.py`

When either auto mode is on, `control_setpoints(p)` runs a 2–4 iteration fixed-point before block instantiation:

1. Compute `GPU_heat = gpu_it_kW × PUE` (invariant — doesn't depend on solve state).
2. Compute `steam_to_libr_required = GPU_heat / (libr_cop × Δh_steam_to_cond)`.
3. Pre-compute steam at 100 % load (closed-form, no aux dependence).
4. Iterate: guess load_pct → derive aux loads → derive elec_demand → recompute `required_load_for_elec` → resolve `load_pct` per mode → recompute `libr_frac` → repeat to convergence.
5. Return `ControlSetpoints` with `load_pct`, `libr_frac`, `external_load_kW` (= user input in island, 0 in grid), `grid_export_kW` (= max(0, GT − NEXA) in grid, 0 in island), and `derived_*` booleans for the renderer.

**No hidden safety margin** — the controller targets exactly what's needed. Small mismatches between the analytical model and the block compute (Δh approximations, fixed-reference t_amb in HRSG, prop-table rounding) are absorbed by the **screening tolerance** on the cooling balance and M7 check, not by oversizing the controller.

---

## 5. The solver

`nexablock/core/solver.py` — sequential-modular with Wegstein recycle.

- **Tarjan SCC** finds recycle loops in the connection graph.
- **Kahn's algorithm** gives a topological order for acyclic portions.
- **Wegstein iteration** with bounded q ∈ [−5, 0] for any tear streams (the recycle convergence acceleration).
- **Block `compute()` runs idempotently** — `block.results.clear()` is called before each compute so multiple Wegstein passes don't trip the framework's duplicate-label guard.
- **No raise on max-iter exhaustion**. Solver completes a final forward pass with the last tear estimates and returns `SolvedSystem.convergence.converged = False`. The renderer turns this into a red "⚠ NOT CONVERGED" card with the loop name, residual, and reason; KPIs go red.

GT system is acyclic — no Wegstein iteration needed at the system level. Convergence card reads "converged (no recycle loops)".

---

## 6. Convergence → Feasibility → Audit

Three independent status objects, threaded through `SolvedSystem` (for convergence) and the engine `r["..."]` dict (for feasibility + audit).

### 6.1 Convergence

Per-loop `LoopStatus` aggregated into a system-wide `ConvergenceStatus`. Surfaces the loop name (`Heater→Cooler→Recycle`), iterations used, final residual, tolerance, and a reason on failure. See [`DICTIONARY.md`](DICTIONARY.md) under "Convergence".

### 6.2 Feasibility — resource balances

`FeasibilityStatus` wraps a list of `ResourceBalance` objects, each with supply / demand / balance / shortfall / breakdown / assumption / tolerance.

For the v2 GT system:

| Balance | Supply | Demand | Tolerance |
|---|---|---|---|
| **Power** | GT derated capacity | GPU silicon + cassette overhead + plant aux + (island) external_load | none (hard) |
| **Cooling capacity** | LiBr Q_cool | GPU silicon heat + cassette overhead heat | **2.5 % screening** |

Power balance breakdown lines (Island):
```
GT derated capacity (available)        +9,300 kW    supply
GT current output (info)               +5,670 kW    operating point (auto-derived shown)
Operating headroom (info)              +3,630 kW    derated − current
GPU silicon (IT power)                 −5,000 kW
Cassette overhead (pumps/ctl)            −250 kW
MED electrical (pumps)                    −0 kW    (= 0 when libr_frac=1 in auto)
LiBr pump electrical                     −79 kW
Cooling tower fan electrical            −111 kW
GT auxiliaries                           −93 kW
Plant BoP (lights/HVAC)                  −57 kW
External load (island, manual)            −0 kW    (user input; 0 by default)
```

In grid-tied mode the External-load line is replaced by:
```
Grid export (computed, export-only)     +N kW      (= supply − NEXA demand)
```

### 6.3 Audit — 44 checks (island/auto), 42 (manual), 44 (grid/auto)

Six categories of "real-issue" assertions on every solve:

| Category | Block-level checks | What they verify |
|---|---|---|
| **Energy closure** | E1–E8 (+ M6 via energy-balance helper) | First-law equations close per block (NG·LHV·η, fuel = power + exhaust, exhaust·η = duty, Q_gen·COP = Q_cool, Heat = IT + overhead, etc.) |
| **Mass closure** | M1–M8 (M7 with 2.5 % tolerance) | Σṁ_in = Σṁ_out per stream kind per block (HRSG FW = steam, splitter in = libr+med, MED sw = dist+brine, etc.) |
| **Second law** | T1–T10 | Positive pinch in HRSG, ΔT-per-effect ≥ 3°C in MED, CT approach > 0, T_steam > T_condensate, etc. |
| **Plausibility** | P1–P11 (system-level) + P12, P13 (generic) | η < 0.55, COP in (0.5, 1.3), GOR in (4, 10), recovery < 0.5, no negative flows, every kW value finite, GT actual ≤ derated, libr_frac + med_frac = 1.0, etc. |

Plus 5 composition checks added by `simulators/gt_system/audit.py`:

| id | name | shown in |
|---|---|---|
| **E9** | Bus closure: supply = NEXA + external (island) OR NEXA + grid_export (grid) | both |
| **F1** | Island balance closed without grid import | island only |
| **F2** | External load finite and ≥ 0 | both |
| **F3** | Derived `load_pct` ≤ 100 % | when `gt_power_mode=auto` |
| **F4** | Derived `libr_frac` in [0, 1] | when `steam_split_mode=auto` |
| **F5** | Grid export ≥ 0 (imports forbidden) | grid only |

**Coverage table — every v2 KPI is named by at least two checks**:

| KPI | Vouched by |
|---|---|
| GT actual power | E1, E2, M6, T8, P1, P2, P3, P11, E9 |
| NG consumption | E1, M6 |
| Steam generation | E3, E4, M1, M2, T1, T2, T3, P8, P9, P10 |
| LiBr cooling capacity | E5, E6, M3, M8, T5, T6, T7, T9, P4, F4 |
| GPU IT load | E7, M7, P7 |
| MED water production | E8, M4, M5, T4, T10, P5, P6 |

### 6.4 Per-KPI basis is now data-driven from audit coverage

```python
cov = audit.coverage_for(kpi_label)
if   cov == "failed":   basis = "unverified"   # a covering check failed
elif cov == "passed":   basis = engine_basis   # respected — typically "verified"
else:                   basis = "screening"    # no check named this KPI
```

Plus global override: convergence / any-feasibility / generic-audit-failure (P12/P13) → every row becomes `unverified`.

---

## 7. Studies

After Run, the Studies card (between chart and results table) drives three exploratory tools:

- **Sensitivity** — multi-select inputs × multi-select KPIs → multi-panel tornado, one tornado per KPI, ranked by |elasticity|, zero-elasticity bars suppressed.
- **Sweep** — 1D / 2D toggle.
  - 1D: pick X input, multi-select KPIs → subplots, one per KPI (independent y-scales so the small-magnitude KPIs don't crush against the big ones).
  - 2D: pick X input + Y input + single KPI → 5×5 grid, real `contourf` with colorbar.
- **Scenarios** — predefined named bundles ("summer peak", "winter low load") solved as a batch → grouped-bar comparison normalised to base.

All study results are stashed per-engine (in-memory dict + disk pickle under `~/.enginetools/studies/`) for the Download Study CSV / Excel buttons. Reports can attach the latest study chart via the "Include latest study" checkbox.

---

## 8. Reports

Every PDF and Excel report carries these sections, in order:

1. Title + engine name
2. **Design point** (input table)
3. **Convergence** (green ✓ / red ⚠)
4. **Power balance** (one band) + (island) external load OR (grid) grid export in breakdown
5. **Cooling capacity balance** (one band)
6. **Audit** — `N/N passed`, or a table listing every failed check (name, category, detail)
7. **Results table** with the per-KPI basis colour
8. **Chart** — flowsheet (SVG, rasterised to PNG via cairosvg for PDF/PPTX), or sweep line chart for the load-sweep adapter
9. (Optional) **AI Analysis** narrative
10. Method note from the engine
11. (Optional, ticked at download) **Study** section/sheet with chart + table

The exact same layout is on the Excel "Study" sheet whether it came from `study_to_xlsx` standalone or from `build_excel(..., study=...)` — `write_study_sheet` is the one source of truth.

---

## 9. Where to look in the code

| Concept | File | Key function/class |
|---|---|---|
| Block contract | `nexablock/core/block.py` | `Block.compute`, `Block.audit_checks` |
| Stream + Port | `nexablock/core/stream.py`, `port.py` | `Stream`, `StreamKind`, `Port` |
| System + Solver | `nexablock/core/system.py`, `solver.py` | `System.solve(tol, max_iter)`, `Solver._solve_with_recycle` |
| Convergence | `nexablock/core/convergence.py` | `ConvergenceStatus`, `convergence_summary` |
| Audit framework | `nexablock/audit/*.py` | `audit()`, `AuditStatus`, helper constructors |
| §7.5 SVG renderer | `nexablock/viz/svg.py` | `render(system_or_solved)` |
| Studies primitives | `nexablock/studies/*.py` | `ParameterSweep`, `OneAtATimeSensitivity`, `ScenarioRunner` |
| Chart helpers | `nexablock/studies/charts.py` | `tornado_chart`, `sweep_chart`, `sweep_contour` |
| GT system composition | `simulators/gt_system/system.py` | `build_gt_system(p)`, `summary(solved)` |
| GT controller | `simulators/gt_system/control.py` | `control_setpoints(p)` |
| GT feasibility | `simulators/gt_system/feasibility.py` | `power_balance`, `cooling_balance`, `feasibility` |
| GT composition audit | `simulators/gt_system/audit.py` | `gt_system_audit_checks(solved)` |
| v2 engine adapter | `nexa_toolkit/engines/gt_system_v2.py` | `GTSystemV2`, `_params_from(v)` |
| Reporting pipeline | `nexa_toolkit/reporting/generic_report.py` | `build_pdf`, `build_excel`, `write_study_sheet`, `_result_rows` |
| Dash UI | `nexa_toolkit/app/app.py` | `input_fields`, `results_table`, `convergence_card`, `feasibility_card`, `audit_card`, `datasets_panel`, `_sync_gt_load` |
| Input datasets (Save/Load/Update/Delete) | `nexa_toolkit/framework/datasets.py` | `save_dataset`, `get_dataset`, `delete_dataset`, `list_datasets` |

---

## 10. A complete worked example — what happens when you click Run

Setup: pick **GT System v2 — nexablock** in the dropdown. Defaults: island / auto / auto, `gpu_it_kW = 5000`, `external_load_kW = 0`, `t_ambient_C = 25`.

1. **Click Run.** `_run` callback fires.
2. **`engine.solve(values)`** in `gt_system_v2.py`:
   - `_params_from(v)` translates UI ints/floats → `GTSystemParams` with mode strings.
   - `build_gt_system(params)` is called.
3. **`build_gt_system`** in `system.py`:
   - `control_setpoints(p)` runs the fixed-point. At GPU 5 MW island/auto: load_pct ≈ 61 %, libr_frac → 1.0, external_load = 0, grid_export = 0, derived_load_pct = True, derived_libr_frac = True.
   - 7 blocks instantiated with the resolved load_pct and libr_frac.
   - Feedwater seed (20 kg/s) + seawater seed (100 kg/s) attached to HRSG and MED inlets.
   - 6 connections wired (GT→HRSG, HRSG→splitter, splitter→LiBr, splitter→MED, LiBr→CT, LiBr→GPU).
   - `sys.solve()` runs the framework solver — acyclic, single topo pass.
   - Each block's `compute()` populates its outlet streams + result rows.
   - Returns `SolvedSystem` with `.convergence` (passed, acyclic) and stashed `.control`, `.operating_mode`.
4. **`summary(solved)`** extracts the top-level KPIs into a dict including the derived setpoints and mode-specific KPIs.
5. **`feasibility(solved, bop_frac=...)`** returns a `FeasibilityStatus` with two `ResourceBalance` objects — Power and Cooling capacity. Cooling carries `tol_rel=0.025` so the 1.9 % gap at GPU 5 MW reads as feasible.
6. **`audit(solved, extra_checks=gt_system_audit_checks(solved))`** runs all 44 checks. M7 honors the 2.5 % screening tolerance. P12/P13 sweep all streams + all kW results.
7. **The engine returns** `r = {"solved", "kpis", "feasibility", "audit"}`.
8. **The UI callback** assembles the highlight cards, the convergence card, the feasibility cards (one per balance), the audit card, the chart (SVG flowsheet), the results table (with basis colours read from `audit.coverage_for(label)`), and the smart section.

The user sees: ✓ Converged · ✓ Power balance (Supply 9300 · Demand 5430 · Balance +3870 kW) · ✓ Cooling capacity (Supply 5149 · Demand 5250 · within 2.5 % tolerance) · ✓ Audit 44/44.

---

## 11. Where to go from here

- **Adjust the mode switches** (Operating mode, GT power, Steam split) to explore the design space.
- **Run Sensitivity** with multi-select inputs/KPIs to see what matters.
- **Run a 2D sweep** of, say, `gpu_it_kW × t_ambient_C` with `Grid export` as the contoured KPI to learn the export envelope.
- **Tick "Include latest study"** before downloading PDF/Excel to embed the chart in the report.
- For terminology, see [`DICTIONARY.md`](DICTIONARY.md).
- For framework / extension developer notes, see [`ARCHITECTURE.md`](ARCHITECTURE.md).
- For day-to-day UI walkthrough, see [`MANUAL.md`](MANUAL.md).
