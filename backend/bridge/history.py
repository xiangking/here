from __future__ import annotations

from typing import Any

from bridge import hooks
from bridge.deps import json, uuid


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
    hooks.event("history_reverted", {"history": reverted, "display": display})
    return {"history": reverted, "display": display}
