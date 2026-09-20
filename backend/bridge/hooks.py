"""Late-bound lookups into ``rpc_bridge``.

Method bodies live in ``bridge.*`` so they can be read in isolation, but tests
and Electron still patch symbols on the ``rpc_bridge`` module. Resolving those
names at call time keeps ``patch.object(rpc_bridge, ...)`` effective without a
circular import at module load.
"""

from __future__ import annotations

import sys
from typing import Any


def __getattr__(name: str) -> Any:
    module = sys.modules.get("rpc_bridge")
    if module is None:
        raise AttributeError(name)
    try:
        return getattr(module, name)
    except AttributeError:
        raise AttributeError(name) from None
