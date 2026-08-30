from __future__ import annotations

import re
from pathlib import Path


ENTRY_DELIMITER = "\n§\n"


def read_text(path: Path) -> str:
    try:
        if path.is_file():
            return path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""
    return ""


def bullet_items(text: str) -> list[str]:
    if ENTRY_DELIMITER in text:
        return [part.strip() for part in text.split(ENTRY_DELIMITER) if part.strip()]
    items = [
        re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()
        for line in text.splitlines()
    ]
    return [item for item in items if item and not item.startswith("#")]


def format_memory_file(path: Path, title: str) -> str:
    text = read_text(path)
    if not text:
        return ""
    items = bullet_items(text)
    if not items:
        return ""
    return f"【{title}】\n" + "\n".join(f"- {item}" for item in items)


def build_identity_prompt(
    *,
    memory_home: str | Path | None,
    load_soul_identity: bool,
    skip_memory: bool,
) -> str:
    if memory_home is None:
        return ""
    home = Path(memory_home).expanduser()
    parts: list[str] = []
    if load_soul_identity:
        soul = read_text(home / "SOUL.md")
        if soul:
            parts.append(soul)
    if not skip_memory:
        memory = format_memory_file(home / "memories" / "MEMORY.md", "长期记忆")
        user = format_memory_file(home / "memories" / "USER.md", "用户画像")
        parts.extend(part for part in (memory, user) if part)
    return "\n\n".join(parts)
