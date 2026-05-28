from __future__ import annotations

import json
import os
from pathlib import Path

from infrastructure.paths import get_app_paths
from typing import Any

from core.delivery.messaging.wechat_openclaw.models import DEFAULT_BASE_URL, WeChatAccount


def state_dir() -> Path:
    override = os.environ.get("HERE_WECHAT_STATE_DIR", "").strip()
    root = Path(override).expanduser() if override else get_app_paths().messaging_state_dir / "wechat"
    root.mkdir(parents=True, exist_ok=True)
    (root / "accounts").mkdir(parents=True, exist_ok=True)
    return root


def accounts_dir() -> Path:
    return state_dir() / "accounts"


def account_index_path() -> Path:
    return state_dir() / "accounts.json"


def sync_path(account_id: str) -> Path:
    return accounts_dir() / f"{_safe_name(account_id)}.sync.json"


def context_tokens_path(account_id: str) -> Path:
    return accounts_dir() / f"{_safe_name(account_id)}.context-tokens.json"


def inbound_debug_path(account_id: str) -> Path:
    return accounts_dir() / f"{_safe_name(account_id)}.inbound-debug.jsonl"


def account_path(account_id: str) -> Path:
    return accounts_dir() / f"{_safe_name(account_id)}.json"


def list_account_ids() -> list[str]:
    data = _read_json(account_index_path(), [])
    return [str(item) for item in data] if isinstance(data, list) else []


def save_account(account: WeChatAccount) -> None:
    path = account_path(account.account_id)
    path.write_text(json.dumps({
        "account_id": account.account_id,
        "token": account.token,
        "base_url": account.base_url,
        "user_id": account.user_id,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    ids = list_account_ids()
    if account.account_id not in ids:
        ids.append(account.account_id)
        account_index_path().write_text(json.dumps(ids, ensure_ascii=False, indent=2), encoding="utf-8")


def replace_accounts(account: WeChatAccount) -> None:
    for account_id in list_account_ids():
        if account_id == account.account_id:
            continue
        for path in (account_path(account_id), sync_path(account_id), context_tokens_path(account_id)):
            try:
                path.unlink()
            except FileNotFoundError:
                pass
    save_account(account)
    account_index_path().write_text(json.dumps([account.account_id], ensure_ascii=False, indent=2), encoding="utf-8")


def load_account(account_id: str = "") -> WeChatAccount | None:
    wanted = account_id.strip()
    if not wanted:
        ids = list_account_ids()
        wanted = ids[0] if ids else ""
    if not wanted:
        return None
    data = _read_json(account_path(wanted), {})
    if not isinstance(data, dict):
        return None
    token = str(data.get("token") or "").strip()
    if not token:
        return None
    return WeChatAccount(
        account_id=str(data.get("account_id") or wanted),
        token=token,
        base_url=str(data.get("base_url") or DEFAULT_BASE_URL),
        user_id=str(data.get("user_id") or ""),
    )


def load_sync_buf(account_id: str) -> str:
    data = _read_json(sync_path(account_id), {})
    return str(data.get("get_updates_buf") or "") if isinstance(data, dict) else ""


def save_sync_buf(account_id: str, value: str) -> None:
    sync_path(account_id).write_text(json.dumps({"get_updates_buf": value}, ensure_ascii=False), encoding="utf-8")


def set_context_token(account_id: str, user_id: str, token: str) -> None:
    if not account_id or not user_id or not token:
        return
    data = _read_json(context_tokens_path(account_id), {})
    tokens = data if isinstance(data, dict) else {}
    tokens[user_id] = token
    context_tokens_path(account_id).write_text(json.dumps(tokens, ensure_ascii=False), encoding="utf-8")


def get_context_token(account_id: str, user_id: str) -> str:
    data = _read_json(context_tokens_path(account_id), {})
    if not isinstance(data, dict):
        return ""
    return str(data.get(user_id) or "")


def list_context_user_ids(account_id: str) -> list[str]:
    data = _read_json(context_tokens_path(account_id), {})
    if not isinstance(data, dict):
        return []
    return sorted(str(key) for key, value in data.items() if key and value)


def append_inbound_debug(account_id: str, raw_message: dict[str, Any]) -> None:
    if not account_id or not isinstance(raw_message, dict):
        return
    payload = _redact_for_debug(raw_message)
    payload["_captured_at"] = __import__("time").time()
    path = inbound_debug_path(account_id)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n")
    try:
        path.chmod(0o600)
    except OSError:
        pass


def _read_json(path: Path, default: Any) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _redact_for_debug(value: Any) -> Any:
    if isinstance(value, dict):
        redacted = {}
        for key, item in value.items():
            key_text = str(key)
            lowered = key_text.lower()
            if any(part in lowered for part in ("token", "ticket", "authorization", "cookie")):
                redacted[key_text] = "***"
            else:
                redacted[key_text] = _redact_for_debug(item)
        return redacted
    if isinstance(value, list):
        return [_redact_for_debug(item) for item in value]
    return value


def _safe_name(value: str) -> str:
    safe = "".join(ch if ch.isalnum() or ch in {"@", ".", "-", "_"} else "_" for ch in value.strip())
    return safe or "default"
