# EngineTools — Glossary

Alphabetical reference for every term used across the codebase, reports, and UI.

---

**Audit** — The universal post-solve check layer at `nexablock/audit/`. Walks every block's declared `audit_checks()`, appends system-level extras from `simulators/<system>/audit.py`, runs framework-generic safety nets (P12 no-negative-flows, P13 finite kW values). Returns an `AuditStatus`. See [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) §6.3.

**`AuditStatus`** — Aggregate over a list of `CheckResult` objects. `.passed`, `.failed()`, `.by_category()`, `.coverage_for(kpi_label)` returning `"passed" | "failed" | "uncovered"` — drives the per-KPI basis in the results table.

**Auto mode** — A control mode where the framework derives the value (currently for `load_pct` and `libr_frac`). Opposite of Manual mode where the user sets the value directly.

**Basis** — The trustworthiness tag on each row of the results table. Was hardcoded; is now data-driven from audit coverage.
- `verified` (green) — at least one audit check vouches for this KPI label and every covering check passed.
- `unverified` (red) — a covering check failed, OR convergence / feasibility / generic-audit failed globally.
- `screening` (amber) — no audit check named this KPI; reported but not asserted.
- `input` (grey) — user-entered value, not a computed result.

**Block** — `nexablock/core/block.py`. The contract every process unit implements: `_build_params`, `_build_inlets`, `_build_outlets`, `compute()`, plus optional `audit_checks()`, `render_ports()`, `references()`, `test_cases()`. Subclassed by GasTurbine, HRSG, LiBrChiller, MED, GPUCassette, SteamSplitter, CoolingTower, and the Recycle tear block.

**BoP — Balance of Plant** — Plant-wide electrical consumption that isn't tied to any specific block: lights, HVAC, fire pumps, controls room, switchgear. Modelled as `bop_frac × GT actual power`. Default `bop_frac = 0.010` (1 % of GT output).

**Cassette overhead** — The non-GPU electrical load *inside* the immersion-cooling cassette: solution pumps, controls, switchgear, dielectric-fluid heaters. Both **drawn from the bus** AND **dissipated into the coolant**. Split out from the previous hidden `IT × PUE` formula so the report itemises it on both the electrical AND cooling balance sides.

**`CheckResult`** — `nexablock/audit/checks.py`. One audit check's outcome: name, category, passed (bool), measure (supply/demand/balance | pass/fail | bounds), supply/demand/balance/tolerance values, detail string, list of affected KPI labels, optional error.

**CHW — Chilled Water** — The cold water supply the LiBr chiller delivers to the GPU cassette. Set point typically 5–10°C (block enforces ≥ 5°C via audit check T6).

**Control modes** — Three mode switches on the v2 GT engine: `operating_mode` (Island / Grid-tied), `gt_power_mode` (Auto / Manual), `steam_split_mode` (Auto / Manual). Plus `external_load_kW` which is a scalar but functionally tied to operating_mode.

**`ControlSetpoints`** — `simulators/gt_system/control.py`. The result of the controller's fixed-point iteration: resolved `load_pct`, `libr_frac`, `external_load_kW`, `grid_export_kW`, derived-vs-user flags, diagnostic `required_load_for_elec_pct` and `required_load_for_steam_pct`, iteration count.

**Convergence** — Whether the recycle/tear solver loops settled to a fixed point. Acyclic systems (like the GT v2) are trivially converged. `ConvergenceStatus` carries per-loop `LoopStatus` entries; the renderer turns it into a green ✓ / red ⚠ card and (on failure) flips every KPI to `unverified`.

**Cooling balance / Cooling capacity balance** — One of the two resource balances surfaced by the GT v2 feasibility check. Supply = LiBr Q_cool; Demand = GPU silicon heat + cassette overhead heat. Honors a **2.5 % screening tolerance** for controller-vs-block precision noise.

**COP — Coefficient of Performance** — For the LiBr chiller, `COP = Q_cool / Q_gen`. Single-effect range 0.5–0.85 (audit check P4 enforces (0.5, 1.3)). Default 0.7.

**Dataset (input dataset / "default")** — A named snapshot of all of an engine's input values, saved from the UI's Datasets panel (Save / Update / Load / Delete). Stored per-engine on disk at `~/.enginetools/defaults/<engine_key>.json`, so datasets persist across restarts and only show for the engine they belong to. Implemented in `nexa_toolkit/framework/datasets.py`.

