# EngineTools — Glossary

Alphabetical reference for every term used across the codebase, reports, and UI.

---

**Audit** — The universal post-solve check layer at `nexablock/audit/`. Walks every block's declared `audit_checks()`, appends system-level extras from `simulators/<system>/audit.py`, runs framework-generic safety nets (P12 no-negative-flows, P13 finite kW values). Returns an `AuditStatus`. See [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) §6.3.

**`AuditStatus`** — Aggregate over a list of `CheckResult` objects. `.passed`, `.failed()`, `.by_category()`, `.coverage_for(kpi_label)` returning `"passed" | "failed" | "uncovered"` — drives the per-KPI basis in the results table.

**Auto mode** — A control mode where the framework derives the value (the GT `load_pct`). Opposite of Manual mode where the user sets the value directly. (`libr_frac` is no longer a derived value — with no steam splitter it is constant 1.0.)

**Basis** — The trustworthiness tag on each row of the results table. Was hardcoded; is now data-driven from audit coverage.
- `verified` (green) — at least one audit check vouches for this KPI label and every covering check passed.
- `unverified` (red) — a covering check failed, OR convergence / feasibility / generic-audit failed globally.
- `screening` (amber) — no audit check named this KPI; reported but not asserted.
- `input` (grey) — user-entered value, not a computed result.

**Block** — `nexablock/core/block.py`. The contract every process unit implements: `_build_params`, `_build_inlets`, `_build_outlets`, `compute()`, plus optional `audit_checks()`, `render_ports()`, `references()`, `test_cases()`. The GT system uses six: GasTurbine, HRSG, LiBrChiller, GPUCassette, MED, Radiator. (SteamSplitter and CoolingTower block files still exist but the GT system no longer wires them.)

**BoP — Balance of Plant** — *(legacy)* The old lumped plant-wide electrical fraction (`bop_frac × GT actual power`). Superseded by the itemised IT/flow-driven plant-electrical model in `plant_loads.py` (pumps + dry-cooler fan + container HVAC + lights). The `bop_frac` field is retained on `GTSystemParams` for backward compatibility but no longer drives the power balance. See **Plant aux**.

**Cassette overhead** — The non-GPU electrical load *inside* the immersion-cooling cassette: solution pumps, controls, switchgear, dielectric-fluid heaters. Computed as `IT × (cassette_pue − 1)`. Both **drawn from the bus** AND **dissipated into the coolant**, so the report itemises it on both the electrical AND cooling balance sides.

**`CheckResult`** — `nexablock/audit/checks.py`. One audit check's outcome: name, category, passed (bool), measure (supply/demand/balance | pass/fail | bounds), supply/demand/balance/tolerance values, detail string, list of affected KPI labels, optional error.

**CHW supply / coolant supply** — The cold coolant the LiBr chiller delivers to the GPU cassette. In the GT system this is the **dielectric immersion fluid**, not chilled water — supplied at `gpu_t_in_C` (default 30°C), returning at `gpu_t_out_C` (default 42°C). The LiBrChiller block still names its outlet `chw_supply` for historical reasons, but it carries the dielectric coolant (`coolant_cp ≈ 2100`, `coolant_rho ≈ 780`). The T6 audit check (CHW supply ≥ 5°C) is comfortably satisfied at 30°C. See **Dielectric coolant loop**.

**Control modes** — Four mode switches on the v2 GT engines: `operating_mode` (Island / Grid-tied), `gt_power_mode` (Auto / Manual), `med_bypass_mode` (Manual / Auto — see **MED bypass**), and `steam_split_mode` (Off / Auto — see **Steam split / Calorifier**), plus the `external_load_kW` scalar (functionally tied to operating_mode).

