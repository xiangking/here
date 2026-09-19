#!/usr/bin/env python3
"""Headless JSON-RPC bridge for the Electron desktop shell.

The copied here domain layer remains the source of truth. This module replaces
Qt queues/signals with newline-delimited JSON events over stdin/stdout.
"""

from __future__ import annotations

import base64
import hashlib
import dataclasses
import importlib
import json
import io
import mimetypes
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import traceback
import urllib.request
import uuid
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any


RPC_STDOUT = sys.stdout
sys.stdout = sys.stderr

BACKEND_ROOT = Path(__file__).resolve().parent
os.environ.setdefault("HERE_PROJECT_ROOT", str(BACKEND_ROOT))
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from core.agent import create_agent_backend
from core.agent.multimodal import build_hermes_user_message
from core.delivery import (
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    MessagingDeliveryAdapter,
)
from core.delivery.chat_platform_bridge import start_chat_platform_bridge, stop_chat_platform_bridge
from core.delivery.messaging import MessagePayload, MessageSender, MessagingConfig, create_default_registry
from core.delivery.messaging.telegram_discovery import discover_next_private_chat_id
from core.delivery.models import DeliveryMessage
from core.life import DailyLifeScheduler, LifeEngine
from core.messaging.messages import AgentDialogMessage
from core.messaging.dialog_tokens import (
    NARR_ALIASES,
    match_bgm_name,
    match_cg_name,
    match_choice_name,
    match_cot_name,
    match_scene_name,
    match_stat_name,
    normalize_character_name,
)
from core.messaging.stream_parser import AgentResponseStreamParser
from core.proactive import ContactPlanEngine, ProactiveContactScheduler
from core.sprite.character_profile import default_character_profile, normalize_character_profile
from core.sprite.emotion_resolver import resolve_sprite_index
from core.sprite.text_processor import TextProcessor, name_map
from core.importers.codex_pet_importer import (
    find_codex_pet_dirs,
    import_codex_pet_as_character,
)
from core.delivery.messaging.wechat_openclaw import api as wechat_api
from core.delivery.messaging.wechat_openclaw import state as wechat_state
from infrastructure.paths import (
    default_character_assets_dir,
    default_character_memory_dir,
    get_app_paths,
    install_user_python_packages_path,
    load_storage_paths,
    resolve_storage_path,
    resolve_character_asset_path,
    save_storage_paths,
    seed_defaults,
)
from internal_agent.context import AgentMemoryStore, build_agent_context
from internal_agent.dream import DreamScheduler, MemoryDreamer
from services.asr.asr_adapter import (
    build_asr_setup_status,
    create_default_asr_adapter,
    default_vosk_model_path,
    is_vosk_model_dir,
    missing_asr_requirements,
    normalize_asr_provider_storage_key,
)
from services.asr.macos_microphone_permission import request_macos_microphone_permission
from services.config.character_manager import CharacterManager
from services.config.config_manager import ConfigManager, SYSTEM_CHARACTER_NAME, is_placeholder_character_name
from services.config.schema import ApiConfig, Character, Sprite, SystemConfig
from services.selfie import SelfieRequest
from services.selfie.factory import build_selfie_runtime
from services.t2i.t2i_manager import T2IAdapterFactory, T2IManager
from services.storage_migration import is_strict_child, migrate_storage_locations
from services.tts.tts_manager import TTSAdapterFactory, TTSManager


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


