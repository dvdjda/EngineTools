# EngineTools — App User Manual

## 1. Starting and stopping

```bash
./start.sh             # starts the Dash app in the background, writes PID
./stop.sh              # stops the running app
./restart.sh           # combination of the two
tail -f enginetools.log  # if it doesn't come up, the log is here
```

The app binds to `http://127.0.0.1:8050/`. Defaults to Anaconda Python (`/opt/anaconda3/bin/python3`) and requires `dash`, `CoolProp`, `scipy`, `matplotlib`, `reportlab`, `openpyxl`, `python-pptx`, `cairosvg`, and `pandas`. See the project root `nexa_toolkit/README.md` for the install line.

### 1.1 Auto-start on login (macOS LaunchAgent)

On this Mac the app auto-starts at login via a user LaunchAgent, `com.nexa.enginetools`, at `~/Library/LaunchAgents/com.nexa.enginetools.plist`. It runs `run.sh` from this repo (`/Users/dvdj/EngineTools`) and logs to `/tmp/enginetools.log`.

`run.sh` is the launcher and serves both contexts: run from a terminal it **self-detaches** into the background; when the LaunchAgent runs it (with `_ET_BG=1` set in the plist) it runs the app in the **foreground** so `launchd` can supervise it (`KeepAlive` restarts it if it exits, `RunAtLoad` starts it at login).

Control the service with `launchctl` (`U=$(id -u)`):

```bash
launchctl kickstart -k gui/$U/com.nexa.enginetools                       # restart now
launchctl bootout   gui/$U/com.nexa.enginetools                          # stop now
launchctl bootstrap gui/$U ~/Library/LaunchAgents/com.nexa.enginetools.plist  # start now
```

To disable auto-start entirely, `bootout` it and move the plist out of `~/Library/LaunchAgents/`. The repo's `./start.sh` / `./stop.sh` remain available for manual control independent of the LaunchAgent (just don't run both at once — they share port 8050).

## 2. The UI layout, top to bottom

When you load the page, the layout is two columns:

**Left column** — inputs panel:
- **System dropdown** at the top. Pick which engine to run. Defaults to the v2 trusted GT system.
- **Datasets panel** below the dropdown. Save / Update / Load / Delete named snapshots of all the current inputs, per engine. See §6.
- **Input list** below. Auto-generated from the picked engine's `InputSpec` list. Plain inputs are numeric boxes; categorical inputs (like the mode switches) are dropdowns. For the GT engines a **GT load (kW)** field sits directly under **GT load (%)**, twinned to it (see §3.1).
- **Run button** at the bottom of the panel.

**Right column** — results pane (everything updates on Run):
- **Status bar** — green tick + engine name when calculation succeeded.
- **Banner area** — a draft-tool notice (if any) plus status messages from clicks elsewhere.
- **Convergence card** — green ✓ / red ⚠ depending on solver convergence (see §4.1).
- **Feasibility cards** — one per resource balance (Power, Cooling capacity). Each is green or red (§4.2).
- **Audit card** — green ✓ N/N or red ⚠ AUDIT FAILED with a list of failed checks (§4.3).
- **Highlight cards** — three big KPI cards (engine-declared highlights).
- **Chart slot** — shows the engine's native chart (the v2 GT system shows the §7.5 SVG flowsheet; the load-sweep adapter shows a sweep line chart). Studies clicks overwrite this slot temporarily.
- **Studies card** — Sensitivity, Sweep (1D/2D), Scenarios. See §5.
- **Results table** — full output list with Quantity / Value / Unit / Basis columns. Basis colour reflects audit coverage (§4.4).
- **Smart section** — diagnostics + method notes from the engine.
- **AI Analysis area** — optional LLM-generated narrative (depends on configured model).
- **Download row** — Download PDF, Download Excel, plus "Include latest study" checkbox to attach the most recent study chart to the export.

## 3. The standard workflow

