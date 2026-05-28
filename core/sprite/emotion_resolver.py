from __future__ import annotations

import re
from typing import Any


DEFAULT_EMOTION = "neutral"
CORE_EMOTIONS = ("neutral", "happy", "thinking", "surprised", "sad", "angry")

_ALIASES = {
    "idle": "neutral",
    "default": "neutral",
    "normal": "neutral",
    "calm": "neutral",
    "joy": "happy",
    "smile": "happy",
    "glad": "happy",
    "wait": "thinking",
    "waiting": "thinking",
    "think": "thinking",
    "thoughtful": "thinking",
    "jump": "surprised",
    "jumping": "surprised",
    "shock": "surprised",
    "shocked": "surprised",
    "failed": "sad",
    "unhappy": "sad",
    "mad": "angry",
    "upset": "angry",
}


def normalize_emotion(value: Any) -> str:
    text = str(value or "").strip().lower()
    text = re.sub(r"[^a-z0-9_\-]+", "_", text).strip("_-")
    return _ALIASES.get(text, text) or DEFAULT_EMOTION


def resolve_sprite_index(character: Any, emotion: str) -> int:
    """Resolve a here emotion name to a zero-based sprite index."""
    sprites = list(getattr(character, "sprites", []) or [])
    if not sprites:
        return -1

    wanted = normalize_emotion(emotion)
    fallback = 0
    for idx, sprite in enumerate(sprites):
        state_name = normalize_emotion(_sprite_value(sprite, "state_name"))
        if state_name == DEFAULT_EMOTION:
            fallback = idx
        if state_name and state_name == wanted:
            return idx

    tag_match = _resolve_from_emotion_tags(character, wanted)
    if tag_match >= 0 and tag_match < len(sprites):
        return tag_match
    return fallback


def _sprite_value(sprite: Any, key: str) -> Any:
    if isinstance(sprite, dict):
        return sprite.get(key)
    return getattr(sprite, key, "")


def _resolve_from_emotion_tags(character: Any, emotion: str) -> int:
    tags = str(getattr(character, "emotion_tags", "") or "")
    if not tags.strip():
        return -1
    for line in tags.splitlines():
        if normalize_emotion(emotion) not in _emotion_words(line):
            continue
        match = re.search(r"(?:立绘|sprite|Sprite)\s*0*([0-9]+)", line, flags=re.IGNORECASE)
        if match:
            return int(match.group(1)) - 1
    return -1


def _emotion_words(line: str) -> set[str]:
    words = set()
    for token in re.split(r"[^A-Za-z0-9_\-]+", line):
        normalized = normalize_emotion(token)
        if normalized:
            words.add(normalized)
    return words