**Steam split / Calorifier** — `steam_split_mode` (Off default / Auto). When the LiBr chiller would *over-perform* — GPU cooling demand below what the HRSG steam drives (e.g. GPU IT load dropped while the GT runs on for power) — Auto mode feeds the chiller only the steam it needs (`libr_frac = libr_steam_demand / total_steam`, via a `SteamSplitter`) and routes the **surplus steam through a `Calorifier`** (a steam→hot-water heat exchanger — "a LiBr without the chilling") whose ~95 °C hot water joins the MED rejection loop through a `Mixer`. This matches the chiller to the GPU load (no over-cooling), keeps every unit on its native heat grade (LiBr = steam, MED = hot water), and turns the surplus into fresh water. Off: all steam → LiBr (`libr_frac` = 1.0), the validated default topology. Audit adds T12 (calorifier steam hotter than its output) and M9 (mixer mass balance) when on.

**`ControlSetpoints`** — `simulators/gt_system/control.py`. The result of the controller's fixed-point iteration: resolved `load_pct`, `libr_frac` (always 1.0), `external_load_kW`, `grid_export_kW`, derived-vs-user flags (`derived_libr_frac` is always False), diagnostic `required_load_for_elec_pct` and `required_load_for_steam_pct`, iteration count.

**Convergence** — Whether the recycle/tear solver loops settled to a fixed point. Acyclic systems (like the GT v2) are trivially converged. `ConvergenceStatus` carries per-loop `LoopStatus` entries; the renderer turns it into a green ✓ / red ⚠ card and (on failure) flips every KPI to `unverified`.

**Cooling balance / Cooling capacity balance** — One of the two resource balances surfaced by the GT v2 feasibility check. Supply = LiBr Q_cool; Demand = GPU silicon heat + cassette overhead heat. Honors a **2.5 % screening tolerance** for controller-vs-block precision noise.

**COP — Coefficient of Performance** — For the LiBr chiller, `COP = Q_cool / Q_gen`. Single-effect range 0.5–0.85 (audit check P4 enforces (0.5, 1.3)). Default 0.7.

**Dataset (input dataset / "default")** — A named snapshot of all of an engine's input values, saved from the UI's Datasets panel (Save / Update / Load / Delete). Stored per-engine on disk at `~/.enginetools/defaults/<engine_key>.json`, so datasets persist across restarts and only show for the engine they belong to. Implemented in `nexa_toolkit/framework/datasets.py`.

**Derate / derated capacity** — Ambient-corrected GT maximum power. `derate = max(0.50, 1 − 0.007 × max(0, T_amb − 15°C))` (0.7 %/°C above ISO 15°C, floor 0.50). The derated capacity is the available envelope and is shown as **info** in the power breakdown — but the **power balance supply** is **GT net power** (gross − GT aux), not the derated capacity. See **GT net power**.

**Derived value** — A computed setpoint in auto mode (`GT load_pct (auto-derived)`). Surfaced in the outputs table with that label so the user can see what the controller picked. (`libr_frac` is no longer derived — it is constant 1.0.)

**Δh / Δh_libr** — Specific enthalpy difference. `Δh_libr = h_steam_in − h_sat_liq_at_atm`. Used by the LiBr chiller to convert steam mass flow into thermal duty.

**Dielectric coolant loop** — The closed single-phase immersion loop between the LiBr chiller and the GPU cassette, and the one **real recycle loop** in the GT system (solver tears `LiBrChiller.chw_supply → GPUCassette.coolant_in`, Wegstein-converges). The working fluid is a dielectric immersion fluid (`coolant_cp ≈ 2100 J/kg·K`, `coolant_rho ≈ 780 kg/m³`), supplied cold at `gpu_t_in_C` (default 30°C) and returned warm at `gpu_t_out_C` (default 42°C, ΔT 12 K). Not chilled water.

**Elasticity** — In sensitivity analysis, `ε = (dY/dX) × (X₀/Y₀)` — the percent change in KPI Y per percent change in input X. Unitless, comparable across inputs of different scale. Drives the tornado bar rank.

**`Engine`** — `nexa_toolkit/framework/contract.py`. The v1 contract used by the EngineTools UI: `key`, `name`, `inputs` (list of `InputSpec`), `solve(values)` → result dict, `outputs(result)` → list of `OutputSpec`, optional `highlights`, `chart`, `study_hooks`. Subclassed by `GTSystemV2` and `GTSystemV2LoadSweep`.

**External load** — Electrical demand outside the modelled NEXA plant. In **island mode**: user-entered scalar (counted in power balance demand). In **grid-tied mode**: hidden — replaced by the auto-computed `Grid export`.

