from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from core.sprite.emotion_resolver import DEFAULT_EMOTION, resolve_sprite_index
from services.config.config_manager import SYSTEM_CHARACTER_NAME


SYSTEM_WELCOME_EMOTION = "welcome"


@dataclass(frozen=True)
class CharacterEntrySprite:
    asset_id: str
    emotion: str


def character_entry_line(character_name: str) -> str:
    name = str(character_name or "").strip()
    if name == SYSTEM_CHARACTER_NAME:
        return "我在。需要调整设置的话，直接告诉我。"
    return "你来啦。今天想聊什么？"


def character_entry_sprite(character_name: str, config_manager: Any) -> CharacterEntrySprite:
    name = str(character_name or "").strip()
    emotion = SYSTEM_WELCOME_EMOTION if name == SYSTEM_CHARACTER_NAME else DEFAULT_EMOTION
    sprite_id = _resolve_entry_sprite_id(name, emotion, config_manager)
    return CharacterEntrySprite(asset_id=str(sprite_id + 1) if sprite_id >= 0 else "1", emotion=emotion)


def _resolve_entry_sprite_id(character_name: str, emotion: str, config_manager: Any) -> int:
    try:
        character = config_manager.get_character_by_name(character_name)
    except Exception:
        return 0
    if character is None:
        return 0
    try:
        return max(0, resolve_sprite_index(character, emotion))
    except Exception:
        return 0
