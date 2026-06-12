# EngineTools — Framework Architecture

Developer-facing reference: how the two packages compose, what contracts they expose, how to extend the framework with a new block or system.

For the user-facing simulator description, see [`NEXA_SIMULATOR.md`](NEXA_SIMULATOR.md). For terminology, see [`DICTIONARY.md`](DICTIONARY.md). For day-to-day app usage, see [`MANUAL.md`](MANUAL.md).

---

## 1. The two packages

```
EngineTools/
├── nexablock/           ← v2 framework. Physics, solver, audit, studies.
│   ├── core/            ← Block, System, Solver, Stream, Port, convergence.
│   ├── blocks/          ← The 7 GT-system blocks (+ Recycle).
│   ├── audit/           ← CheckResult, AuditStatus, audit(), helpers.
│   ├── studies/         ← Sweep, Sensitivity, Scenarios, charts.
│   ├── viz/             ← SVG flowsheet renderer (§7.5).
│   └── validation/      ← Reference + TestCase dataclasses.
├── simulators/          ← System compositions on top of nexablock blocks.
│   └── gt_system/       ← The GT + HRSG + LiBr + GPU + MED system.
│       ├── system.py    ← build_gt_system, summary, GTSystemParams.
│       ├── control.py   ← Controller (auto-mode setpoint resolution).
│       ├── feasibility.py ← Power + cooling resource balances.
│       └── audit.py     ← Composition-level audit checks (E9, F1–F5).
├── nexa_toolkit/        ← v1 UI host framework — Dash app + reports + drafts.
│   ├── framework/       ← Engine contract, InputSpec, OutputSpec, builder.
│   ├── engines/         ← Engine adapters (gt_system_v2, gpu_cassette, ...).
│   ├── reporting/       ← PDF, Excel, chart, study_export.
│   └── app/             ← The Dash UI (app.py).
└── tests/               ← 164 tests across the whole stack.
```

**Why two packages?** The v1 `nexa_toolkit` predates the v2 framework. It hosts the UI, the reporting layer, the drafts directory (where Cody scaffolds new tools), and the old standalone engines. The v2 `nexablock` is the "real" engineering framework — blocks, system composition, solver, audit. The v2 engines (`gt_system_v2`, `gt_system_v2_loadsweep`) live in `nexa_toolkit/engines/` and **adapt** the v2 framework to the v1 `Engine` contract so the v1 UI can drive it.

This is intentional layering, not legacy cruft: nexablock can be used standalone (import and run `build_gt_system(p)` from a script) without the Dash UI or any v1 framework imports.

---

## 2. The Block contract — `nexablock/core/block.py`

Every process unit is a subclass of `Block`. The framework only touches this interface:

```python
class Block(ABC):
    category: str = "Generic"        # SVG colouring
    label:    str = ""

    @abstractmethod def _build_params(self)  -> dict[str, Param]
    @abstractmethod def _build_inlets(self)  -> dict[str, Port]
    @abstractmethod def _build_outlets(self) -> dict[str, Port]
    @abstractmethod def compute(self)        -> None       # fills outlet streams + results

    # Optional:
    def references(self)       -> list[Reference]
    def test_cases(self)       -> list[TestCase]
    def render_ports(self)     -> dict[str, (rel_x, rel_y)]   # SVG anchors
    def audit_checks(self)     -> list[CheckResult]           # default []
```

