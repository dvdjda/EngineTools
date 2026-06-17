"""Tests for the named-input-dataset store (nexa_toolkit.framework.datasets).

The store persists Save/Update/Delete/Load datasets per engine to disk. These
tests redirect the store directory to a tmp path so the real ~/.enginetools is
never touched.
"""
import pytest

from nexa_toolkit.framework import datasets as D


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(D, "_DIR", tmp_path / "defaults")
    monkeypatch.setattr(D, "_DEFAULTS_DIR", tmp_path / "engine_defaults")
    yield


def test_empty_engine_lists_nothing():
    assert D.list_datasets("eng_a") == []
    assert D.get_dataset("eng_a", "missing") is None
    assert D.exists("eng_a", "missing") is False


def test_save_get_list():
    D.save_dataset("eng_a", "base", {"load_pct": 85, "mode": 0})
    D.save_dataset("eng_a", "peak", {"load_pct": 100})
    assert D.list_datasets("eng_a") == ["base", "peak"]   # sorted
    assert D.exists("eng_a", "base")
    assert D.get_dataset("eng_a", "base") == {"load_pct": 85, "mode": 0}


def test_save_is_upsert():
    D.save_dataset("eng_a", "base", {"load_pct": 85})
    D.save_dataset("eng_a", "base", {"load_pct": 42})   # overwrite (Update path)
    assert D.get_dataset("eng_a", "base") == {"load_pct": 42}
    assert D.list_datasets("eng_a") == ["base"]          # no duplicate name


def test_delete():
    D.save_dataset("eng_a", "base", {"x": 1})
    assert D.delete_dataset("eng_a", "base") is True
    assert D.list_datasets("eng_a") == []
    assert D.delete_dataset("eng_a", "base") is False     # already gone


def test_per_engine_isolation():
    D.save_dataset("eng_a", "shared", {"x": 1})
    D.save_dataset("eng_b", "shared", {"x": 2})
    assert D.get_dataset("eng_a", "shared") == {"x": 1}
    assert D.get_dataset("eng_b", "shared") == {"x": 2}
    D.delete_dataset("eng_a", "shared")
    assert D.list_datasets("eng_a") == []
    assert D.list_datasets("eng_b") == ["shared"]         # untouched


def test_persists_across_reads():
    D.save_dataset("eng_a", "base", {"load_pct": 85})
    # a fresh read (simulating a new process / app restart) sees it on disk
    assert D.get_dataset("eng_a", "base") == {"load_pct": 85}


def test_corrupt_file_is_tolerated():
    D.save_dataset("eng_a", "base", {"x": 1})
    D._file("eng_a").write_text("{ not json", encoding="utf-8")
    assert D.list_datasets("eng_a") == []                 # degrades to empty, no raise


def test_key_is_filename_safe():
    # a stray engine key can't escape the defaults directory
    D.save_dataset("../evil", "base", {"x": 1})
    written = list((D._DIR).glob("*.json"))
    assert len(written) == 1
    assert written[0].name == "evil.json"


# ── persistent per-engine DEFAULT parameters ─────────────────────────────────

def test_is_default_name_case_insensitive():
    assert D.is_default_name("Default")
    assert D.is_default_name(" default ")
    assert not D.is_default_name("my dataset")
    assert not D.is_default_name(None)


def test_default_params_set_and_get():
    assert D.get_default_params("eng_a") is None      # none yet
    D.set_default_params("eng_a", {"gpu_it_kW": 1234.0, "fw_t_C": 60.0})
    assert D.get_default_params("eng_a") == {"gpu_it_kW": 1234.0, "fw_t_C": 60.0}


def test_default_params_survive_dataset_delete():
    """The core requirement: deleting the 'Default' dataset must NOT clear the
    persisted default parameters."""
    vals = {"a": 1, "b": 2}
    D.save_dataset("eng_a", "Default", vals)
    D.set_default_params("eng_a", vals)
    D.delete_dataset("eng_a", "Default")
    assert D.list_datasets("eng_a") == []             # the dataset is gone
    assert D.get_default_params("eng_a") == vals      # but the default persists


def test_default_params_independent_per_engine():
    D.set_default_params("eng_a", {"x": 1})
    assert D.get_default_params("eng_a") == {"x": 1}
    assert D.get_default_params("eng_b") is None       # each GT simulator separate


def test_clear_default_params():
    D.set_default_params("eng_a", {"x": 1})
    assert D.clear_default_params("eng_a") is True
    assert D.get_default_params("eng_a") is None
    assert D.clear_default_params("eng_a") is False    # already gone
