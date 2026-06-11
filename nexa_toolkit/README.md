# Nexa process toolkit

A framework, not an app. New systems (desalination, gas turbine, whole plant, ...)
drop in as engine modules on one common contract. Reporting, UI and the MCP/agent
exposure are all generic and read that contract, so adding a system is a module,
not a rebuild. Runs locally (light numerical work, no GPU); heavy LLM reasoning
stays in the cloud.

## Structure
```
nexa_toolkit/
  framework/
    contract.py        InputSpec / OutputSpec / Engine base / REGISTRY
  engines/
    libr_chiller_engine.py   system 1 - LiBr absorption chiller (cycle)
    gpu_cassette.py          system 2 - immersed-GPU cassette (load/flow balance)
    __init__.py              importing registers the systems
  engine/
    libr_chiller.py    raw LiBr physics (CoolProp + ASHRAE/Herold-Klein)
  reporting/
    generic_report.py  chart/Excel/PDF/PPTX for ANY engine via the contract
    charts.py          shared chart helpers + LiBr signature chart
make_systems.py        demo: register systems, report each through one layer
```

## Add a system
Implement the contract: set key/name/notes/inputs, write solve(values)->dict and
outputs(result)->[OutputSpec] (each output carries a basis: verified|screening|input),
optionally highlights() and a signature chart(). Register with @register. Done -
reporting, UI and MCP pick it up automatically.

## Run
```
pip install CoolProp scipy matplotlib reportlab openpyxl python-pptx cairosvg
python make_systems.py        # reports for every registered system -> ./systems
```

## Governance (safe + controllable)
- Every output declares its basis (verified / screening / input); reports show it.
- Numbers come only from engines, never invented. An agent composes around them.
- New models: draft -> run sandboxed, marked screening -> verify -> promote to trusted.
- ChemCAD is the system of record for certifiable numbers.

## Next
- Generic UI (Dash): auto-renders inputs + results from the registry, report downloads.
- MCP server: each engine exposed as a tool/skill so OpenClaw/Cody calls it (no host shell).
- More systems: desalination absorption, gas turbine generator, whole-plant simulator.
