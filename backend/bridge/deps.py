"""Shared imports for split ``HereBackend`` helpers.

Patched ``rpc_bridge`` symbols (``event``, ASR factories, storage migration,
chat-platform bridge start/stop) are intentionally *not* imported here. Method
bodies read them through ``bridge.hooks`` so tests can keep patching the
sidecar module.
"""

from __future__ import annotations

import base64
import hashlib
import importlib
import io
import json
import mimetypes
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
from pathlib import Path
from typing import Any

from core.agent import create_agent_backend
from core.agent.multimodal import build_hermes_user_message
from core.delivery import (
    DeliveryAdapterRegistry,
    DeliveryCapabilityProbe,
    DeliveryRouter,
    DesktopDeliveryAdapter,
    MessagingDeliveryAdapter,
)
from core.delivery.messaging import MessageSender, MessagingConfig, create_default_registry
from core.delivery.messaging.telegram_discovery import discover_next_private_chat_id
from core.delivery.messaging.wechat_openclaw import api as wechat_api
from core.delivery.messaging.wechat_openclaw import state as wechat_state
from core.delivery.models import DeliveryMessage
from core.importers.codex_pet_importer import find_codex_pet_dirs, import_codex_pet_as_character
from core.life import DailyLifeScheduler, LifeEngine
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
from core.messaging.messages import AgentDialogMessage
from core.messaging.stream_parser import AgentResponseStreamParser
from core.proactive import ContactPlanEngine, ProactiveContactScheduler
from core.sprite.character_profile import default_character_profile, normalize_character_profile
from core.sprite.emotion_resolver import resolve_sprite_index
from core.sprite.text_processor import TextProcessor, name_map
from infrastructure.paths import (
    default_character_assets_dir,
    default_character_memory_dir,
    get_app_paths,
    install_user_python_packages_path,
    load_storage_paths,
    resolve_character_asset_path,
    resolve_storage_path,
    save_storage_paths,
    seed_defaults,
)
from internal_agent.context import AgentMemoryStore, build_agent_context
from internal_agent.dream import DreamScheduler, MemoryDreamer
from services.asr.asr_adapter import (
    default_vosk_model_path,
    is_vosk_model_dir,
    normalize_asr_provider_storage_key,
)
from services.config.character_manager import CharacterManager
from services.config.config_manager import ConfigManager, SYSTEM_CHARACTER_NAME, is_placeholder_character_name
from services.config.schema import ApiConfig, Character, Sprite, SystemConfig
from services.selfie import SelfieRequest
from services.selfie.factory import build_selfie_runtime
from services.storage_migration import is_strict_child
from services.t2i.t2i_manager import T2IAdapterFactory, T2IManager
from services.tts.tts_manager import TTSAdapterFactory, TTSManager
