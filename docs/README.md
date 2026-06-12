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

For the v2 trusted GT system, pick **"GT System v2 — nexablock"** in the system dropdown. Defaults already work: hit Run.

## The three status layers, summarised

Every Run shows three independent status cards above the chart:

- **Convergence** — green ✓ if the solver loops settled, red ⚠ NOT CONVERGED if they didn't. Acyclic systems read "converged (no recycle loops)".
- **Feasibility** — one card per resource balance (Power, Cooling capacity). Each is green ✓ when supply ≥ demand, red ⚠ DEFICIT otherwise.
- **Audit** — green ✓ N/N when every post-solve check (39 + composition extras = 44 in island/auto mode) passes, red ⚠ AUDIT FAILED otherwise with the list of failed checks.

Per-KPI basis (the colour of the Basis column in the Results table) is now data-driven from audit coverage: a KPI vouched for by a passing check shows the engine-declared basis (typically `verified`); a KPI named by any failed check goes `unverified` (red); a KPI no check covers goes `screening` (amber).

See [`MANUAL.md`](MANUAL.md) for the full walkthrough and [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md) for what each check measures.