class HereBackend:
    def __init__(self) -> None:
        self.paths = get_app_paths()
        install_user_python_packages_path(self.paths)
        seed_defaults(self.paths, source_root=BACKEND_ROOT / "defaults")
        self.config = ConfigManager()
        self.memory = AgentMemoryStore()
        self.history_path = self.paths.state_dir / "electron_history.json"
        self.history_lock = threading.RLock()
        self.chat_lock = threading.RLock()
        self.screen_context_last_prompt_at = 0.0
        self.asr_adapter: Any | None = None
        self.chat_platform_bridge: Any | None = None
        self._initialize_runtime()

    def _initialize_runtime(self) -> None:
        name_map.clear()
        for configured_character in self.config.config.characters:
            name_map.update(dict(getattr(configured_character, "pronunciation_map", {}) or {}))
        self.text_processor = TextProcessor()
        self.agent = create_agent_backend(
            self.config,
            system_prompt=self._system_template(),
            status_callback=lambda text: event("status", {"text": str(text), "busy": False}),
            tool_status_callback=lambda text: event("status", {"text": str(text), "busy": True}),
        )
        self.life = LifeEngine(self.memory)
        self.dream_scheduler = DreamScheduler(self.config, MemoryDreamer(self.memory, self.agent))
        self.contacts = ContactPlanEngine(self.memory, self.life)
        self.delivery_router = DeliveryRouter(self.config, DeliveryCapabilityProbe(self.config))
        self.sender = MessageSender(
            config=MessagingConfig.auto_load(),
            registry=create_default_registry(self._emit_dialog),
        )
        self.delivery = DeliveryAdapterRegistry(
            DesktopDeliveryAdapter(self._emit_dialog),
            MessagingDeliveryAdapter(self.sender),
        )
        self.tts = self._build_tts()
        self.t2i = self._build_t2i()
        try:
            self.selfie, self.selfie_t2i = build_selfie_runtime(
                self.config,
                existing_manager=self.t2i,
                enabled_only=True,
            )
        except Exception as exc:
            print(f"Selfie runtime unavailable: {exc}")
            self.selfie, self.selfie_t2i = None, self.t2i
        self.life_scheduler = DailyLifeScheduler(
            config_manager=self.config,
            life_engine=self.life,
            agent_backend=self.agent,
            allow_llm_generate_getter=self._proactive_enabled,
        )
        self.proactive = ProactiveContactScheduler(
            config_manager=self.config,
            life_engine=self.life,
            contact_engine=self.contacts,
            agent_backend=self.agent,
            active_character_name=self.config.resolve_active_character_name,
            emit_dialog=self._emit_dialog,
            enabled_getter=self._proactive_enabled,
            delivery_router=self.delivery_router,
            delivery_adapters=self.delivery,
            audio_generator=self._generate_tts_for_delivery,
            photo_generator=self._generate_photo,
            memory_store=self.memory,
        )
        if self._proactive_enabled():
            self.life_scheduler.start()
        self.dream_scheduler.start()
        self.proactive.start()
        self._restart_chat_platform_bridge()

    def _shutdown_runtime(self) -> None:
        stop_chat_platform_bridge(getattr(self, "chat_platform_bridge", None), wait=True)
        self.chat_platform_bridge = None
        for runtime in (
            getattr(self, "proactive", None),
            getattr(self, "life_scheduler", None),
            getattr(self, "dream_scheduler", None),
            getattr(self, "asr_adapter", None),
        ):
            stop = getattr(runtime, "stop", None)
            if callable(stop):
                try:
                    stop()
                except Exception:
                    pass
        try:
            self.agent.interrupt()
        except Exception:
            pass

    def _restart_chat_platform_bridge(self) -> None:
        stop_chat_platform_bridge(getattr(self, "chat_platform_bridge", None), wait=True)
        self.chat_platform_bridge = start_chat_platform_bridge(
            channel=str(getattr(self.config.config.system_config, "chat_delivery_channel", "desktop_chat")),
            emit_user_text=self._receive_platform_text,
            notify=lambda text: event("status", {"text": str(text), "busy": False}),
        )

    def _receive_platform_text(self, text: str) -> None:
        message = str(text or "").strip()
        if not message:
            return

        def run_inbound() -> None:
            request_id = f"platform-{uuid.uuid4().hex}"
            try:
                self.chat({"request_id": request_id, "text": message, "source": "platform"})
            except Exception as exc:
                traceback.print_exc()
                event("chat_error", {"request_id": request_id, "message": str(exc)})

        threading.Thread(target=run_inbound, name="here-platform-chat", daemon=True).start()

    def reload_runtime(self) -> None:
        had_asr_adapter = self.asr_adapter is not None
        self._shutdown_runtime()
        self.asr_adapter = None
        if had_asr_adapter:
            event("asr_state", {"running": False, "paused": False})
        self.config.reload()
        self._initialize_runtime()

    def _system_template(self) -> str:
        path = self.paths.templates_dir / "here_companion.txt"
        try:
            return path.read_text(encoding="utf-8")
        except OSError:
            return ""

    def _companion_context_template(self) -> str:
        """Load the project-owned runtime behavior skill only while 同桌模式 is on."""
        template = self._system_template()
        system = self.config.config.system_config
        if not bool(getattr(system, "screen_context_enabled", False)):
            return template
        skill_path = BACKEND_ROOT.parent / "skills" / "here-companion-mode" / "references" / "runtime-prompt.md"
        try:
            companion = skill_path.read_text(encoding="utf-8").strip()
        except OSError:
            companion = ""
        if companion:
            return f"{template}\n\n【同桌模式行为协议】\n{companion}"
        return template

    def _proactive_enabled(self) -> bool:
        return bool(self.config.config.system_config.proactive_contact_enabled)

    def _build_tts(self) -> TTSManager | None:
        provider = str(self.config.config.api_config.tts_provider or "none").strip().lower()
        if not provider or provider == "none":
            return None
        try:
            adapter = TTSAdapterFactory.create_adapter(
                provider,
                **self.config.merged_tts_factory_kwargs(provider, {}),
            )
            manager = TTSManager()
            manager.set_tts_adapter(adapter)
            manager.set_language(str(self.config.config.system_config.voice_language or "ja"))
            return manager
        except Exception as exc:
            event("status", {"text": f"TTS 初始化失败：{exc}", "busy": False})
            return None

    def _build_t2i(self) -> T2IManager | None:
        provider = str(self.config.config.api_config.t2i_provider or "image-api").strip()
        base = {}
        if provider.lower() == "image-api":
            base["api_url"] = str(self.config.config.api_config.t2i_api_url)
        try:
            adapter = T2IAdapterFactory.create_adapter(
                provider,
                **self.config.merged_t2i_factory_kwargs(provider, base),
            )
            return T2IManager(adapter)
        except Exception as exc:
            event("status", {"text": f"生图初始化失败：{exc}", "busy": False})
            return None

    def _history(self) -> list[dict[str, Any]]:
        with self.history_lock:
            try:
                value = json.loads(self.history_path.read_text(encoding="utf-8"))
                return value[-500:] if isinstance(value, list) else []
            except Exception:
                return []

    def _append_history(self, role: str, name: str, text: str, **extra: Any) -> dict[str, Any]:
        item = {
            "id": uuid.uuid4().hex,
            "role": role,
            "character_name": name,
            "text": text,
            "created_at": __import__("datetime").datetime.now().astimezone().isoformat(),
            **extra,
        }
        with self.history_lock:
            history = self._history()
            history.append(item)
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.history_path.with_suffix(".tmp")
            temp.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.history_path)
        return item

    def _write_history(self, history: list[dict[str, Any]]) -> None:
        with self.history_lock:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            temp = self.history_path.with_suffix(".tmp")
            temp.write_text(json.dumps(history[-500:], ensure_ascii=False, indent=2), encoding="utf-8")
            temp.replace(self.history_path)

    @staticmethod
    def _is_reserved_dialog_name(name: str) -> bool:
        normalized = normalize_character_name(name)
        return bool(
            match_cot_name(normalized)
            or match_choice_name(normalized)
            or match_stat_name(normalized)
            or match_scene_name(normalized)
            or match_bgm_name(normalized)
            or match_cg_name(normalized)
            or normalized in NARR_ALIASES
        )

    def _handle_system_action(
        self,
        dialog: AgentDialogMessage,
        *,
        active_character: str,
        user_text: str,
    ) -> AgentDialogMessage:
        action = dialog.system_action or {}
        if not isinstance(action, dict) or str(action.get("type") or "").strip() != "rename_active_character":
            return dialog
        old_name = str(active_character or "").strip()
        new_name = str(action.get("name") or action.get("new_name") or "").strip()
        if (
            not old_name
            or not new_name
            or old_name == new_name
            or old_name == SYSTEM_CHARACTER_NAME
            or not is_placeholder_character_name(old_name)
        ):
            return dialog
        if new_name not in str(user_text or "") and new_name not in str(dialog.text or ""):
            return dialog
        before_home = self.memory.agent_home(old_name)
        renamed = self.config.rename_character(old_name, new_name)
        if renamed != new_name:
            return dialog
        try:
            if before_home.exists():
                self.memory.rename_character(old_name, new_name)
        except Exception as exc:
            event("status", {"text": f"角色已重命名，但记忆目录迁移失败：{exc}", "busy": False})
        self.agent.reset_session()
        event("character", {"name": new_name})
        event("status", {"text": f"已将 {old_name} 命名为 {new_name}", "busy": False})
        return dialog.model_copy(update={"name": new_name})

    def _emit_dialog(
        self,
        dialog: AgentDialogMessage,
        request_id: str = "",
        *,
        publish: bool = True,
    ) -> None:
        name = normalize_character_name(str(dialog.name or ""))
        text = str(dialog.text or "")
        if match_cot_name(name):
            preview = re.sub(r"<[^>]+>", " ", text)
            if publish:
                event("status", {"text": re.sub(r"\s+", " ", preview).strip()[:200] or "正在思考", "busy": True})
            return
        if match_choice_name(name):
            self._append_history("assistant", "CHOICE", text, request_id=request_id)
            if publish:
                event("options", {"options": [part.strip() for part in text.split("/") if part.strip()], "request_id": request_id})
            return
        if match_stat_name(name):
            if publish:
                event("numeric", {"text": text, "request_id": request_id})
            return
        if match_scene_name(name):
            path = self._background_asset(dialog.asset_id)
            self.config.config.system_config.background_path = path
            self.config.save_system_config()
            if publish:
                event("background", {"path": path, "request_id": request_id})
            return
        if match_bgm_name(name):
            path = self._bgm_asset(dialog.asset_id)
            self.config.config.system_config.bgm_path = path
            self.config.save_system_config()
            if publish:
                event("bgm", {"path": path, "request_id": request_id})
            return
        if match_cg_name(name):
            path = ""
            if self.t2i is not None and text:
                if publish:
                    event("status", {"text": "正在生成场景图…", "busy": True})
                path = str(self.t2i.t2i(text) or "")
            if publish:
                event("cg", {
                    "path": path,
                    "caption": text,
                    "background_only": "no person" in text.lower(),
                    "request_id": request_id,
                })
            return
        item = self._append_history(
            "assistant",
            str(dialog.name or self.config.resolve_active_character_name()),
            text,
            emotion=str(dialog.emotion or "neutral"),
            asset_id=dialog.asset_id,
            request_id=request_id,
        )
        if publish:
            event("dialog", {**item, "translate": dialog.translate or "", "effect": dialog.effect or ""})
        if publish and name not in NARR_ALIASES and item["text"]:
            if self.tts is not None:
                threading.Thread(
                    target=self._emit_tts,
                    args=(item["character_name"], dialog.translate or item["text"], request_id),
                    daemon=True,
                ).start()
            else:
                character = self.config.get_character_by_name(item["character_name"])
                sprite_index = resolve_sprite_index(character, str(dialog.emotion or "neutral")) if character else -1
                if character is not None and 0 <= sprite_index < len(character.sprites):
                    sprite = character.sprites[sprite_index]
                    voice_path = sprite.get("voice_path", "") if isinstance(sprite, dict) else getattr(sprite, "voice_path", "")
                    if voice_path:
                        event("audio", {
                            "path": str(voice_path),
                            "request_id": request_id,
                            "character_name": item["character_name"],
                            "segment_index": 0,
                            "segment_count": 1,
                        })

    def _route_chat_dialog(self, dialog: AgentDialogMessage, request_id: str, active_character: str) -> None:
        if self._is_reserved_dialog_name(str(dialog.name or "")):
            self._emit_dialog(dialog, request_id)
            return
        route = self.delivery_router.route_chat_response()
        channel = str(getattr(route, "channel", "desktop_chat") or "desktop_chat")
        if channel == "desktop_chat":
            self._emit_dialog(dialog, request_id)
            return
        delivery_result = self.delivery.send(
            DeliveryMessage(
                dialog=dialog,
                character_name=active_character or str(dialog.name or ""),
                target_channel=channel,
            )
        )
        if str(getattr(delivery_result, "status", "") or "") == "sent":
            self._emit_dialog(dialog, request_id, publish=False)
            event("external_delivery", {"channel": channel, "status": "sent", "request_id": request_id})
            return
        reason = str(getattr(delivery_result, "reason", "") or "unknown")
        event("status", {"text": f"外部渠道发送失败，已回到桌面：{reason}", "busy": False})
        self._emit_dialog(dialog, request_id)

    def _background_asset(self, asset_id: Any) -> str:
        try:
            index = int(asset_id) - 1
        except (TypeError, ValueError):
            return ""
        for group in self.config.config.background_list:
            sprites = list(getattr(group, "sprites", []) or [])
            if 0 <= index < len(sprites):
                sprite = sprites[index]
                raw = sprite.get("path") if isinstance(sprite, dict) else getattr(sprite, "path", "")
                return resolve_character_asset_path(raw, self.paths).as_posix()
        return ""

    def _bgm_asset(self, asset_id: Any) -> str:
        try:
            index = int(asset_id) - 1
        except (TypeError, ValueError):
            return ""
        for group in self.config.config.background_list:
            tracks = list(getattr(group, "bgm_list", []) or [])
            if 0 <= index < len(tracks):
                path = Path(str(tracks[index])).expanduser()
                return path.as_posix() if path.is_absolute() else (BACKEND_ROOT / path).as_posix()
        return ""

    def _emit_tts(self, character_name: str, text: str, request_id: str = "") -> None:
        if self.tts is None:
            return
        character = self.config.get_character_by_name(character_name)
        speed = float(getattr(character, "speech_speed", 1.0) or 1.0) if character else 1.0
        try:
            api_config = self.config.config.api_config
            segments = [text]
            if bool(getattr(api_config, "tts_split_enabled", False)):
                maximum = max(5, int(getattr(api_config, "tts_max_sentence_length", 15) or 15))
                pieces = [part.strip() for part in re.split(r"(?<=[。！？，、；：\.!\?,;:])", text) if part.strip()]
                segments, current = [], ""
                for piece in pieces:
                    if not current or len(current) + len(piece) <= maximum:
                        current += piece
                    else:
                        segments.append(current)
                        current = piece
                if current:
                    segments.append(current)
                if not segments:
                    segments = [text]
            for index, segment in enumerate(segments):
                path = self.tts.generate_tts(
                    segment,
                    text_processor=self.text_processor,
                    character_name=character_name,
                    speed_factor=speed,
                )
                if path:
                    event("audio", {
                        "path": str(path),
                        "request_id": request_id,
                        "character_name": character_name,
                        "segment_index": index,
                        "segment_count": len(segments),
                    })
        except Exception as exc:
            event("status", {"text": f"语音生成失败：{exc}", "busy": False})

    def _generate_tts_for_delivery(self, character_name: str, text: str) -> str:
        if self.tts is None:
            return ""
        return str(self.tts.generate_tts(text, character_name=character_name) or "")

    def _generate_photo(self, request: SelfieRequest) -> str:
        if self.selfie is None:
            return ""
        generated = self.selfie.generate(request)
        return generated.path if generated else ""

    def state(self) -> dict[str, Any]:
        active_name = self.config.resolve_active_character_name()
        character = self.config.get_character_by_name(active_name)
        capabilities = {
            key: model_json(value)
            for key, value in DeliveryCapabilityProbe(self.config).probe().items()
        }
        life_plan = None
        contact_plan = None
        if character is not None:
            try:
                life_plan = self.life.ensure_daily_plan(character, allow_llm_generate=False)
                contact_plan = self.contacts.ensure_contact_plan(
                    character,
                    life_plan,
                    agent_backend=self.agent,
                    allow_llm_generate=False,
                )
            except Exception as exc:
                print(f"Plan snapshot failed: {exc}")
        return {
            "config": model_json(self.config.config),
            "active_character_name": active_name,
            "selected_backend": getattr(self.agent, "selected_backend_id", type(self.agent).__name__),
            "history": self._history(),
            "paths": model_json(self.paths.__dict__),
            "capabilities": capabilities,
            "adapter_schemas": adapter_schemas(),
            "chat_ui_theme": chat_ui_theme_snapshot(
                str(getattr(self.config.config.system_config, "chat_ui_theme_path", "") or "")
            ),
            "messaging": MessagingConfig.auto_load().to_dict(),
            "storage": model_json(load_storage_paths(self.paths.root).__dict__),
            "memory": {
                "character": self.memory.read_character_memories(active_name),
                "user": self.memory.read_user_profile(active_name),
            },
            "life_plan": model_json(life_plan.to_dict()) if life_plan else None,
            "contact_plan": model_json(contact_plan.to_dict()) if contact_plan else None,
        }

    def save_config(self, payload: dict[str, Any]) -> dict[str, Any]:
        rename = payload.get("character_rename") if isinstance(payload.get("character_rename"), dict) else {}
        old_name = str(rename.get("old_name") or "").strip()
        new_name = str(rename.get("new_name") or "").strip()
        if "api_config" in payload:
            self.config.config.api_config = ApiConfig.model_validate(payload["api_config"])
            self.config.save_api_config()
        if "system_config" in payload:
            self.config.config.system_config = SystemConfig.model_validate(payload["system_config"])
            self.config.save_system_config()
        if "characters" in payload:
            self.config.config.characters = [Character.model_validate(item) for item in payload["characters"]]
            self.config.save_characters_config()
        if old_name and new_name and old_name != new_name:
            try:
                self.memory.rename_character(old_name, new_name)
            except FileNotFoundError:
                pass
        self.reload_runtime()
        return self.state()

    def set_active_character(self, name: str) -> dict[str, Any]:
        active = self.config.set_active_character_name(name)
        self.agent.reset_session()
        event("character", {"name": active})
        return self.state()

    def _save_attachments(self, attachments: list[dict[str, Any]]) -> list[Path]:
        paths: list[Path] = []
        for attachment in attachments[:4]:
            data_url = str(attachment.get("dataUrl") or attachment.get("data_url") or "")
            match = re.match(r"^data:([^;,]+);base64,(.+)$", data_url, flags=re.DOTALL)
            if not match:
                continue
            extension = mimetypes.guess_extension(match.group(1)) or ".png"
            path = self.paths.input_images_dir / f"electron_{uuid.uuid4().hex}{extension}"
            path.write_bytes(base64.b64decode(match.group(2)))
            paths.append(path)
        return paths

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.chat_lock:
            return self._chat(payload)

    def observe_screen(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Use a temporary screen snapshot to learn durable, non-sensitive user habits."""
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"角色不存在：{name}")
        paths = self._save_attachments(list(payload.get("attachments") or []))
        if not paths:
            return {"observed": False, "memories_added": 0}
        try:
            refs = "".join(f"\n[图片: {path.as_posix()}]" for path in paths)
            prompt = (
                "你是 here 的同桌观察助手。根据当前屏幕截图，判断用户是否表现出稳定、可长期帮助对话的工作习惯。\n"
                "只记录重复性或明显稳定的习惯，不记录当前文件正文、具体聊天内容、姓名、密码、验证码、账号、地址或其他敏感信息。\n"
                "同桌模式也可以主动陪伴，但只有在确实能帮上忙时才打扰用户。只输出严格 JSON 对象："
                '{"habits":[{"habit":"用户通常在晚上进行编程工作","confidence":0.82}],'
                '"should_speak":false,"message":""}。\n'
                "message 只写一句简短、自然的桌面对白；如果没有必要打扰，should_speak 必须为 false 且 message 为空。"
                "如果没有足够证据，habits 输出 []。单次画面不能证明稳定习惯。\n"
                f"{refs}"
            )
            context = build_agent_context(
                config_manager=self.config,
                memory_store=self.memory,
                system_template=self._companion_context_template(),
                session_id="screen-context",
                selected_character_names=[name],
                life_state="",
            )
            with self.chat_lock:
                raw = self.agent.chat(
                    build_hermes_user_message(prompt),
                    context=context,
                    stream=False,
                )
            text = str(raw or "").strip()
            start = text.find("{")
            parsed: dict[str, Any] = {}
            if start >= 0:
                try:
                    parsed = json.JSONDecoder().raw_decode(text[start:])[0]
                except (json.JSONDecodeError, TypeError):
                    parsed = {}
            candidates = parsed.get("habits", []) if isinstance(parsed, dict) else []
            if not isinstance(candidates, list):
                candidates = []
            current = self.memory.read_user_profile(name)
            added: list[str] = []
            sensitive = re.compile(r"密码|验证码|口令|密钥|token|password|信用卡|身份证|私聊|聊天记录", re.IGNORECASE)
            for item in candidates:
                if not isinstance(item, dict):
                    continue
                habit = str(item.get("habit") or "").strip()
                try:
                    confidence = float(item.get("confidence") or 0)
                except (TypeError, ValueError):
                    confidence = 0
                if not habit or confidence < 0.7 or len(habit) > 240 or sensitive.search(habit):
                    continue
                if any(re.sub(r"\s+", "", habit).casefold() == re.sub(r"\s+", "", old).casefold() for old in current):
                    continue
                current.append(habit)
                added.append(habit)
            if added:
                self.memory.write_user_profile(name, current[-100:])
            now = time.monotonic()
            message = str(parsed.get("message") or "").strip() if isinstance(parsed, dict) else ""
            should_speak = bool(parsed.get("should_speak")) if isinstance(parsed, dict) else False
            if should_speak and message and now - self.screen_context_last_prompt_at >= 30 * 60:
                self.screen_context_last_prompt_at = now
                self._emit_dialog(
                    AgentDialogMessage(name=name, text=message, emotion="thinking"),
                    request_id=f"screen-context-{uuid.uuid4().hex}",
                )
            return {"observed": True, "memories_added": len(added), "memories": added}
        finally:
            for path in paths:
                try:
                    path.unlink(missing_ok=True)
                except OSError:
                    pass

    def _chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_id = str(payload.get("request_id") or payload.get("requestId") or uuid.uuid4().hex)
        text = str(payload.get("text") or "").strip()
        name = str(payload.get("character_name") or payload.get("characterName") or self.config.resolve_active_character_name())
        if name != self.config.resolve_active_character_name():
            name = self.config.set_active_character_name(name)
            self.agent.reset_session()
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"角色不存在：{name}")
        paths = self._save_attachments(list(payload.get("attachments") or []))
        message_text = text + "".join(f"\n[图片: {path.as_posix()}]" for path in paths)
        self._append_history(
            "user",
            "你",
            text or "[图片]",
            request_id=request_id,
            attachments=[path.name for path in paths],
        )
        self.proactive.note_user_message()
        event("chat_start", {"request_id": request_id, "character_name": name})
        life_state = ""
        try:
            self.life.observe_user_message(character, text, agent_backend=self.agent, allow_llm_generate=False)
            life_state = self.life.current_life_state(character, agent_backend=self.agent, allow_llm_generate=False)
        except Exception as exc:
            print(f"Life state update failed: {exc}")
        context = build_agent_context(
            config_manager=self.config,
            memory_store=self.memory,
            system_template=self._companion_context_template(),
            session_id="default",
            selected_character_names=[name],
            life_state=life_state,
        )
        raw = self.agent.chat(
            build_hermes_user_message(message_text),
            context=context,
            stream=bool(self.config.config.api_config.hermes_streaming),
        )
        chunks = raw if self.config.config.api_config.hermes_streaming else [raw]
        parser = AgentResponseStreamParser()
        dialogs: list[AgentDialogMessage] = []

        def publish_dialog(raw_dialog: AgentDialogMessage) -> None:
            current_name = self.config.resolve_active_character_name()
            dialog = self._handle_system_action(raw_dialog, active_character=current_name, user_text=text)
            current_name = self.config.resolve_active_character_name()
            if not self._is_reserved_dialog_name(str(dialog.name or "")) and str(dialog.name or "").strip() != current_name:
                dialog = dialog.model_copy(update={"name": current_name})
            dialogs.append(dialog)
            self._route_chat_dialog(dialog, request_id, current_name)

        for chunk in chunks:
            value = chunk if isinstance(chunk, str) else str(chunk or "")
            for dialog in parser.feed(value):
                publish_dialog(dialog)
        for dialog in parser.flush():
            publish_dialog(dialog)
        if not dialogs:
            for dialog in parser.recover_messages(parser.accumulated_text):
                publish_dialog(dialog)
        if not dialogs:
            fallback = parser.accumulated_text.strip() or "刚才没有拿到有效回复，我们再试一次。"
            publish_dialog(AgentDialogMessage(name=name, text=fallback, emotion="neutral"))
        event("chat_done", {"request_id": request_id})
        return {"request_id": request_id, "dialogs": [model_json(item) for item in dialogs]}

    def stop_chat(self) -> None:
        self.agent.interrupt()

    def clear_history(self) -> list[Any]:
        with self.history_lock:
            self.history_path.parent.mkdir(parents=True, exist_ok=True)
            self.history_path.write_text("[]\n", encoding="utf-8")
        self.agent.reset_session()
        return []

    def revert_history(self, payload: dict[str, Any]) -> dict[str, Any]:
        history = self._history()
        message_id = str(payload.get("user_message_id") or payload.get("id") or "").strip()
        target_index = -1
        if message_id:
            target_index = next(
                (index for index, item in enumerate(history) if item.get("id") == message_id and item.get("role") == "user"),
                -1,
            )
        elif payload.get("user_index") is not None:
            wanted = int(payload.get("user_index") or 0)
            user_indexes = [index for index, item in enumerate(history) if item.get("role") == "user"]
            if 0 <= wanted < len(user_indexes):
                target_index = user_indexes[wanted]
        if target_index < 0:
            raise ValueError("没有找到要回滚的用户消息。")
        reverted = history[:target_index]
        self._write_history(reverted)
        self.agent.reset_session()
        display = next((item for item in reversed(reverted) if item.get("role") == "assistant"), None)
        event("history_reverted", {"history": reverted, "display": display})
        return {"history": reverted, "display": display}

    def update_memory(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        kind = str(payload.get("kind") or "character")
        entries = [str(item).strip() for item in payload.get("entries", []) if str(item).strip()]
        if kind == "user":
            self.memory.write_user_profile(name, entries)
        else:
            self.memory.write_character_memories(name, entries)
        return {"character": self.memory.read_character_memories(name), "user": self.memory.read_user_profile(name)}

    def upload_character_sprites(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"角色不存在：{name}。请先保存新角色，再添加立绘。")
        target = self.paths.characters_dir / str(character.sprite_prefix or re.sub(r"\W+", "_", name))
        target.mkdir(parents=True, exist_ok=True)
        added = 0
        for attachment in list(payload.get("attachments") or []):
            data_url = str(attachment.get("dataUrl") or attachment.get("data_url") or "")
            match = re.match(r"^data:([^;,]+);base64,(.+)$", data_url, flags=re.DOTALL)
            if not match:
                continue
            extension = mimetypes.guess_extension(match.group(1)) or ".png"
            raw_name = Path(str(attachment.get("name") or f"sprite_{added + 1}{extension}")).name
            stem = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", Path(raw_name).stem).strip("_") or f"sprite_{added + 1}"
            path = target / f"{stem}_{uuid.uuid4().hex[:6]}{extension}"
            path.write_bytes(base64.b64decode(match.group(2)))
            character.sprites.append(Sprite(path=path, state_name="", state_group="custom"))
            added += 1
        if not added:
            raise ValueError("没有可用的立绘图片。")
        character.emotion_tags = str(payload.get("emotion_tags") or character.emotion_tags or "")
        self.config.save_characters_config()
        return self.state()

    def create_character(self, payload: dict[str, Any]) -> dict[str, Any]:
        requested = str(payload.get("name") or "").strip()
        setting = str(payload.get("setting") or "").strip()
        raw_states = payload.get("states") if isinstance(payload.get("states"), list) else []
        states: list[dict[str, Any]] = []
        for raw_state in raw_states:
            if not isinstance(raw_state, dict):
                continue
            paths = [Path(str(value)).expanduser().resolve() for value in raw_state.get("paths", [])]
            paths = [path for path in paths if path.is_file()]
            if paths:
                states.append({**raw_state, "paths": paths})
        if not states:
            paths = [Path(str(value)).expanduser().resolve() for value in payload.get("paths", [])]
            paths = [path for path in paths if path.is_file()]
            if paths:
                states = [{
                    "state_name": str(payload.get("state_name") or "neutral"),
                    "state_group": str(payload.get("state_group") or "core_emotion"),
                    "frame_interval_ms": int(payload.get("frame_interval_ms") or 120),
                    "paths": paths,
                }]
        if not requested:
            raise ValueError("角色名不能为空。")
        if not setting:
            raise ValueError("请填写角色人设。")
        if not states:
            raise ValueError("至少需要导入一个立绘图片或动画。")
        names = {str(character.name or "").strip() for character in self.config.config.characters}
        name = requested
        if name in names:
            raise ValueError(f"角色名称已存在：{name}")
        previous_active = self.config.resolve_active_character_name()
        raw_profile = payload.get("character_profile")
        profile = normalize_character_profile(name, raw_profile) if isinstance(raw_profile, dict) else default_character_profile(name)
        character = Character(
            name=name,
            color=str(payload.get("color") or "#84c2d5"),
            sprite_prefix=f"character_{uuid.uuid4().hex[:10]}",
            sprites=[],
            character_profile=profile,
            character_setting=setting,
            visual_reference_image="",
            visual_identity=str(payload.get("visual_identity") or "").strip(),
            sprite_scale=float(
                getattr(self.config.config.system_config, "default_sprite_scale", 0.72)
                or 0.72
            ),
            emotion_tags="",
            speech_speed=1.0,
            speech_volume=1.0,
            pronunciation_map={},
        )
        self.config.config.characters.append(character)
        try:
            self.config.save_characters_config()
            self.config.set_active_character_name(name)
            for sprite_state in states:
                self.import_character_state_assets({
                    "character_name": name,
                    "state_name": str(sprite_state.get("state_name") or "neutral"),
                    "state_group": str(sprite_state.get("state_group") or "core_emotion"),
                    "frame_interval_ms": int(sprite_state.get("frame_interval_ms") or 120),
                    "paths": [path.as_posix() for path in sprite_state["paths"]],
                })
            # Qt stores the first imported sprite as the visual reference and
            # seeds the emotion prompt with the imported state mapping. Keep
            # both values available to T2I and the agent immediately after
            # creating a character.
            if character.sprites:
                first_sprite = model_json(character.sprites[0])
                character.visual_reference_image = str(first_sprite.get("path") or "")
                tag_lines = [
                    "状态分组：核心情绪 core_emotion、系统可选情绪 system_optional_emotion、用户自定义 custom、鼠标事件 mouse_event。",
                    "核心情绪标准名：neutral/happy/thinking/surprised/sad/angry；这些状态允许缺少。",
                    "",
                ]
                state_tags = {
                    "neutral": "默认、平静、普通、neutral",
                    "happy": "开心、欢迎、打招呼、happy",
                    "thinking": "思考、等待、处理中、thinking",
                    "surprised": "惊讶、被点名、注意力被拉起、surprised",
                    "sad": "难过、失败、出错、sad",
                    "angry": "生气、不满、抗议、angry",
                }
                for index, sprite in enumerate(character.sprites, start=1):
                    raw_sprite = model_json(sprite)
                    state_name = str(raw_sprite.get("state_name") or "custom").strip() or "custom"
                    group = str(raw_sprite.get("state_group") or "custom").strip() or "custom"
                    tags = state_tags.get(state_name, state_name)
                    tag_lines.append(f"立绘 {index}：{state_name}；分组：{group}；{tags}")
                character.emotion_tags = "\n".join(tag_lines)
                self.config.save_characters_config()
            self.reload_runtime()
        except Exception:
            self.config.config.characters = [item for item in self.config.config.characters if item.name != name]
            self.config.save_characters_config()
            self.config.set_active_character_name(previous_active)
            shutil.rmtree(self.paths.characters_dir / character.sprite_prefix, ignore_errors=True)
            raise
        event("character", {"name": name})
        return self.state()

    @staticmethod
    def _safe_asset_name(value: str, fallback: str) -> str:
        cleaned = re.sub(r"[^0-9A-Za-z_\-\u4e00-\u9fff]+", "_", str(value or "")).strip("_")
        return cleaned or fallback

    def import_character_state_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"角色不存在：{name}")
        source_paths = [Path(str(value)).expanduser().resolve() for value in payload.get("paths", [])]
        source_paths = [path for path in source_paths if path.is_file()]
        if not source_paths:
            raise ValueError("没有选择有效的立绘或动画文件。")
        state_name = self._safe_asset_name(str(payload.get("state_name") or "custom"), "custom")
        if state_name == "video_call" and (len(source_paths) != 1 or source_paths[0].suffix.lower() not in {".mp4", ".webm", ".m4v"}):
            raise ValueError("视频通话请选择一个 MP4、WebM 或 M4V 视频。")
        state_group = str(payload.get("state_group") or "custom").strip() or "custom"
        interval = max(20, min(10_000, int(payload.get("frame_interval_ms") or 120)))
        prefix = self._safe_asset_name(str(character.sprite_prefix or name), "character")
        target_dir = self.paths.characters_dir / prefix / "animations" / state_name
        shutil.rmtree(target_dir, ignore_errors=True)
        target_dir.mkdir(parents=True, exist_ok=True)

        video_suffixes = {".mp4", ".mov", ".m4v", ".avi", ".mkv", ".webm"}
        frames: list[Path] = []
        native_video = len(source_paths) == 1 and state_name == "video_call" and source_paths[0].suffix.lower() in {".mp4", ".webm", ".m4v"}
        if native_video:
            first_path = target_dir / f"video_call{source_paths[0].suffix.lower()}"
            shutil.copy2(source_paths[0], first_path)
        elif len(source_paths) == 1 and source_paths[0].suffix.lower() in video_suffixes:
            try:
                import cv2
            except ImportError as exc:
                raise RuntimeError("导入视频立绘需要 opencv-python，请先在语音与依赖页安装视频支持。") from exc
            capture = cv2.VideoCapture(source_paths[0].as_posix())
            frame_index = 0
            try:
                while capture.isOpened():
                    ok, frame = capture.read()
                    if not ok:
                        break
                    destination = target_dir / f"frame_{frame_index + 1:04d}.png"
                    if cv2.imwrite(destination.as_posix(), frame):
                        frames.append(destination)
                    frame_index += 1
            finally:
                capture.release()
            if not frames:
                raise RuntimeError("没有从视频中提取到有效帧。")
        elif len(source_paths) == 1 and source_paths[0].suffix.lower() in {".gif", ".webp"}:
            from PIL import Image, ImageSequence

            with Image.open(source_paths[0]) as image:
                for frame_index, frame in enumerate(ImageSequence.Iterator(image)):
                    destination = target_dir / f"frame_{frame_index + 1:04d}.png"
                    frame.convert("RGBA").save(destination, format="PNG")
                    frames.append(destination)
                    duration = int(frame.info.get("duration") or 0)
                    if frame_index == 0 and duration > 0 and not payload.get("frame_interval_ms"):
                        interval = max(20, min(10_000, duration))
            if len(frames) <= 1:
                frames = []
        if native_video:
            pass
        elif not frames:
            copied: list[Path] = []
            for index, source in enumerate(source_paths):
                suffix = source.suffix.lower()
                if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}:
                    raise ValueError(f"不支持的立绘格式：{source.name}")
                destination = target_dir / f"frame_{index + 1:04d}{suffix}"
                shutil.copy2(source, destination)
                copied.append(destination)
            frames = copied if len(copied) > 1 else []
            first_path = copied[0]
        else:
            first_path = frames[0]

        target_index: int | None = None
        previous_sprite: dict[str, Any] = {}
        if payload.get("sprite_index") is not None:
            target_index = int(payload["sprite_index"])
            if target_index < 0 or target_index >= len(character.sprites):
                raise ValueError("立绘索引无效。")
            previous_sprite = model_json(character.sprites[target_index])

        sprite = Sprite(
            path=first_path,
            frames=[path.as_posix() for path in frames],
            frame_interval_ms=interval,
            state_name=state_name,
            state_group=state_group,
            source_state=state_name,
            voice_path=previous_sprite.get("voice_path") or None,
            voice_text=previous_sprite.get("voice_text") or None,
        )
        if target_index is not None:
            character.sprites[target_index] = sprite
        else:
            existing_index = next(
                (
                    index
                    for index, existing in enumerate(character.sprites)
                    if str(getattr(existing, "state_name", "") or (existing.get("state_name") if isinstance(existing, dict) else "")) == state_name
                ),
                -1,
            )
            if existing_index >= 0:
                character.sprites[existing_index] = sprite
            else:
                character.sprites.append(sprite)
        self.config.save_characters_config()
        return self.state()

    def delete_character_sprite(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        character = self.config.get_character_by_name(name)
        if character is None:
            raise ValueError(f"角色不存在：{name}")
        index = int(payload.get("index") or 0)
        if index < 0 or index >= len(character.sprites):
            raise ValueError("立绘索引无效。")
        sprite = character.sprites[index]
        raw = model_json(sprite)
        # Imported animations live below the character asset root. Remove only
        # files/directories owned by this character; external legacy paths are
        # left untouched.
        asset_root = (self.paths.characters_dir / str(character.sprite_prefix or "")).resolve()
        referenced = [raw.get("path"), *(raw.get("frames") or []), raw.get("spritesheet_path"), raw.get("voice_path")]
        for candidate in referenced:
            if not candidate:
                continue
            try:
                path = resolve_character_asset_path(candidate, self.paths).resolve()
                if path.is_file() and (path == asset_root or asset_root in path.parents):
                    path.unlink(missing_ok=True)
                elif path.is_dir() and (path == asset_root or asset_root in path.parents):
                    shutil.rmtree(path, ignore_errors=True)
            except (OSError, RuntimeError, ValueError):
                continue
        voice_path = str(raw.get("voice_path") or "").strip()
        if voice_path:
            try:
                voice = Path(voice_path).expanduser().resolve()
                voice_root = (self.paths.generated_dir / "voices" / str(character.sprite_prefix or "")).resolve()
                if voice.is_file() and (voice == voice_root or voice_root in voice.parents):
                    voice.unlink(missing_ok=True)
            except (OSError, RuntimeError, ValueError):
                pass
        character.sprites.pop(index)
        # Keep the legacy numbered emotion notes aligned with the sprite list.
        tags = str(character.emotion_tags or "").splitlines()
        if tags and 0 <= index < len(tags):
            del tags[index]
            normalized: list[str] = []
            for number, line in enumerate(tags, start=1):
                if "：" in line:
                    detail = line.split("：", 1)[1].strip()
                elif ":" in line:
                    detail = line.split(":", 1)[1].strip()
                else:
                    detail = line.strip()
                normalized.append(f"立绘 {number}：{detail}" if detail else f"立绘 {number}：")
            character.emotion_tags = "\n".join(normalized)
        self.config.save_characters_config()
        return self.state()

    def delete_character(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("name") or self.config.resolve_active_character_name()).strip()
        if name == SYSTEM_CHARACTER_NAME:
            raise ValueError("内置系统角色不能删除。")
        if len(self.config.config.characters) <= 1:
            raise ValueError("不能删除最后一个角色。")
        message, _ = CharacterManager().delete_character(name, delete_memory=bool(payload.get("delete_memory")))
        if "找不到" in message or "不能" in message:
            raise ValueError(message)
        self.reload_runtime()
        active = self.config.resolve_active_character_name()
        event("character", {"name": active})
        return self.state()

    def generate_image(self, payload: dict[str, Any]) -> dict[str, Any]:
        if self.t2i is None:
            raise RuntimeError("当前生图适配器未成功初始化。")
        prompt = str(payload.get("prompt") or "").strip()
        if not prompt:
            raise ValueError("生图提示词不能为空。")
        event("status", {"text": "正在生成图片…", "busy": True})
        path = self.t2i.t2i(prompt, **dict(payload.get("options") or {}))
        event("status", {"text": "图片生成完成。" if path else "图片生成失败。", "busy": False})
        return {"path": str(path or "")}

    def generate_realtime_sprite(self, payload: dict[str, Any]) -> dict[str, Any]:
        system = self.config.config.system_config
        if not bool(system.sprite_realtime_enabled):
            return {"path": "", "enabled": False}
        if self.t2i is None:
            raise RuntimeError("实时立绘已启用，但当前生图适配器未成功初始化。")
        character_name = str(payload.get("character_name") or self.config.resolve_active_character_name()).strip()
        emotion = str(payload.get("emotion") or "neutral").strip() or "neutral"
        scene = str(payload.get("scene") or "normal").strip() or "normal"
        template = str(system.sprite_realtime_prompt_template or "").strip() or (
            "{character_name}, {emotion} expression, {scene}, anime style, high quality, "
            "detailed, masterpiece, white background, full body, standing pose"
        )
        try:
            prompt = template.format(character_name=character_name, emotion=emotion, scene=scene)
        except (KeyError, ValueError) as exc:
            raise ValueError(f"实时立绘提示词模板无效：{exc}") from exc
        cache_root = Path(str(system.sprite_realtime_cache_dir or "")).expanduser()
        if not str(system.sprite_realtime_cache_dir or "").strip():
            cache_root = self.paths.cache_dir / "sprite_cache"
        cache_root.mkdir(parents=True, exist_ok=True)
        api = self.config.config.api_config
        fingerprint = "\n".join((prompt, str(api.t2i_provider or ""), str(api.t2i_api_url or "")))
        cache_key = hashlib.sha256(fingerprint.encode("utf-8")).hexdigest()[:16]
        safe_name = self._safe_asset_name(character_name, "character")
        cache_path = cache_root / f"{safe_name}_{cache_key}.png"
        if not cache_path.is_file():
            event("status", {"text": f"正在生成 {character_name} 的立绘…", "busy": True})
            result = self.t2i.t2i(prompt, file_path=cache_path.as_posix())
            if not result or not Path(result).is_file():
                event("status", {"text": "实时立绘生成失败，已保留当前立绘。", "busy": False})
                return {"path": "", "enabled": True, "cached": False}
            cache_path = Path(result)
        event("status", {"text": "", "busy": False})
        character = self.config.get_character_by_name(character_name)
        return {
            "path": cache_path.as_posix(),
            "enabled": True,
            "cached": cache_path.is_file(),
            "scale": float(getattr(character, "sprite_scale", 1.0) or 1.0),
        }

    def start_asr(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        # Electron owns the user-facing macOS permission request. A Python
        # child process may have a different TCC identity, so do not repeat
        # the check when the host has already authorized this request.
        host_authorized = isinstance(payload, dict) and payload.get("__here_macos_microphone_authorized") is True
        if not host_authorized:
            permission_granted, permission_message = request_macos_microphone_permission()
            if not permission_granted:
                raise RuntimeError(permission_message)
        if self.asr_adapter is None:
            self.asr_adapter = create_default_asr_adapter(
                lambda text, is_partial: event(
                    "transcript",
                    {"text": text, "final": not bool(is_partial)},
                )
            )
        self.asr_adapter.start()
        status = self.asr_adapter.get_status()
        event("asr_state", {"running": status == "Running", "paused": False})
        return {"status": status}

    def stop_asr(self) -> dict[str, Any]:
        if self.asr_adapter is not None:
            self.asr_adapter.stop()
        event("asr_state", {"running": False, "paused": False})
        return {"status": "Stopped"}

    def pause_asr(self) -> dict[str, Any]:
        if self.asr_adapter is not None:
            self.asr_adapter.pause()
        running = self.asr_adapter is not None and self.asr_adapter.get_status() == "Running"
        return {"status": "Paused" if running else "Stopped"}

    def resume_asr(self) -> dict[str, Any]:
        if self.asr_adapter is not None:
            self.asr_adapter.resume()
        return {"status": self.asr_adapter.get_status() if self.asr_adapter else "Stopped"}

    def codex_pet_candidates(self) -> list[str]:
        return [path.as_posix() for path in find_codex_pet_dirs()]

    def import_codex_pet(self, payload: dict[str, Any]) -> dict[str, Any]:
        path = Path(str(payload.get("path") or "")).expanduser()
        imported = import_codex_pet_as_character(path, config_manager=self.config, make_active=True)
        self.reload_runtime()
        event("character", {"name": imported.character_name})
        return {
            "import": model_json(imported.__dict__),
            "state": self.state(),
        }

    def wechat_login_start(self, payload: dict[str, Any]) -> dict[str, Any]:
        login = wechat_api.start_login(base_url=str(payload.get("base_url") or "").strip() or "https://ilinkai.weixin.qq.com")
        import qrcode

        image = qrcode.make(login.qrcode_url or login.qrcode)
        buffer = io.BytesIO()
        image.save(buffer, format="PNG")
        return {
            **model_json(login.__dict__),
            "qr_data_url": "data:image/png;base64," + base64.b64encode(buffer.getvalue()).decode("ascii"),
        }

    def wechat_login_poll(self, payload: dict[str, Any]) -> dict[str, Any]:
        polled = wechat_api.poll_login(
            qrcode=str(payload.get("qrcode") or ""),
            base_url=str(payload.get("base_url") or "").strip() or "https://ilinkai.weixin.qq.com",
            timeout=8,
        )
        if polled.account is not None:
            wechat_state.replace_accounts(polled.account)
            self._restart_chat_platform_bridge()
        return model_json(polled.__dict__)

    def wechat_status(self) -> dict[str, Any]:
        accounts = []
        for account_id in wechat_state.list_account_ids():
            account = wechat_state.load_account(account_id)
            if account is None:
                continue
            accounts.append({
                "account_id": account.account_id,
                "base_url": account.base_url,
                "user_id": account.user_id,
                "recipients": wechat_state.list_context_user_ids(account.account_id),
            })
        return {"accounts": accounts}

    def telegram_discover(self, payload: dict[str, Any]) -> dict[str, Any]:
        token = str(payload.get("token") or "").strip()
        if not token:
            raise ValueError("请先填写 Telegram Bot Token。")
        discovered = discover_next_private_chat_id(token, timeout_seconds=45)
        return model_json(discovered.__dict__)

    def list_models(self, payload: dict[str, Any]) -> dict[str, Any]:
        from openai import OpenAI

        base_url = str(payload.get("base_url") or "").strip().rstrip("/")
        api_key = str(payload.get("api_key") or "").strip() or "unused"
        client = OpenAI(api_key=api_key, base_url=base_url or None)
        models = sorted(
            str(model.id)
            for model in client.models.list().data
            if str(getattr(model, "id", "") or "").strip()
        )
        return {"models": models}

    def dependency_status(self, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        return {
            "asr": {
                provider: {
                    "missing": missing_asr_requirements(provider),
                    "ready": build_asr_setup_status(
                        provider,
                        model_path=self._configured_vosk_model_path(payload) if provider == "vosk" else None,
                    ).ready,
                }
                for provider in ("vosk", "faster_whisper", "realtime_stt")
            },
            "video": {"missing": [] if importlib.util.find_spec("cv2") else ["cv2"]},
            "hermes": {
                "missing": []
                if importlib.util.find_spec("run_agent") and importlib.util.find_spec("hermes_cli.config")
                else ["hermes-agent"]
            },
        }

    def _configured_vosk_model_path(self, payload: dict[str, Any] | None = None) -> str:
        """Resolve the Vosk directory from an explicit form value or saved settings."""
        requested = str((payload or {}).get("model_path") or "").strip()
        if requested:
            return requested
        extra = self.config.config.api_config.asr_extra_configs or {}
        vosk_config = extra.get("vosk") or {}
        configured = vosk_config.get("model_path") if isinstance(vosk_config, dict) else ""
        return str(configured or "").strip() or default_vosk_model_path()

    def _download_vosk_model(self, model_path: str) -> str:
        """Download and unpack the bundled small Chinese Vosk model on demand."""
        target = Path(model_path).expanduser()
        if is_vosk_model_dir(target):
            return target.as_posix()
        target.parent.mkdir(parents=True, exist_ok=True)
        archive = target.parent / f".{target.name}.download.zip"
        url = "https://alphacephei.com/vosk/models/vosk-model-small-cn-0.22.zip"
        event("status", {"text": "正在下载 Vosk 模型…", "busy": True})
        try:
            urllib.request.urlretrieve(url, archive)
            event("status", {"text": "正在解压 Vosk 模型…", "busy": True})
            with zipfile.ZipFile(archive) as zf:
                root = target.parent.resolve()
                for member in zf.infolist():
                    destination = (root / member.filename).resolve()
                    if destination != root and root not in destination.parents:
                        raise RuntimeError("Vosk 模型压缩包包含非法路径。")
                zf.extractall(root)
            extracted = target.parent / "vosk-model-small-cn-0.22"
            if target.resolve() != extracted.resolve():
                if target.is_dir():
                    shutil.rmtree(target)
                elif target.exists():
                    target.unlink()
                if extracted.is_dir():
                    shutil.move(extracted.as_posix(), target.as_posix())
            if not is_vosk_model_dir(target):
                raise RuntimeError(f"Vosk 模型解压后目录无效：{target}")
            return target.as_posix()
        finally:
            try:
                archive.unlink()
            except OSError:
                pass
            event("status", {"text": "", "busy": False})

    def install_dependencies(self, payload: dict[str, Any]) -> dict[str, Any]:
        feature = str(payload.get("feature") or "").strip().lower().replace("-", "_")
        packages = {
            "vosk": ("pyaudio", "vosk==0.3.44"),
            "faster_whisper": ("pyaudio", "faster-whisper"),
            "realtime_stt": ("RealtimeSTT",),
            "video": ("opencv-python",),
            "hermes": ("git+https://github.com/NousResearch/hermes-agent.git@0f0e20ef81709a6dd590b25af380b116db67628c",),
        }.get(feature)
        if not packages:
            raise ValueError(f"不支持的依赖功能：{feature}")
        target = self.paths.python_packages_dir
        target.mkdir(parents=True, exist_ok=True)
        event("status", {"text": f"正在安装 {feature} 依赖…", "busy": True})
        command = [sys.executable, "-m", "pip", "install", "--upgrade", "--target", str(target), *packages]
        completed = subprocess.run(command, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=30 * 60)
        if completed.returncode != 0:
            tail = "\n".join(completed.stdout.splitlines()[-12:])
            raise RuntimeError(f"依赖安装失败：\n{tail}")
        importlib.invalidate_caches()
        event("status", {"text": f"{feature} 依赖安装完成。", "busy": False})
        return self.dependency_status()

    def prepare_asr(self, payload: dict[str, Any]) -> dict[str, Any]:
        provider = normalize_asr_provider_storage_key(str(payload.get("provider") or "vosk"))
        missing = missing_asr_requirements(provider)
        if missing:
            raise RuntimeError("缺少 ASR 依赖：" + "、".join(missing))
        if provider == "vosk":
            model_path = self._configured_vosk_model_path(payload)
            status = build_asr_setup_status(provider, model_path=model_path)
            if status.needs_model:
                model_path = self._download_vosk_model(model_path)
                status = build_asr_setup_status(provider, model_path=model_path)
            if not status.ready:
                raise RuntimeError(status.user_message())
            return {"provider": provider, "ready": True, "model": model_path}
        model = str(payload.get("model") or "small").strip() or "small"
        if provider == "faster_whisper":
            from faster_whisper import WhisperModel

            device = str(payload.get("device") or "auto")
            compute_type = str(payload.get("compute_type") or "").strip() or "default"
            WhisperModel(model, device=device, compute_type=compute_type)
        return {"provider": provider, "ready": True, "model": model}

    def save_messaging(self, payload: dict[str, Any]) -> dict[str, Any]:
        config = MessagingConfig(payload)
        config.save()
        self.sender = MessageSender(config=config, registry=create_default_registry(self._emit_dialog))
        self.delivery = DeliveryAdapterRegistry(
            DesktopDeliveryAdapter(self._emit_dialog),
            MessagingDeliveryAdapter(self.sender),
        )
        self.delivery_router = DeliveryRouter(self.config, DeliveryCapabilityProbe(self.config))
        self._restart_chat_platform_bridge()
        return {
            key: model_json(value)
            for key, value in DeliveryCapabilityProbe(self.config).probe().items()
        }

    def save_storage(self, payload: dict[str, Any]) -> dict[str, Any]:
        old_memory = self.paths.memory_dir
        old_assets = self.paths.characters_dir
        old_config = load_storage_paths(self.paths.root)
        memory_raw = str(payload.get("character_memory_dir") or "").strip()
        assets_raw = str(payload.get("character_assets_dir") or "").strip()
        new_memory = resolve_storage_path(
            memory_raw, root=self.paths.root, fallback=default_character_memory_dir(self.paths.root)
        )
        new_assets = resolve_storage_path(
            assets_raw, root=self.paths.root, fallback=default_character_assets_dir(self.paths.root)
        )
        copy_memory = bool(payload.get("copy_memory", True))
        copy_assets = bool(payload.get("copy_assets", True))
        if copy_memory and is_strict_child(new_memory, old_memory):
            raise ValueError("新的角色记忆目录不能位于旧目录内部。")
        if copy_assets and is_strict_child(new_assets, old_assets):
            raise ValueError("新的角色资产目录不能位于旧目录内部。")
        saved = False
        try:
            new_memory.mkdir(parents=True, exist_ok=True)
            new_assets.mkdir(parents=True, exist_ok=True)
            value = save_storage_paths(
                character_memory_dir=memory_raw,
                character_assets_dir=assets_raw,
                root=self.paths.root,
            )
            saved = True
            migrate_storage_locations(
                old_memory_dir=old_memory,
                old_assets_dir=old_assets,
                new_memory_dir=new_memory,
                new_assets_dir=new_assets,
                config_manager=self.config,
                copy_memory=copy_memory,
                copy_assets=copy_assets,
            )
            self.reload_runtime()
            return model_json(value.__dict__)
        except Exception:
            if saved:
                save_storage_paths(
                    character_memory_dir=old_config.character_memory_dir,
                    character_assets_dir=old_config.character_assets_dir,
                    root=self.paths.root,
                )
                self.config.reload()
            raise

    def import_legacy(self, payload: dict[str, Any]) -> dict[str, Any]:
        selected = Path(str(payload.get("source_path") or "")).expanduser().resolve()
        candidates = [selected / ".local" / "here", selected]
        source = next(
            (path for path in candidates if (path / "config" / "system_config.yaml").is_file()),
            None,
        )
        if source is None:
            raise ValueError("没有找到旧版 config/system_config.yaml。")
        if source == self.paths.root.resolve():
            raise ValueError("所选目录已经是 Electron 数据目录。")
        copied: list[str] = []
        for name in ("config", "memory", "characters", "backgrounds", "state", "character_templates"):
            origin = source / name
            if not origin.exists():
                continue
            destination = self.paths.root / name
            if origin.is_dir():
                shutil.copytree(origin, destination, dirs_exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(origin, destination)
            copied.append(name)
        self.reload_runtime()
        return {
            "sourcePath": str(source),
            "charactersImported": len(self.config.config.characters),
            "settingsImported": "config" in copied,
            "warnings": [
                "旧数据已复制到 Electron 目录；原目录未被修改。",
                "Hermes 自身的全局配置仍由本机 Hermes 安装管理。",
            ],
            "copied": copied,
        }

    def resolve_assets(self, payload: dict[str, Any]) -> dict[str, Any]:
        name = str(payload.get("character_name") or self.config.resolve_active_character_name())
        character = self.config.get_character_by_name(name)
        if character is None:
            return {"sprites": []}
        sprites = []
        for index, sprite in enumerate(character.sprites):
            raw = model_json(sprite)
            raw["index"] = index
            raw["path"] = resolve_character_asset_path(raw.get("path"), self.paths).as_posix()
            raw["frames"] = [
                resolve_character_asset_path(path, self.paths).as_posix()
                for path in raw.get("frames", [])
            ]
            if raw.get("spritesheet_path"):
                raw["spritesheet_path"] = resolve_character_asset_path(raw["spritesheet_path"], self.paths).as_posix()
            sprites.append(raw)
        return {"name": name, "scale": character.sprite_scale, "color": character.color, "sprites": sprites}

    def shutdown(self) -> None:
        self._shutdown_runtime()


def dispatch(backend: HereBackend, method: str, params: dict[str, Any]) -> Any:
    methods = {
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
