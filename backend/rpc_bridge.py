#!/usr/bin/env python3
"""Headless JSON-RPC bridge for the Electron desktop shell.

The copied here domain layer remains the source of truth. This module replaces
Qt queues/signals with newline-delimited JSON events over stdin/stdout.

``HereBackend`` method bodies live under ``bridge/``. This file keeps the
startup sequence, protocol I/O, dispatch table, and the names tests patch.
"""

from __future__ import annotations

import dataclasses
import json
import os
import re
import sys
import threading
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


RPC_STDOUT = sys.stdout
sys.stdout = sys.stderr

BACKEND_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HERE_PROJECT_ROOT", str(BACKEND_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from bridge.backend import HereBackend
from core.delivery.chat_platform_bridge import start_chat_platform_bridge, stop_chat_platform_bridge
from infrastructure.paths import get_app_paths
from services.asr.asr_adapter import (
    build_asr_setup_status,
    create_default_asr_adapter,
    missing_asr_requirements,
)
from services.asr.macos_microphone_permission import request_macos_microphone_permission
from services.storage_migration import migrate_storage_locations
from services.t2i.t2i_manager import T2IAdapterFactory
from services.tts.tts_manager import TTSAdapterFactory

_write_lock = threading.Lock()


def emit(message: dict[str, Any]) -> None:
    with _write_lock:
        RPC_STDOUT.write(json.dumps(message, ensure_ascii=False, default=str) + "\n")
        RPC_STDOUT.flush()


def event(name: str, payload: Any = None) -> None:
    emit({"type": "event", "event": name, "payload": payload})


def result(request_id: str, payload: Any = None) -> None:
    emit({"type": "response", "id": request_id, "ok": True, "result": payload})


def failure(request_id: str, exc: BaseException) -> None:
    emit({
        "type": "response",
        "id": request_id,
        "ok": False,
        "error": {"message": str(exc), "kind": type(exc).__name__},
    })