**Feasibility** — Whether supply ≥ demand for each modelled resource. Different from convergence (solver settling) and audit (first-principles checks). `FeasibilityStatus` wraps a list of `ResourceBalance` objects.

**`FeasibilityStatus`** — Aggregate over a list of `ResourceBalance` objects. `.feasible` is True iff every balance is. `.by(resource)` lookup by name.

**Flowsheet** — The §7.5 SVG renderer's output. `nexablock/viz/svg.py:render(system_or_solved) → str`. Block boxes coloured by category, connection paths coloured by stream kind. Embedded in the v2 engine's chart slot.

**GOR — Gain Output Ratio** — MED screening rule: `GOR ≈ 0.8 × n_effects`. Distillate per kg of latent heat input. Audit checks M5 / P5 keep it in the (4, 10) range; values outside this are non-physical for thin-film falling-film MED.

**Grid export** — In grid-tied mode, the auto-computed surplus electrical = `max(0, GT net power − NEXA demand)`. Export-only — grid imports are forbidden per the NEXA specification. F5 audit check enforces ≥ 0.

**GT net power** — The GT's electrical output to the bus: `GT gross power − GT aux electrical`. GT aux is the package's own parasitic (lube oil, fuel skid, controls) — an *internal derate*, so it never appears on the bus; the bus sees the net only. **GT net power is the power-balance supply** (not gross, not derated capacity). Reported as the `GT net power` result on the GasTurbine block.

**GT load (kW)** — A UI field on the GT engines, shown under **GT load (%)** and twinned to it both ways: `kW = derated capacity × load% ÷ 100` (actual-power basis), where `derated = rated power × max(0.50, 1 − 0.007·max(0, T_amb − 15 °C))`. Editing %, kW, rated power, or ambient keeps the pair consistent. It mirrors `load_pct` — not a separate input — so it equals **GT actual power** in manual GT-power mode and is inert in auto mode. See [`MANUAL.md`](MANUAL.md) §3.1.

**`gt_system_v2`** — The v2 trusted GT system engine. Drop-in replacement for the v1 trusted GT tool, validated within ±2 % across 14 reference KPIs (`tests/test_gt_system.py`). Default selection in the system dropdown.

**`gt_system_v2_loadsweep`** — A screening variant of `gt_system_v2` that runs a 50–100 % GT-load sweep in the chart slot instead of the SVG flowsheet.

**Heat load** — In the GPU cassette, `q_W = IT + cassette_overhead`. Equals the GPU's total electrical draw (immersion physics: all electrical → heat). Drives the cooling demand.

**HRSG — Heat Recovery Steam Generator** — The block that converts GT exhaust heat into steam. Effectiveness `hrsg_eff_pct` typically 75–90 %. Generates steam at `T_sat(P_steam) + 30°C` superheat.

**Immersion cooling** — Single-phase dielectric-fluid immersion. The framework assumes 100 % of GPU electrical input dissipates as heat into the dielectric coolant — no part of the silicon's electrical input goes anywhere else. This is the basis for the cooling-balance demand equation. See **Dielectric coolant loop**.

**`InputSpec`** — One input field on an engine. `(key, label, unit, default, min, max, choices=None)`. When `choices` is provided, renders as a dropdown; otherwise a number input.

**Island mode** — Operating mode where the plant is autonomous. No grid backstop. GT must supply ALL demand. The `external_load_kW` input is honored; deficits are hard feasibility failures (not softened into "grid import").

**LiBr-priority** — *(historical)* The old auto steam-split policy that fed the chiller before MED. No longer applies: there is no steam splitter, all HRSG steam goes to the LiBr chiller (`libr_frac = 1.0`), and MED is driven by the chiller's heat rejection instead of steam. See **MED**, **Steam splitter**.

**Manual mode** — The control mode where the user's numeric `load_pct` input is used directly (instead of the auto-derived value). Opposite of auto.