**Derate / derated capacity** — Ambient-corrected GT maximum power. `derate = max(0.50, 1 − 0.007 × max(0, T_amb − 15°C))`. The 0.7 %/°C above ISO 15°C is conservative-screening for typical industrial turbines. The **power balance supply** uses derated capacity (the available envelope), not actual operating power.

**Derived value** — A computed setpoint in auto mode (`load_pct (auto-derived)`, `libr_frac (auto-derived)`). Surfaced in the outputs table with that label so the user can see what the controller picked.

**Δh / Δh_libr** — Specific enthalpy difference. `Δh_libr = h_steam_in − h_sat_liq_at_atm`. Used by the LiBr chiller to convert steam mass flow into thermal duty.

**Elasticity** — In sensitivity analysis, `ε = (dY/dX) × (X₀/Y₀)` — the percent change in KPI Y per percent change in input X. Unitless, comparable across inputs of different scale. Drives the tornado bar rank.

**`Engine`** — `nexa_toolkit/framework/contract.py`. The v1 contract used by the EngineTools UI: `key`, `name`, `inputs` (list of `InputSpec`), `solve(values)` → result dict, `outputs(result)` → list of `OutputSpec`, optional `highlights`, `chart`, `study_hooks`. Subclassed by `GTSystemV2` and `GTSystemV2LoadSweep`.

**External load** — Electrical demand outside the modelled NEXA plant. In **island mode**: user-entered scalar (counted in power balance demand). In **grid-tied mode**: hidden — replaced by the auto-computed `Grid export`.

**Feasibility** — Whether supply ≥ demand for each modelled resource. Different from convergence (solver settling) and audit (first-principles checks). `FeasibilityStatus` wraps a list of `ResourceBalance` objects.

**`FeasibilityStatus`** — Aggregate over a list of `ResourceBalance` objects. `.feasible` is True iff every balance is. `.by(resource)` lookup by name.

**Flowsheet** — The §7.5 SVG renderer's output. `nexablock/viz/svg.py:render(system_or_solved) → str`. Block boxes coloured by category, connection paths coloured by stream kind. Embedded in the v2 engine's chart slot.

**GOR — Gain Output Ratio** — MED screening rule: `GOR ≈ 0.8 × n_effects`. Distillate per kg of steam input. Audit checks M5 / P5 keep it in the (4, 10) range; values outside this are non-physical for thin-film falling-film MED.

**Grid export** — In grid-tied mode, the auto-computed surplus electrical = `max(0, GT actual power − NEXA demand)`. Export-only — grid imports are forbidden per the NEXA specification. F5 audit check enforces ≥ 0.

**GT load (kW)** — A UI field on the GT engines, shown under **GT load (%)** and twinned to it both ways: `kW = derated capacity × load% ÷ 100` (actual-power basis), where `derated = rated power × max(0.50, 1 − 0.007·max(0, T_amb − 15 °C))`. Editing %, kW, rated power, or ambient keeps the pair consistent. It mirrors `load_pct` — not a separate input — so it equals **GT actual power** in manual GT-power mode and is inert in auto mode. See [`MANUAL.md`](MANUAL.md) §3.1.

**`gt_system_v2`** — The v2 trusted GT system engine. Drop-in replacement for the v1 trusted GT tool, validated within ±2 % across 14 reference KPIs (`tests/test_gt_system.py`). Default selection in the system dropdown.

**`gt_system_v2_loadsweep`** — A screening variant of `gt_system_v2` that runs a 50–100 % GT-load sweep in the chart slot instead of the SVG flowsheet.

**Heat load** — In the GPU cassette, `q_W = IT + cassette_overhead`. Equals the GPU's total electrical draw (immersion physics: all electrical → heat). Drives the cooling demand.

**HRSG — Heat Recovery Steam Generator** — The block that converts GT exhaust heat into steam. Effectiveness `hrsg_eff_pct` typically 75–90 %. Generates steam at `T_sat(P_steam) + 30°C` superheat.

**Immersion cooling** — Single-phase dielectric-fluid immersion. The framework assumes 100 % of GPU electrical input dissipates as heat into the coolant — no part of the silicon's electrical input goes anywhere else. This is the basis for the cooling-balance demand equation.

**`InputSpec`** — One input field on an engine. `(key, label, unit, default, min, max, choices=None)`. When `choices` is provided, renders as a dropdown; otherwise a number input.

**Island mode** — Operating mode where the plant is autonomous. No grid backstop. GT must supply ALL demand. The `external_load_kW` input is honored; deficits are hard feasibility failures (not softened into "grid import").

