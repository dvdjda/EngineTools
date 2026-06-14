"""
Named input datasets ("defaults") for EngineTools.

A dataset is a saved snapshot of an engine's input values under a user-given
name. Persisted server-side on disk, one JSON file per engine, so datasets
survive app restarts and are shared by any browser hitting the app — the same
storage stance as the studies store (~/.enginetools/).

File layout:
    ~/.enginetools/defaults/<engine_key>.json
    { "<dataset name>": {"<input key>": <value>, ...}, ... }

The UI (app.py) exposes Save / Update / Delete / Load over these.
"""
from __future__ import annotations
import json
import os
import pathlib

_DIR = pathlib.Path(os.path.expanduser("~/.enginetools/defaults"))


def _file(engine_key: str) -> pathlib.Path:
    # engine keys are lowercase/underscore by contract; guard anyway so a stray
    # key can't escape the defaults directory.
    safe = "".join(c for c in str(engine_key) if c.isalnum() or c in ("_", "-"))
    return _DIR / f"{safe}.json"


def _read(engine_key: str) -> dict:
    f = _file(engine_key)
    if not f.exists():
        return {}
    try:
        data = json.loads(f.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write(engine_key: str, data: dict) -> None:
    _DIR.mkdir(parents=True, exist_ok=True)
    _file(engine_key).write_text(
        json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")


def list_datasets(engine_key: str) -> list[str]:
    """Sorted names of every dataset saved for this engine."""
    return sorted(_read(engine_key).keys())


def exists(engine_key: str, name: str) -> bool:
    return name in _read(engine_key)


def get_dataset(engine_key: str, name: str):
    """The {input_key: value} dict for a dataset, or None if it doesn't exist."""
    return _read(engine_key).get(name)


def save_dataset(engine_key: str, name: str, values: dict) -> None:
    """Create or overwrite a dataset (upsert). Used by both Save and Update."""
    data = _read(engine_key)
    data[str(name)] = dict(values)
    _write(engine_key, data)


def delete_dataset(engine_key: str, name: str) -> bool:
    """Remove a dataset. Returns True if it existed and was removed."""
    data = _read(engine_key)
    if name in data:
        del data[name]
        _write(engine_key, data)
        return True
    return False