**MED — Multi-Effect Distillation** — Thermal desalination block (`nexablock/blocks/med.py`). Now **rejection-driven**: its `loop_in` is the LiBr chiller's hot heat-rejection water (not steam). It captures `(1 − med_bypass_frac)` of that loop heat, makes distillate at `GOR × Q_captured / h_fg`, and passes the loop water on to the radiator via `loop_out`. The manual `med_bypass_frac` 3-way valve routes part of the rejection heat around MED. If there is no usable rejection heat it produces zero water (no steam fallback).

**Operating mode** — `operating_mode` input on the v2 GT engine. Values: `island` (default) / `grid_tied`. Drives whether external load is manual or auto-computed, and whether deficits are hard fails or softened.

**`OutputSpec`** — One row in the results table. `(label, value, unit, basis, fmt)`. The `basis` is the *engine-declared* one; the renderer may override it from audit coverage.

**P-checks (P1–P14)** — Plausibility audit checks: bounds on η, COP, GOR, recovery, PUE, derate, load_pct, etc., plus P11 (GT actual ≤ derated), P14 (radiator 3-way split in [0, 100] %), and the generic P12 (no-negative-flows) and P13 (finite kW values). Plus the system-level F1, F2, F3 (auto), F5 (grid) composition checks (also Plausibility category). (There is no F4 — `libr_frac` is constant 1.0.)

