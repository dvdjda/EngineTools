# EngineTools Documentation

EngineTools is the build framework and simulator host for the NEXA process toolkit. It runs a Dash UI in the browser, drives the `nexablock` v2 framework underneath, and produces self-describing PDF / Excel / CSV reports with explicit convergence, feasibility, and audit status.

## What's in this folder

| File | Audience | What it covers |
|---|---|---|
| [`MANUAL.md`](MANUAL.md) | App user (process engineer, plant designer) | How to start the app, every UI element, the standard workflow, how to read the status cards, how to drive sensitivity / sweep / scenarios, how to read PDF / Excel / CSV exports. |
| [`DICTIONARY.md`](DICTIONARY.md) | Anyone | Every term used across the codebase, in alphabetical order: framework concepts (Block, System, Engine, basis), the mode names, the resource balances, the audit categories, each result-row label. |
| [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) | App user + developer | The full shape of the v2 GT system: every block with its ports, params, physics, and audit checks; the system wiring; the control logic for the auto modes; the order in which convergence → feasibility → audit run after each solve; how the data flows into the report. |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Developer extending the framework | The two-package layering (`nexablock/` v2 core, `nexa_toolkit/` v1 UI host), the `Block` contract, the solver, the studies layer, the audit framework, how to write a new block, how to add a new resource balance, how to write a new audit check. |

## Quick start

```bash
# from the repo root
./start.sh                                # starts the Dash app on port 8050
open http://127.0.0.1:8050/               # the EngineTools UI
./stop.sh                                 # stops it
./restart.sh                              # stop + start
```

Pick a system in the dropdown — e.g. **"GT System v2 — nexablock (… + Backup)"** (the currently trusted GT variant) or the **"LiBr-H₂O absorption chiller"** (single/double-effect, calibrated to the BROAD XII Non-Electric Chiller OEM datasheet). Defaults already work: hit Run.

> **Tool status (current).** The only `trusted` GT engine is the **… + Backup** variant. The base **GT System v2**, its **double-effect (2×LiBr)** and **load-sweep** variants, and the **GPU cassette** are presently `draft` (pending re-verification); the **LiBr-H₂O absorption chiller** is `draft`. Draft tools run fully — they just carry a draft badge and `unverified` / `screening` bases until David promotes them.

## The three status layers, summarised

Every Run shows three independent status cards above the chart:

- **Convergence** — green ✓ if the solver loops settled, red ⚠ NOT CONVERGED if they didn't. The GT system has one real recycle loop (the GPU↔LiBr dielectric coolant loop), torn and Wegstein-converged; the card reads "converged in N iterations".
- **Feasibility** — one card per resource balance (Power, Cooling capacity). Each is green ✓ when supply ≥ demand within tolerance, red ⚠ DEFICIT otherwise.
- **Audit** — green ✓ N/N when every post-solve check (42 in island/auto or grid/auto mode, 41 fully-manual) passes, red ⚠ AUDIT FAILED otherwise with the list of failed checks.

Per-KPI basis (the colour of the Basis column in the Results table) is now data-driven from audit coverage: a KPI vouched for by a passing check shows the engine-declared basis (typically `verified`); a KPI named by any failed check goes `unverified` (red); a KPI no check covers goes `screening` (amber).

See [`MANUAL.md`](MANUAL.md) for the full walkthrough and [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) for what each check measures.