Inside `compute()`:
- `self._in(port_name)` reads an inlet `Stream` (raises if a required port isn't connected).
- `self._out_set(port_name, stream)` writes an outlet.
- `self._p(param_name)` reads a parameter in SI.
- `self._result(label, value, unit, basis, ref)` records a result row. **Duplicate labels raise** — see `commit 525269a` for the historical bug and the hardening.

After `compute()`, the framework can call `block.audit_checks()` to harvest the block's contribution to the post-solve audit.

---

## 3. Streams, Ports, and the System graph

- **Stream** — `nexablock/core/stream.py`. Carries `mdot, T, P, h, x, power, props`. `StreamKind` ∈ {WATER_STEAM, ENERGY, ELECTRICAL, GENERIC_FLUID}.
- **Port** — `nexablock/core/port.py`. Inlet/outlet socket on a block. Knows its `StreamKind`, direction, required flag, and (after wiring) its connected `Stream`.
- **System** — `nexablock/core/system.py`. `add(block)` registers a block; `connect(src_port, dst_port)` records a directed edge; `solve(tol, max_iter)` returns a `SolvedSystem`.

The wiring is purely declarative — `System.solve()` figures out the order.

---

## 4. The solver — `nexablock/core/solver.py`

Sequential-modular with Wegstein recycle.

**Pipeline**:
1. Propagate edges: copy outlet streams onto downstream inlet ports.
2. Check required inlets — raise on disconnected required ports.
3. Tarjan SCC detects recycle loops.
4. If acyclic: topo-sort (Kahn), one forward pass — done.
5. If cyclic: choose one tear per SCC, seed it, Wegstein-iterate until `max_res < tol` or `max_iter` reached. **No raise on max-iter** — sets `convergence.converged = False` and runs a final forward pass anyway so KPIs exist.

**Idempotent re-compute**: each forward pass calls `block.results.clear()` before `block.compute()` so duplicate-label guards don't trip on iteration N+1.

**Per-loop convergence**: `ConvergenceStatus` carries one `LoopStatus` per SCC with name (block-class names joined by →), tear connection string, iterations used, final residual, tolerance, and reason on failure.

---

## 5. Audit framework — `nexablock/audit/`

```python
# Block-side: each block declares its checks inline
class HRSG(Block):
    def audit_checks(self) -> list[CheckResult]:
        return [
            energy_balance("E3: exhaust · η_hrsg = HRSG duty",
                supply=..., demand=..., affects=["Steam generation"], tol_rel=5e-3),
            mass_balance(...), pass_fail(...), bounds_check(...),
        ]

# Composition-side: simulators/gt_system/audit.py
def gt_system_audit_checks(solved, bop_frac=0.010) -> list[CheckResult]:
    return [
        energy_balance("E9: bus closure (island) ...", ...),
        pass_fail("F1: island balance closed without grid import", ...),
        # ...
    ]

# Engine-side: gt_system_v2.py
def solve(self, v):
    solved = build_gt_system(_params_from(v))
    return {
        "solved":      solved,
        "kpis":        summary(solved),
        "feasibility": feasibility(solved, bop_frac=params.bop_frac),
        "audit":       audit(solved,
                              extra_checks=gt_system_audit_checks(
                                  solved, bop_frac=params.bop_frac)),
    }
```

`audit(solved, extra_checks=[])` walks every block, appends extras, runs framework-generic safety nets (P12 no-negative-flows, P13 finite-kW), catches per-check exceptions defensively so one buggy check never silences the rest.

**Coverage lookup**:
```python
audit.coverage_for(kpi_label) -> "passed" | "failed" | "uncovered"
```
This drives the per-row basis in the results table — no more hardcoded "verified" strings.

---

## 6. The Engine adapter — adapting v2 to the v1 UI

The v1 `Engine` contract is at `nexa_toolkit/framework/contract.py`. Every UI element (input rendering, results table, chart slot, report generation) reads from this contract.

A v2-on-v1 adapter looks like:

```python
@register
class GTSystemV2(Engine):
    key          = "gt_system_v2"
    name         = "GT System v2 — nexablock (...)"
    status       = "trusted"
    chart_format = "svg"        # tells the UI to render the SVG flowsheet
    inputs       = [InputSpec(...), ...]    # 22 input fields

    def solve(self, v):                     # → r dict
        params = _params_from(v)
        solved = build_gt_system(params)
        return {"solved": solved, "kpis": summary(solved),
                "feasibility": feasibility(solved, ...),
                "audit":       audit(solved, ...)}

    def outputs(self, r):                   # → list[OutputSpec]
        # static rows + mode-derived rows + grid_export / external_load row
        return [...]

    def chart(self, r, path):               # → write SVG flowsheet
        with open(path, "w") as f: f.write(render_svg(r["solved"]))
        return path

    def study_hooks(self):                  # → studies plumbing
        return {"builder":      build_gt_system,
                "make_params":  _params_from,
                "kpi_fn":       summary,
                "kpis":         [...],
                "sensitivity_inputs": [...],
                "sweep_inputs": [...],
                "bounds":       {...},
                "step_override": {...},
                "scenarios":    {...}}
```

The UI doesn't need to know about `nexablock` at all — it just reads the v1 `Engine` shape. The `solve()` method is where v2 is hosted.

---

## 7. Studies — `nexablock/studies/`

Three primitives, framework-agnostic:

```python
ParameterSweep(builder, base_params, kpi_fn).run({input_name: values})
OneAtATimeSensitivity(builder, base_params, kpi_fn, rel_step, bounds, step_override).run(inputs, kpis)
ScenarioRunner(builder, base_params, kpi_fn).run({scenario_name: overrides, ...})
```

Each returns a structured result with `.as_dataframe()` (lazy pandas) and per-KPI/per-input accessors. The chart helpers in `charts.py` consume these results:

```python
tornado_chart(sens_result, path, kpi="...")
tornado_multi_chart(sens_result, path, kpis=[...])
sweep_chart(sweep_result, path, kpis=[...], subplots=True)
sweep_contour(sweep_result, path, kpi="...")    # requires len(varied)==2
scenarios_chart(scenario_result, path, kpis=[...])
```

These are pure functions of the result. The Dash UI calls them; the standalone study export (`study_to_csv` / `study_to_xlsx`) consumes the same results.

---

## 8. Reporting — `nexa_toolkit/reporting/generic_report.py`

`build_pdf(engine, values, result, path, chart_png, ai_text=None, study=None)` and `build_excel(engine, values, result, path, ai_text=None, study=None)` are the two entry points used by the UI download buttons.

The PDF layout is built with reportlab; the Excel layout with openpyxl. Both honour the basis colours from `_result_rows()` which read audit coverage. Both insert the **Convergence**, **Power balance**, **Cooling capacity balance**, and **Audit** sections in that order before the results table.

`write_study_sheet(wb, study)` is the **single source of truth** for the "Study" sheet whether it's attached to a full report (`build_excel(..., study=...)`) or sent standalone (`study_to_xlsx(study, path)`).

---

## 9. How to write a new Block

```python
from nexablock.core.block    import Block
from nexablock.core.port     import Port
from nexablock.core.stream   import Stream, StreamKind
from nexablock.core.quantity import Param
from nexablock.audit         import mass_balance, energy_balance, pass_fail, bounds_check

class MyBlock(Block):
    category = "Cooling"
    label    = "My Block"

    def __init__(self, x: float = 1.0, ...):
        super().__init__()
        self._x = x; ...

    def _build_params(self):
        return {"x": Param(self._x, "kW", min=0, max=100, desc="..."),
                ...}

    def _build_inlets(self):
        return {"feed": Port("feed", StreamKind.WATER_STEAM, "in")}

    def _build_outlets(self):
        return {"product": Port("product", StreamKind.WATER_STEAM, "out")}

    def compute(self):
        feed = self._in("feed")
        # physics here
        ...
        self._out_set("product", Stream.water_steam(mdot=..., T=..., P=..., h=...))
        self._result("My KPI", value, "kW", basis="verified", ref="...")

    def audit_checks(self):
        r = self.results
        return [
            energy_balance("MyE1: ...", supply=..., demand=...,
                affects=["My KPI"], tol_rel=5e-3),
            pass_fail("MyT1: ...", passed=..., detail="...",
                category="Second law", affects=["My KPI"]),
            bounds_check("MyP1: ...", value=..., lo=0, hi=1,
                affects=["My KPI"]),
        ]
```

Add to `nexablock/blocks/__init__.py`, wire into a system in `simulators/<your_system>/system.py`, expose via a `nexa_toolkit/engines/<your_system>_v2.py` adapter.

---

## 10. How to add a new resource balance

In `simulators/<your_system>/feasibility.py`:

```python
def steam_balance(solved, assumption: str = STEAM_ASSUMPTION) -> ResourceBalance:
    supply = ...    # e.g. HRSG steam generation
    demand = ...    # e.g. LiBr + MED demand
    return _make("Steam", "kg/s", supply, demand, assumption,
                  breakdown={"HRSG": supply, "LiBr": -..., "MED": -...},
                  tol_rel=0.01)
```

Append it to `feasibility(solved)`:
```python
return FeasibilityStatus(balances=[
    power_balance(solved, bop_frac=bop_frac),
    cooling_balance(solved),
    steam_balance(solved),       # ← new
])
```

The renderer iterates whatever's in `balances`, so it appears automatically as a new card in the UI and a new band in the PDF/Excel.

---

## 11. How to add a new audit check

Either as a block-level check in that block's `audit_checks()`:

```python
energy_balance("EX: my new energy closure",
    supply=..., demand=...,
    affects=["Engine output label"],
    tol_rel=5e-3),
```

Or as a composition-level check in `simulators/<system>/audit.py`:

```python
def my_system_audit_checks(solved) -> list:
    return [
        pass_fail("FX: my system-wide invariant",
            passed=..., detail="...",
            category="Plausibility", affects=["Engine output label"]),
        ...,
    ]
```

`affects` is a list of **engine-level output labels** (as shown in the results table). When a check fails, every KPI in this list gets `basis="unverified"`. Empty `affects` makes it a global check (P12/P13 style) that flags the whole system when failed.

---

## 12. Testing conventions

- `tests/test_core.py` — Block contract + units + props + recycle convergence + the duplicate-label guard.
- `tests/test_<block>.py` — Per-block physics + boundary cases.
- `tests/test_gt_system.py` — **The v2 promotion gate.** 14 reference KPIs cross-checked against the v1 trusted GT tool within ±2 %. Pinned to manual modes so the operating point is reproducible.
- `tests/test_audit.py` — Framework primitives + per-block audit invariants.
- `tests/test_feasibility.py` — Resource balances + tolerance behaviour.
- `tests/test_control.py` — Operating modes + auto/manual setpoint resolution.
- `tests/test_studies.py` — Sweep + sensitivity + scenarios + chart helpers.
- `tests/test_reports.py` — PDF/Excel render + study attachment + cell content.
- `tests/test_audit.py`, `tests/test_studies.py` — Updated for the screening-tolerance concept on cooling and M7.

Run all with `python -m pytest tests/ -q`. Current count: **164 / 164 green**. v2 promotion stays 14 / 14 ±2 % across every refactor.
