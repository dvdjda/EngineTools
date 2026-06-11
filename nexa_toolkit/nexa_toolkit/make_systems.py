"""Run every registered system through the one generic reporting layer."""
import nexa_toolkit.engines  # noqa: F401  (registers the systems)
from nexa_toolkit.framework import REGISTRY, list_engines
from nexa_toolkit.reporting.generic_report import build_all

OUT = "/home/claude/systems"

print("Registered systems:")
for key, name in list_engines():
    print(f"  - {key}: {name}")

# run each on its defaults (swap in real values per system)
for key, engine in REGISTRY.items():
    values = engine.defaults()
    r = build_all(engine, values, OUT, slug=key)
    print(f"\n{engine.name}")
    for o in engine.outputs(r):
        print(f"  {o.label:32s} {o.text():>10s} {o.unit:8s} [{o.basis}]")

print("\nreports written to", OUT)
