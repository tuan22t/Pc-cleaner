"""Operating-system specific code.

The rest of the app is shared. Each module here registers what it provides
(startup-item providers, junk categories) when it is loaded:

* ``windows`` – Windows 10/11
* ``macos``   – macOS (Intel and Apple chips)
* ``linux``   – development only
"""
from __future__ import annotations

import importlib

from .. import paths

_loaded = None


def name() -> str:
    return "windows" if paths.IS_WINDOWS else "macos" if paths.IS_MAC else "linux"


def load():
    """Import (once) and return the module for this operating system."""
    global _loaded
    if _loaded is None:
        _loaded = importlib.import_module(f"{__name__}.{name()}")
    return _loaded
