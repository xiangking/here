from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import requests


@dataclass(frozen=True)
class TelegramChatCandidate:
    chat_id: str
    update_id: int
    display_name: str = ""
    username: str = ""
    text: str = ""

    @property
    def description(self) -> str:
        parts = [self.chat_id]
        name = self.display_name.strip()
        username = self.username.strip()
        if username and not username.startswith("@"):
            username = f"@{username}"
        extra = " ".join(part for part in (name, username) if part)
        if extra:
            parts.append(f"({extra})")
        return " ".join(parts)


@dataclass(frozen=True)
class TelegramChatDiscoveryResult:
    candidate: TelegramChatCandidate | None = None
    reason: str = "ready"

    @property
    def chat_id(self) -> str:
        return self.candidate.chat_id if self.candidate is not None else ""

    @property
    def description(self) -> str:
        return self.candidate.description if self.candidate is not None else ""


def discover_next_private_chat_id(
    token: str,
    *,
    timeout_seconds: float = 30,
    poll_timeout_seconds: int = 3,
    should_stop: Callable[[], bool] | None = None,
    request_get: Callable[..., Any] = requests.get,
) -> TelegramChatDiscoveryResult:
    token = str(token or "").strip()
    if not token:
        return TelegramChatDiscoveryResult(reason="missing_token")
    url = f"https://api.telegram.org/bot{token}/getUpdates"
    stop_requested = should_stop or (lambda: False)
    initial = _fetch_updates(url, timeout=0, request_timeout=5, request_get=request_get)
    if initial.reason != "ready":
        return TelegramChatDiscoveryResult(reason=initial.reason)
    offset = _next_offset(initial.data)
    deadline = time.monotonic() + max(1.0, float(timeout_seconds))
    last_reason = "timeout"
    while not stop_requested() and time.monotonic() < deadline:
        remaining = max(1, int(min(float(poll_timeout_seconds), deadline - time.monotonic())))
        fetched = _fetch_updates(
            url,
            timeout=remaining,
            offset=offset,
            request_timeout=remaining + 2,
            request_get=request_get,
        )
        if fetched.reason != "ready":
            return TelegramChatDiscoveryResult(reason=fetched.reason)
        updates = fetched.data.get("result") or []
        for update in updates:
            if isinstance(update, dict):
                try:
                    offset = max(offset, int(update.get("update_id", 0) or 0) + 1)
                except (TypeError, ValueError):
                    pass
            candidate = private_chat_candidate(update)
            if candidate is not None:
                _fetch_updates(url, timeout=0, offset=candidate.update_id + 1, request_timeout=5, request_get=request_get)
                return TelegramChatDiscoveryResult(candidate=candidate)
        last_reason = "no_private_message"
    return TelegramChatDiscoveryResult(reason="cancelled" if stop_requested() else last_reason)


def private_chat_candidate(update: Any) -> TelegramChatCandidate | None:
    if not isinstance(update, dict):
        return None
    message = update.get("message")
    if not isinstance(message, dict):
        return None
    chat = message.get("chat")
    if not isinstance(chat, dict) or str(chat.get("type") or "").lower() != "private":
        return None
    chat_id = str(chat.get("id") or "").strip()
    if not chat_id:
        return None
    try:
        update_id = int(update.get("update_id", 0) or 0)
    except (TypeError, ValueError):
        update_id = 0
    display_name = " ".join(
        part
        for part in (
            str(chat.get("first_name") or "").strip(),
            str(chat.get("last_name") or "").strip(),
        )
        if part
    )
    return TelegramChatCandidate(
        chat_id=chat_id,
        update_id=update_id,
        display_name=display_name,
        username=str(chat.get("username") or "").strip(),
        text=str(message.get("text") or "").strip(),
    )


@dataclass(frozen=True)
class _FetchResult:
    data: dict[str, Any]
    reason: str = "ready"


def _fetch_updates(
    url: str,
    *,
    timeout: int,
    request_timeout: float,
    request_get: Callable[..., Any],
    offset: int | None = None,
) -> _FetchResult:
    params: dict[str, Any] = {"timeout": timeout, "allowed_updates": '["message"]'}
    if offset is not None:
        params["offset"] = offset
    try:
        response = request_get(url, params=params, timeout=request_timeout)
        data = response.json()
    except Exception as exc:
        return _FetchResult({}, f"request_error:{exc.__class__.__name__}")
    if not isinstance(data, dict):
        return _FetchResult({}, "telegram_error:invalid_response")
    if not data.get("ok"):
        return _FetchResult(data, f"telegram_error:{data.get('description') or data}")
    return _FetchResult(data)


def _next_offset(data: dict[str, Any]) -> int:
    update_ids: list[int] = []
    for update in data.get("result") or []:
        if not isinstance(update, dict):
            continue
        try:
            update_ids.append(int(update.get("update_id", 0) or 0))
        except (TypeError, ValueError):
            pass
    return max(update_ids, default=-1) + 1