1. **Pick an engine** in the system dropdown.
2. **Adjust inputs** in the left column as needed. For the v2 GT system, the modes at the bottom (Operating mode, GT power control) decide how the controller behaves — see [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) §4.
3. **Click Run**. The right pane populates with status cards, the flowsheet, the highlights, and the full results table.
4. **Read the three status cards** to know whether the result is trustworthy:
   - Convergence card must be green.
   - Every Feasibility card must be green (Power AND Cooling capacity for the v2 GT system).
   - Audit card must be green (42 checks total in island/auto or grid/auto mode; 41 in fully-manual GT-power mode).
5. **Drive a study** if you want to learn the system's dynamics — sensitivity (multi-select inputs and KPIs), sweep (1D or 2D), or scenarios. See §5.
6. **Download a report** (PDF / Excel) when you have something to share. Tick "Include latest study" to attach the most recent study chart to the report.

### 3.1 The GT load %↔kW twin (GT engines)

The two GT engines (`gt_system_v2`, `gt_system_v2_loadsweep`) show a **GT load (kW)** field directly under **GT load (%)**. The two are linked both ways:

- Edit **%** → the kW field updates.
- Edit **kW** → the % field updates.
- Edit **GT rated power** or **Ambient temperature** → the kW re-derives at the held %.

The conversion is on the **actual-power (derated) basis**: `kW = derated capacity × load% ÷ 100`, where the derate is `max(0.50, 1 − 0.007·max(0, T_amb − 15 °C))` (see [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) §3.1). So the kW shown equals the **GT actual power** the engine reports when GT power control is **Manual**. If you type a kW that implies a load outside the 10–100 % envelope, the % clamps and the kW snaps back to the consistent value.

Note: in **Auto** GT power mode the controller derives `load_pct` itself, so both the % input and this kW twin are inert at solve time (the actual operating point appears in the results as `GT load_pct (auto-derived)`).

### 3.2 The plant-electrical and cooling-loop inputs (GT system)