**Plant aux** — The itemised, IT/flow-driven plant electrical model in `simulators/gt_system/plant_loads.py`. Each **pump** = `Q·ΔP/η` (dielectric coolant, LiBr internal solution, cooling-loop, HRSG feed-water/BFP, seawater intake, MED feed, brine, distillate, condensate). The **dry-cooler fan** rides a VSD: `fan = fan_rated_frac · Q_cond · utilisation³` (cube law on dry-cooler utilisation). **HVAC** = `n_containers · area · U · (T_ambient − T_inside)` with `n_containers = containers_per_MW · IT_MW`; **lights** = `lights_frac · HVAC`. All lines appear in the power-balance breakdown. (GT aux is *not* here — it's an internal GT derate; see **GT net power**.) Replaces the old lumped `libr_pump_frac` / `ct_fan_frac` / `bop_frac` fractions and the MED 1.5 kWh/m³ rule.

**PFD page** — The Process Flow Diagram appended as the final **landscape** page of the PDF report for the GT-system engines. Redrawn natively in the report engine (`nexa_toolkit/reporting/pfd_page.py`) with every value refreshed from the current solve — block boxes, flow streams, a Key-results table, an energy-balance/audit panel, the island/grid badge + named operating-mode strip, and a stream/basis legend. The export cell is mode-aware (island → "External load"; grid-tied → "Grid export").

**PUE — Power Usage Effectiveness** — Data centre metric. **Cassette PUE** is an *input* (ratio, default 1.05) that sets the cassette overhead `IT × (cassette_pue − 1)`. **Plant PUE** is the single computed *result* — see below. (The input key is `cassette_pue`; the old standalone "GPU PUE" results row that merely echoed the input was removed.)

**Plant PUE (electrical, export excluded)** — The one overall plant efficiency KPI, basis `screening`: `(IT + cassette overhead + itemised plant aux + GT aux) / IT`, where "itemised plant aux" is the total from `plant_loads` (pumps + dry-cooler fan + HVAC + lights). Electrical only — excludes MED electrical, external load and grid export. Guarded on IT > 0. Computed in `summary()` in `system.py`. At island/auto defaults it reads ≈ 1.116. Rolls every overhead consumption into a single figure so the report doesn't list pump/fan/cassette-PUE rows separately (those stay in the inputs).

**Radiator** — The dry, forced-air cooling block (`nexablock/blocks/radiator.py`) that replaces the evaporative cooling tower. The hot loop water hits a 3-way auto bypass valve that splits it between the radiator core (cooled to `T_ambient + approach`) and a bypass (stays hot), remixing to a controlled outlet — the HRSG feedwater return set-point `fw_t_C` — so the radiator rejects only surplus heat and never overcools the feedwater. `Fan electrical = fan_frac × Q_rad`. Audit: T5, T5b, P14. Closes the cooling loop back to the HRSG feedwater.

**MED bypass (`med_bypass_mode` / `med_bypass_frac`)** — The MED 3-way valve that routes part of the LiBr heat-rejection loop *around* MED; MED captures `(1 − bypass)` of the loop heat, the bypassed share stays hot. Two modes (`med_bypass_mode`, default **Auto** on both GT engines):
- **Manual** — uses the fixed `med_bypass_frac` (0–1) directly. `loop_cold_C = fw_t_C` (MED cools the loop exactly to the set-point).
- **Auto** — a cascade with the radiator that **holds the HRSG return at the feedwater set-point** `fw_t_C`. MED is allowed to cool toward its real cold-end (`sw_t_C + med_cold_pinch_K`, default seawater + 15 K, *below* the set-point); the bypass auto-opens just enough to blend the MED-cooled branch and the hot bypassed branch back to `fw_t_C`, so the feedwater inlet holds set-point and the radiator idles. Resolved by `med_bypass_fraction(p)` / `med_loop_cold_C(p)` in `control.py`; shared by both the single- and double-effect engines. At the design point it captures ≈ the same heat (≈ same MED water) as Manual `bypass=0`, but self-adjusts the valve as load / ambient / seawater change.

**Resource balance** — One supply / demand pair surfaced by feasibility. `ResourceBalance` carries resource name, unit, feasibility flag, supply, demand, balance, shortfall, breakdown (itemised contributors), assumption text, and screening tolerance.

**Screening tolerance** — A relative tolerance below which gaps are considered controller-vs-block precision noise rather than real engineering deficits. Cooling balance uses 2.5 %; M7 audit check uses 2.5 %.

**Sensitivity** — One-at-a-time central-difference perturbation around a base point. `OneAtATimeSensitivity` returns elasticities (% ΔKPI per % ΔInput) for ranking inputs. Multi-panel tornado in the UI shows one panel per selected KPI.

**`SolvedSystem`** — The output of `System.solve()`. Carries the wired system, the `ConvergenceStatus`, and (for the GT system) stashed `.control` (`ControlSetpoints`), `.operating_mode`, and `.params` (the `GTSystemParams`, used by `plant_loads` in `summary`/feasibility/audit) for downstream consumers.

**`SteamSplitter`** — *(historical)* The block that used to distribute HRSG steam between LiBr and MED via `libr_frac`. The GT system no longer wires it: all steam goes to the LiBr chiller. The block file still exists in `nexablock/blocks/` but is unused by `gt_system`.

**Stream** — A process stream connecting two ports. Carries `mdot, T, P, h, x, power, props`. `StreamKind` ∈ {WATER_STEAM, ENERGY, ELECTRICAL, GENERIC_FLUID}.

**Study** — Sensitivity, sweep, or scenarios. Returns a `SensitivityResult` / `SweepResult` / `ScenarioResult`. Stored per-engine in-memory + on disk (pickled to `~/.enginetools/studies/`). Downloadable as standalone CSV / Excel; attachable to report exports.

**Sweep** — `ParameterSweep` walks a grid of input combinations and collects KPIs. 1D in UI is a single-X line chart (subplots, one per KPI); 2D is X × Y → KPI contour on a 5×5 grid.

**Sufficiency check** — An audit check that asserts supply ≥ demand without requiring strict equality. Used where mass-balance equality would be too strict for screening (M1 HRSG feedwater seed, M7 GPU coolant inlet flow).

**System** — `nexablock/core/system.py`. Composes blocks and connections into a graph; `solve(tol, max_iter)` returns a `SolvedSystem`.

**Tornado (sensitivity)** — Horizontal-bar chart of `|elasticity|` for one or more KPIs, ranked descending. Multi-panel tornado in the v2 UI shows one panel per selected KPI.

**Wegstein iteration** — The bounded-q recycle convergence acceleration the solver uses. `q ∈ [−5, 0]` per the standard sequential-modular reference.

**Wet bulb** — *(historical)* Was the evaporative cooling-tower design ambient. No longer used: the wet cooling tower is replaced by a dry **Radiator** that approaches the ambient **dry-bulb** air temperature (`T_rad = T_ambient + approach`). See **Radiator**.