**LiBr-priority** — The auto steam-split mode where the chiller takes exactly the steam it needs to cool the GPU, and MED gets the residual. Implemented in `control.py` by `libr_frac = min(steam_to_libr_needed / total_steam, 1.0)`.

**Manual mode** — The control mode where the user's numeric input (`load_pct` / `libr_frac`) is used directly. Opposite of auto.

**MED — Multi-Effect Distillation** — Thermal desalination block. **Steam balancer** — its water production is residual to what LiBr claims. When `libr_frac = 1.0` (high GPU + auto split), MED gets zero and produces zero water.

**Operating mode** — `operating_mode` input on the v2 GT engine. Values: `island` (default) / `grid_tied`. Drives whether external load is manual or auto-computed, and whether deficits are hard fails or softened.

**`OutputSpec`** — One row in the results table. `(label, value, unit, basis, fmt)`. The `basis` is the *engine-declared* one; the renderer may override it from audit coverage.

**P-checks (P1–P13)** — Plausibility audit checks: bounds on η, COP, GOR, recovery, PUE, derate, load_pct, etc., plus generic P12 (no-negative-flows) and P13 (finite kW values). 13 base + system-level F1–F5 (plausibility-category composition checks).

**Plant aux** — Auxiliary electrical loads modelled at screening fidelity: MED electrical (pumps), LiBr pump electrical, CT fan electrical, GT auxiliaries, Plant BoP. Itemised in the power balance breakdown.

**PUE — Power Usage Effectiveness** — Data centre metric. `PUE = (IT + overhead) / IT = 1 + aux_frac`. For immersion the v2 default is 1.05 (~5 % cassette overhead). The block's "PUE  (approx)" result row reflects this.

**Resource balance** — One supply / demand pair surfaced by feasibility. `ResourceBalance` carries resource name, unit, feasibility flag, supply, demand, balance, shortfall, breakdown (itemised contributors), assumption text, and screening tolerance.

**Screening tolerance** — A relative tolerance below which gaps are considered controller-vs-block precision noise rather than real engineering deficits. Cooling balance uses 2.5 %; M7 audit check uses 2.5 %.

**Sensitivity** — One-at-a-time central-difference perturbation around a base point. `OneAtATimeSensitivity` returns elasticities (% ΔKPI per % ΔInput) for ranking inputs. Multi-panel tornado in the UI shows one panel per selected KPI.

**`SolvedSystem`** — The output of `System.solve()`. Carries the wired system, the `ConvergenceStatus`, and (for the GT system) a stashed `.control` (`ControlSetpoints`) and `.operating_mode` attribute for downstream consumers.

**Steam balancer** — How MED is positioned in the new LiBr-priority control: not a designed primary product but a residual sink for whatever steam the chiller doesn't claim.

**`SteamSplitter`** — The block that distributes HRSG steam between LiBr and MED. `libr_frac` either user-set (manual) or controller-derived (auto). Always mass-conserves: `ṁ_in = ṁ_libr + ṁ_med`.

**Stream** — A process stream connecting two ports. Carries `mdot, T, P, h, x, power, props`. `StreamKind` ∈ {WATER_STEAM, ENERGY, ELECTRICAL, GENERIC_FLUID}.

**Study** — Sensitivity, sweep, or scenarios. Returns a `SensitivityResult` / `SweepResult` / `ScenarioResult`. Stored per-engine in-memory + on disk (pickled to `~/.enginetools/studies/`). Downloadable as standalone CSV / Excel; attachable to report exports.

**Sweep** — `ParameterSweep` walks a grid of input combinations and collects KPIs. 1D in UI is a single-X line chart (subplots, one per KPI); 2D is X × Y → KPI contour on a 5×5 grid.

**Sufficiency check** — An audit check that asserts supply ≥ demand without requiring strict equality. Used where mass-balance equality would be too strict for screening (M1 HRSG feedwater seed, M7 GPU coolant inlet flow).

**System** — `nexablock/core/system.py`. Composes blocks and connections into a graph; `solve(tol, max_iter)` returns a `SolvedSystem`.

**Tornado (sensitivity)** — Horizontal-bar chart of `|elasticity|` for one or more KPIs, ranked descending. Multi-panel tornado in the v2 UI shows one panel per selected KPI.

**Wegstein iteration** — The bounded-q recycle convergence acceleration the solver uses. `q ∈ [−5, 0]` per the standard sequential-modular reference.

**Wet bulb** — Site cooling-tower design ambient. `T_supply = T_wb + approach`. Audit check T5 enforces `T_supply > T_wb`.