The v2 GT system input list (auto-generated from the engine's `InputSpec`s) includes:

- **Dielectric coolant** fields — **GPU coolant T_in / T_out** (default 30°C → 42°C), **Dielectric coolant cp** (2100 J/kg·K) and **density** (780 kg/m³). This is the immersion fluid, not chilled water.
- **LiBr rejection temperature** (`libr_reject_t_C`, default 95°C) and **HRSG feedwater / loop return set-point** (`fw_t_C`, default 80°C) — the hot and cold ends of the cooling-water loop.
- **MED bypass (manual, 0–1)** — the 3-way valve fraction routing rejection heat around MED. **Radiator approach to ambient** (default 15 K) — the dry-cooler cold-branch approach.
- **Plant-electrical (aux) model** — itemised, IT/flow-driven: **GT aux fraction** (internal derate → GT net), **Pump efficiency** (all pumps), the pump heads **Dielectric coolant loop head**, **Cooling-water loop head**, **HRSG feed-water pump head**, **Seawater / MED pump head** (one knob drives all the ~2-bar desal/condensate pumps), the **Dry-cooler fan at full duty** fraction (VSD cube law), and the container-envelope HVAC set **40' containers per MW IT**, **Container external area**, **Envelope U-value**, **Container inside set-point**, **Lights (fraction of HVAC)**.

## 4. Reading the status cards

### 4.1 Convergence card

Lives directly above the chart slot.

| Reading | Meaning |
|---|---|
| ✓ Converged · "converged (no recycle loops)" | Acyclic system — no Wegstein iteration was needed. |
| ✓ Converged · "converged in N iterations, residual X < tol Y" | Recycle loops settled within tolerance. |
| ⚠ NOT CONVERGED | The Wegstein iteration didn't reach tolerance within `max_iter`. The loop is named; the residual and tolerance are shown. KPIs below are flagged red. |

When this is red, the KPIs in the results table represent the LAST iteration values, not a converged solution. The framework now reports this honestly instead of raising.

### 4.2 Feasibility cards — one per resource balance

The v2 GT system carries two resource balances:

| Resource | Supply | Demand | When it goes red |
|---|---|---|---|
| **Power** | **GT net power** (gross − GT aux; GT aux is an internal derate, so the bus sees net) | GPU silicon + cassette overhead + itemised plant aux + (island) external load OR (grid) grid export | The bus doesn't close within 2.5 %: a deficit, or (island) a surplus with nowhere to go, or (grid mode) export-only would have to import. |
| **Cooling capacity** | LiBr Q_cool | GPU silicon heat + cassette overhead heat | LiBr undersized for the GPU heat dump (gap beyond the 2.5 % screening tolerance). |

Each card shows:
- Supply · Demand · Balance · (when red) shortfall
- An "Assumption:" line stating the modelling stance (e.g. "GT-powered: ... no external grid import." for island; "Grid-tied: ... export-only" for grid).
- The breakdown is on the PDF/Excel report, not on the UI card.

### 4.3 Audit card

The post-solve audit runs 42 checks in island/auto and grid/auto mode (41 in fully-manual GT-power mode — the F3 derived-load_pct check only exists in auto). When everything passes you get a single green line; when something fails, a red block lists every failed check with category, name, and detail.

Categories: **Energy closure**, **Mass closure**, **Second law**, **Plausibility**. See [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) §6 for the full check list.

### 4.4 Per-KPI basis colours (Results table)

The Basis column for each row is data-driven from audit coverage:

| Basis | Colour | Meaning |
|---|---|---|
| `verified` | green | At least one audit check vouches for this KPI label, and every check covering it passed. |
| `unverified` | red | An audit check naming this KPI failed, OR the convergence/feasibility cards globally invalidated everything. |
| `screening` | amber | No audit check named this KPI. The number is reported but not asserted. |
| `input` | grey | This row reflects a user input, not a computed result. |

Hardcoded "verified" strings are gone. A KPI gets "verified" only if it's empirically earned, run by run.

## 5. Studies — driving the system to learn its dynamics

The Studies card sits between the chart slot and the results table. Three button rows + a download row.

### 5.1 Sensitivity

Two multi-select dropdowns: **Inputs to perturb** and **KPIs to analyse**. Run. The chart slot shows a multi-panel tornado — one panel per selected KPI, each ranked by |elasticity|, zero-elasticity bars suppressed (so a KPI structurally decoupled from most inputs doesn't read as "broken").

Elasticity reads as: % change in this KPI per % change in this input. ±1.0 means linear; ±2.0 means quadratic in this region; 0.0 means decoupled.

Defaults: both dropdowns pre-select everything in the engine's `sensitivity_inputs` and `kpis` lists.

### 5.2 Sweep — 1D / 2D toggle

Pick **1D** or **2D** with the radio at the top of the row.

**1D mode**:
- One **X axis** dropdown (which input to vary).
- One **KPIs to plot** multi-select (which outputs to track).
- The X dropdown shows the curated `sweep_inputs` list (`load_pct`, `gt_eff`, `libr_cop`, `libr_reject_t_C`, `hrsg_eff_pct`, `med_bypass_frac`, `t_ambient_C`, `gpu_it_kW`, `external_load_kW`).
- Chart: stacked subplots, one per KPI, sharing the X axis. Each KPI gets its own y-scale so small-magnitude lines (steam t/h next to GT kW) stay visible.

**2D mode**:
- **X** and **Y** dropdowns. They must be different inputs.
- A single **KPI** (the first selected) becomes the contour z-axis.
- The sweep is a 5×5 grid. The chart is a `contourf` with labelled contour lines and a colorbar.

### 5.3 Scenarios

One button. Runs the engine-declared scenarios (summer peak, winter low load) and renders a comparison bar chart in the chart slot, normalised to base.

### 5.4 Latest-study download

Each study run gets stashed per-engine (in-memory dict + disk pickle under `~/.enginetools/studies/`). Two buttons at the bottom of the Studies card:

- **Download Study CSV** — `# `-prefixed metadata header (kind, engine, timestamp, base_params as JSON) + the `as_dataframe()` body.
- **Download Study Excel** — two sheets: **Metadata** (kind / engine / timestamp / one row per base_params field) and **Study** (chart + table — same sheet that `build_excel` attaches to a full report).

The "Latest study: ..." status line shows what's currently loaded.

## 6. Input datasets — Save / Load / Update / Delete

The **Datasets** panel in the left column (between the System dropdown and the input list) saves and restores named snapshots of **all** the current engine's inputs. Datasets are stored **per engine** on disk under `~/.enginetools/defaults/<engine_key>.json`, so they persist across app restarts and only appear for the engine they belong to.

The panel has a **dataset dropdown**, a **name** text box, and four buttons:

| Button | What it does |
|---|---|
| **💾 Save** | Writes the current inputs as a new dataset under the name typed in the box (overwrites if that name already exists), then selects it in the dropdown. |
| **↻ Update** | Overwrites the dataset currently selected in the dropdown with the current inputs. |
| **📂 Load** | Pushes the selected dataset back into every input field, including the mode dropdowns. |
| **🗑 Delete** | Removes the selected dataset. |

A status line under the buttons confirms each action (e.g. "Saved dataset 'summer peak'.") or prompts you (e.g. "Select a dataset first, then Update.").

Notes:
- The dropdown repopulates when you switch engines, so you only ever see datasets for the engine in front of you.
- The **GT load (kW)** twin (§3.1) is a view of `load_pct`, not an input, so it isn't stored — but `load_pct` is, and the kW field re-derives automatically on Load.
- A dataset saved before a new input existed still loads fine; any input the dataset doesn't name simply keeps its current value.

## 7. Downloads

| Format | What's in it |
|---|---|
| **PDF** | Title · design point table · convergence / power balance / cooling balance / audit sections · chart (flowsheet or sweep depending on engine) · results table (with basis colours — including the single **Plant PUE** KPI) · method note · AI analysis (if any). Tick "Include latest study" to append the most recent study chart. For the GT-system engines a final **landscape PFD page** is appended — the process flow diagram with every value live from the run, an island/grid badge, the named operating modes, and a mode-aware external-load / grid-export cell. |
| **Excel** | Sizing sheet (engine name + design point + convergence band + every resource balance + audit band + results table). With "Include latest study" ticked, an extra **Study** sheet carries the chart + the underlying table. |

Both honour the basis colours from the Results table. Both fail loud — neither will silently emit a "verified" basis when audit/feasibility/convergence haven't actually run and passed.

## 8. Troubleshooting

- **Port 8050 already in use** → `./stop.sh` first; check `enginetools.pid` for a stale PID file.
- **"This engine doesn't expose study_hooks"** in the banner → the picked engine is a v1 entry without the v2 hook. Switch to the v2 GT entry.
- **Audit shows M7 failure (and a red Cooling card) at island/auto defaults** → expected. Island mode caps GT load by electrical demand; at the GPU-5-MW defaults the electrically-pinned GT raises only enough steam for ~5 072 kW of LiBr cooling against a 5 250 kW demand (~3.4 % short, beyond the 2.5 % screening tolerance), so M7 (coolant inlet supply ≥ cassette demand) fails and 41/42 checks pass. Either raise external load, switch to grid mode (which ramps the GT for full cooling and is clean), or pick manual GT-power with a higher `load_pct`.
- **PDF builds slowly** → cairosvg rasterises the SVG flowsheet at 1600 px wide. Acceptable for screening; future speed-up is on the list.
- **Inputs row reads "Operating mode  (-)"** → already fixed. If you see this again, the dimensionless-unit suppression in `input_fields` regressed.
