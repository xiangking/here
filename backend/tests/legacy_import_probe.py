"""Subprocess probe for legacy import storage relocation (Issue #15).

Run with ``HERE_APP_HOME`` pointing at an empty app home and ``PROBE_LEGACY``
pointing at a legacy source tree. It imports the legacy data and then writes a
fresh memory entry, so the parent test can confirm where the write landed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))


def main() -> None:
    import rpc_bridge

    backend = rpc_bridge.HereBackend()
    try:
        backend.import_legacy({"source_path": os.environ["PROBE_LEGACY"]})
        active = backend.config.resolve_active_character_name()
        backend.update_memory({
            "character_name": active,
            "kind": "character",
            "entries": ["electron-only-memory"],
        })
        print(f"PROBE_ACTIVE={active}", file=rpc_bridge.RPC_STDOUT)
    finally:
        backend.shutdown()


if __name__ == "__main__":
    main()
