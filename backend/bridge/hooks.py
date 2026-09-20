"""Late-bound lookups into the sidecar entry module.

Method bodies live in ``bridge.*`` so they can be read in isolation, but tests
and Electron still patch symbols on the ``rpc_bridge`` module. Resolving those
names at call time keeps ``patch.object(rpc_bridge, ...)`` effective without a
circular import at module load.

The Electron sidecar executes ``python rpc_bridge.py``, which registers the
file as ``__main__``. ``rpc_bridge.py`` aliases that module as ``rpc_bridge``
before importing ``bridge``; this lookup still accepts ``__main__`` so a
missing alias cannot take the process down with ``AttributeError``.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any


def _entry_module() -> ModuleType:
    for name in ("rpc_bridge", "__main__"):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, "BACKEND_ROOT"):
            return module
    raise AttributeError("rpc_bridge entry module is not loaded")


def __getattr__(name: str) -> Any:
    try:
        return getattr(_entry_module(), name)
    except AttributeError:
        raise AttributeError(name) from None
