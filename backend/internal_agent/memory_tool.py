from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from internal_agent.memory import ENTRY_DELIMITER, bullet_items, read_text


def schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "memory",
            "description": (
                "Save durable information to the current character memory. "
                "Use this proactively for stable user preferences, corrections, "
                "relationship facts, role facts, or project/environment facts that "
                "will matter in future conversations. Do not save transient task "
                "progress or ordinary chat logs."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "action": {
                        "type": "string",
                        "enum": ["add", "replace", "remove"],
                        "description": "Memory operation to perform.",
                    },
                    "target": {
                        "type": "string",
                        "enum": ["memory", "user"],
                        "description": "'memory' for character notes, 'user' for user profile.",
                    },
                    "content": {
                        "type": "string",
                        "description": "New memory text for add/replace.",
                    },
                    "old_text": {
                        "type": "string",
                        "description": "Unique substring identifying the entry to replace/remove.",
                    },
                },
                "required": ["action", "target"],
            },
        },
    }


def run(
    *,
    action: str,
    target: str = "memory",
    content: str | None = None,
    old_text: str | None = None,
    memory_home: str | Path | None = None,
) -> str:
    if memory_home is None:
        return _dump(False, error="No active memory home.")
    if target not in {"memory", "user"}:
        return _dump(False, error="Invalid target. Use 'memory' or 'user'.")

    path = _path_for_target(Path(memory_home).expanduser(), target)
    entries = _read_entries(path)
    action = str(action or "").strip().lower()
    content = str(content or "").strip()
    old_text = str(old_text or "").strip()

    if action == "add":
        if not content:
            return _dump(False, error="content is required for add.")
        if content not in entries:
            entries.append(content)
            _write_entries(path, entries)
        return _dump(True, action=action, target=target, count=len(entries))

    if action == "replace":
        if not old_text:
            return _dump(False, error="old_text is required for replace.")
        if not content:
            return _dump(False, error="content is required for replace.")
        index = _find_entry(entries, old_text)
        if index < 0:
            return _dump(False, error="No matching memory entry found.")
        entries[index] = content
        _write_entries(path, _dedupe(entries))
        return _dump(True, action=action, target=target, count=len(entries))

    if action == "remove":
        if not old_text:
            return _dump(False, error="old_text is required for remove.")
        index = _find_entry(entries, old_text)
        if index < 0:
            return _dump(False, error="No matching memory entry found.")
        removed = entries.pop(index)
        _write_entries(path, entries)
        return _dump(True, action=action, target=target, removed=removed, count=len(entries))

    return _dump(False, error="Unknown action. Use add, replace, or remove.")


def _path_for_target(home: Path, target: str) -> Path:
    filename = "USER.md" if target == "user" else "MEMORY.md"
    return home / "memories" / filename


def _read_entries(path: Path) -> list[str]:
    return _dedupe(bullet_items(read_text(path)))


def _write_entries(path: Path, entries: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clean = _dedupe(entries)
    body = ENTRY_DELIMITER.join(clean)
    path.write_text(body + ("\n" if body else ""), encoding="utf-8")


def _find_entry(entries: list[str], needle: str) -> int:
    for index, entry in enumerate(entries):
        if needle == entry or needle in entry:
            return index
    return -1


def _dedupe(entries: list[str]) -> list[str]:
    seen: set[str] = set()
    clean: list[str] = []
    for entry in entries:
        text = str(entry or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        clean.append(text)
    return clean


def _dump(success: bool, **payload: Any) -> str:
    return json.dumps({"success": success, **payload}, ensure_ascii=False)