def model_json(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json")
    if isinstance(value, dict):
        return {key: model_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [model_json(item) for item in value]
    if dataclasses.is_dataclass(value):
        return model_json(dataclasses.asdict(value))
    if isinstance(value, Path):
        return value.as_posix()
    return value


def adapter_schemas() -> dict[str, Any]:
    def schemas(adapters: dict[str, type]) -> dict[str, Any]:
        return {
            name: model_json(getattr(adapter, "get_config_schema", lambda: {})())
            for name, adapter in adapters.items()
        }

    from services.asr.asr_manager import ASRAdapterFactory

    return {
        "tts": schemas(TTSAdapterFactory._adapters),
        "asr": schemas(ASRAdapterFactory._adapters),
        "t2i": schemas(T2IAdapterFactory._adapters),
    }


_THEME_FORBIDDEN_DECLARATION = re.compile(
    r"(?i)^\s*(width|height|min-width|max-width|min-height|max-height|"
    r"min-size|max-size|position|left|right|top|bottom|font-size)\s*:"
)


def _sanitize_theme_qss(fragment: Any) -> str:
    """Keep only harmless declaration fragments from the legacy QSS theme."""
    if not isinstance(fragment, str):
        return ""
    kept: list[str] = []
    for raw in fragment.split(";"):
        item = raw.strip()
        if item and not _THEME_FORBIDDEN_DECLARATION.match(item):
            kept.append(item)
    return "; ".join(kept) + (";" if kept else "")


def chat_ui_theme_snapshot(system_chat_ui_theme_path: str = "") -> dict[str, Any]:
    """Read the legacy chat_ui_theme.json layout subset for the Electron shell.

    QSS itself is deliberately not applied to the DOM. Returning sanitized
    fragments keeps the state useful for future component-level mapping while
    preventing layout-changing declarations from crossing the RPC boundary.
    """
    raw_path = str(system_chat_ui_theme_path or "").strip()
    path = Path(raw_path).expanduser() if raw_path else get_app_paths().config_dir / "chat_ui_theme.json"
    if not path.is_absolute():
        path = BACKEND_ROOT / path
    defaults: dict[str, Any] = {
        "path": path.as_posix(),
        "loaded": False,
        "dialog_offset_y": 0,
        "dialog_width_pct": 80,
        "dialog_padding": 40,
        "options_gap": 10,
        "extras": {},
    }
    if not path.is_file():
        return defaults
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return defaults
    if not isinstance(raw, dict):
        return defaults

    def bounded_int(key: str, fallback: int, low: int, high: int) -> int:
        try:
            value = int(raw.get(key, fallback))
        except (TypeError, ValueError):
            return fallback
        return max(low, min(high, value))

    extras: dict[str, str] = {}
    for key in (
        "numeric_label",
        "dialog_label",
        "input_bar",
        "busy_bar_label",
        "option_row",
        "options_container",
        "send_button",
        "microphone_button",
    ):
        block = raw.get(key)
        if not isinstance(block, dict):
            continue
        for fragment_key in ("extra_qss", "hover_extra_qss"):
            fragment = _sanitize_theme_qss(block.get(fragment_key))
            if fragment:
                extras[f"{key}.{fragment_key}"] = fragment

    return {
        **defaults,
        "loaded": True,
        "dialog_offset_y": bounded_int("dialog_offset_y", 0, -500, 500),
        "dialog_width_pct": bounded_int("dialog_width_pct", 80, 30, 100),
        "dialog_padding": bounded_int("dialog_padding", 40, 0, 120),
        "options_gap": bounded_int("options_gap", 10, 0, 60),
        "extras": extras,
    }


def rpc_methods(backend: HereBackend) -> dict[str, Any]:
    return {
        "ping": lambda _: {"ok": True, "version": backend.config.version},
        "get_state": lambda _: backend.state(),
        "save_config": backend.save_config,
        "set_active_character": lambda p: backend.set_active_character(str(p.get("name") or "")),
        "chat": backend.chat,
        "observe_screen": backend.observe_screen,
        "stop_chat": lambda _: backend.stop_chat(),
        "clear_history": lambda _: backend.clear_history(),
        "revert_history": backend.revert_history,
        "update_memory": backend.update_memory,
        "create_character": backend.create_character,
        "upload_character_sprites": backend.upload_character_sprites,
        "import_character_state_assets": backend.import_character_state_assets,
        "delete_character_sprite": backend.delete_character_sprite,
        "delete_character": backend.delete_character,
        "generate_image": backend.generate_image,
        "generate_realtime_sprite": backend.generate_realtime_sprite,
        "start_asr": backend.start_asr,
        "stop_asr": lambda _: backend.stop_asr(),
        "pause_asr": lambda _: backend.pause_asr(),
        "resume_asr": lambda _: backend.resume_asr(),
        "codex_pet_candidates": lambda _: backend.codex_pet_candidates(),
        "import_codex_pet": backend.import_codex_pet,
        "wechat_login_start": backend.wechat_login_start,
        "wechat_login_poll": backend.wechat_login_poll,
        "wechat_status": lambda _: backend.wechat_status(),
        "telegram_discover": backend.telegram_discover,
        "list_models": backend.list_models,
        "dependency_status": backend.dependency_status,
        "install_dependencies": backend.install_dependencies,
        "prepare_asr": backend.prepare_asr,
        "save_messaging": backend.save_messaging,
        "save_storage": backend.save_storage,
        "import_legacy": backend.import_legacy,
        "resolve_assets": backend.resolve_assets,
    }


RPC_METHOD_NAMES = frozenset((
    "ping",
    "get_state",
    "save_config",
    "set_active_character",
    "chat",
    "observe_screen",
    "stop_chat",
    "clear_history",
    "revert_history",
    "update_memory",
    "create_character",
    "upload_character_sprites",
    "import_character_state_assets",
    "delete_character_sprite",
    "delete_character",
    "generate_image",
    "generate_realtime_sprite",
    "start_asr",
    "stop_asr",
    "pause_asr",
    "resume_asr",
    "codex_pet_candidates",
    "import_codex_pet",
    "wechat_login_start",
    "wechat_login_poll",
    "wechat_status",
    "telegram_discover",
    "list_models",
    "dependency_status",
    "install_dependencies",
    "prepare_asr",
    "save_messaging",
    "save_storage",
    "import_legacy",
    "resolve_assets",
))


def dispatch(backend: HereBackend, method: str, params: dict[str, Any]) -> Any:
    methods = rpc_methods(backend)
    if method not in methods:
        raise KeyError(f"未知 RPC 方法：{method}")
    return methods[method](params)


def main() -> int:
    try:
        backend = HereBackend()
    except Exception as exc:
        traceback.print_exc()
        event("fatal", {"message": str(exc), "kind": type(exc).__name__})
        return 1
    event("ready", backend.state())
    executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="here-rpc")

    def run(request_id: str, method: str, params: dict[str, Any]) -> None:
        try:
            result(request_id, dispatch(backend, method, params))
        except Exception as exc:
            traceback.print_exc()
            failure(request_id, exc)

    try:
        for raw_line in sys.stdin:
            try:
                request = json.loads(raw_line)
                request_id = str(request.get("id") or uuid.uuid4().hex)
                method = str(request.get("method") or "")
                params = request.get("params") if isinstance(request.get("params"), dict) else {}
                executor.submit(run, request_id, method, params)
            except Exception as exc:
                traceback.print_exc()
                event("protocol_error", {"message": str(exc)})
    except KeyboardInterrupt:
        pass
    finally:
        backend.shutdown()
        executor.shutdown(wait=False, cancel_futures=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
