# importing each engine registers it
from . import libr_chiller_engine
from . import gpu_cassette
from . import gt_system_v2
from . import gt_system_v2_loadsweep

# auto-load every module in engines/drafts/ so drafts survive app restarts
import importlib
import os
import pkgutil

_drafts_dir = os.path.join(os.path.dirname(__file__), "drafts")
if os.path.isdir(_drafts_dir):
    for _mod_info in pkgutil.iter_modules([_drafts_dir]):
        try:
            importlib.import_module(f"nexa_toolkit.engines.drafts.{_mod_info.name}")
        except Exception as _e:
            import warnings
            warnings.warn(f"EngineTools: could not load draft '{_mod_info.name}': {_e}")
