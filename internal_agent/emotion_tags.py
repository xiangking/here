from __future__ import annotations

import re
from typing import Any


_SPRITE_ID_RE = re.compile(r"(?:立绘|sprite|Sprite)\s*0*([0-9]+)", re.IGNORECASE)


def sprite_count(character: Any) -> int:
    return len(getattr(character, "sprites", []) or [])


def filter_emotion_tags_for_character(character: Any) -> str:
    return filter_emotion_tags(
        str(getattr(character, "emotion_tags", "") or ""),
        sprite_count(character),
    )


def filter_emotion_tags(emotion_tags: str, available_sprites: int) -> str:
    text = str(emotion_tags or "").strip()
    if not text:
        return ""
    if available_sprites <= 0:
        return "\n".join(_untagged_lines(text))

    kept: list[str] = []
    for line in text.splitlines():
        raw = line.rstrip()
        if not raw.strip():
            if kept and kept[-1] != "":
                kept.append("")
            continue
        ids = [int(m.group(1)) for m in _SPRITE_ID_RE.finditer(raw)]
        if ids and any(sprite_id < 1 or sprite_id > available_sprites for sprite_id in ids):
            continue
        kept.append(raw)
    return "\n".join(_trim_blank_edges(kept)).strip()


def _untagged_lines(text: str) -> list[str]:
    return [
        line.rstrip()
        for line in text.splitlines()
        if line.strip() and not _SPRITE_ID_RE.search(line)
    ]


def _trim_blank_edges(lines: list[str]) -> list[str]:
    start = 0
    end = len(lines)
    while start < end and not lines[start].strip():
        start += 1
    while end > start and not lines[end - 1].strip():
        end -= 1
    return lines[start:end]
