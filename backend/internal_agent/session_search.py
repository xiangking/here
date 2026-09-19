from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from internal_agent.session_store import SessionStore


def schema() -> dict[str, Any]:
    return {
        "type": "function",
        "function": {
            "name": "session_search",
            "description": (
                "Search past conversation sessions, or list recent sessions when query is empty. "
                "Use this for cross-session recall. The current conversation is already in context; "
                "do not use this to answer what was said a moment ago in the same active turn."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Keywords to search in past sessions. Omit or pass empty to list recent sessions.",
                    },
                    "role_filter": {
                        "type": "string",
                        "description": "Optional comma-separated roles, e.g. user,assistant.",
                    },
                    "limit": {"type": "integer", "default": 3},
                },
                "required": [],
            },
        },
    }


def search(
    query: str = "",
    limit: int = 3,
    *,
    memory_home: str | Path | None = None,
    session_store: SessionStore | None = None,
    current_session_id: str | None = None,
    role_filter: str | None = None,
    character_name: str | None = None,
) -> str:
    store = session_store or _store_from_memory_home(memory_home)
    if store is None:
        return _dump(False, error="Session database is not available.")

    try:
        limit = max(1, min(int(limit or 3), 5))
    except (TypeError, ValueError):
        limit = 3

    query = str(query or "").strip()
    if not query:
        sessions = store.list_sessions(
            limit=limit,
            exclude_session_id=current_session_id,
            character_name=character_name,
        )
        return _dump(
            True,
            mode="recent",
            count=len(sessions),
            results=[
                {
                    "session_id": item.get("id"),
                    "source": item.get("source"),
                    "started_at": item.get("started_at"),
                    "message_count": item.get("message_count"),
                    "preview": item.get("preview") or "",
                }
                for item in sessions
            ],
        )

    roles = [role.strip() for role in str(role_filter or "").split(",") if role.strip()] or None
    rows = store.search_messages(
        query,
        role_filter=roles,
        character_name=character_name,
        limit=50,
    )
    sessions: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        sid = str(row.get("session_id") or "")
        if not sid or sid == current_session_id:
            continue
        sessions.setdefault(sid, []).append(row)
        if len(sessions) >= limit:
            break

    results = []
    for sid, matches in sessions.items():
        meta = store.get_session(sid) or {}
        messages = store.get_messages_as_conversation(sid)
        transcript = _format_conversation(messages)
        results.append(
            {
                "session_id": sid,
                "source": meta.get("source"),
                "started_at": meta.get("started_at"),
                "matched_messages": len(matches),
                "summary": _snippet(transcript, query),
            }
        )
    return _dump(True, query=query, count=len(results), results=results)


def _store_from_memory_home(memory_home: str | Path | None) -> SessionStore | None:
    if memory_home is None:
        return None
    home = Path(memory_home).expanduser()
    root = home.parent.parent if home.name else home
    return SessionStore(root)


def _format_conversation(messages: list[dict[str, Any]]) -> str:
    lines = []
    for message in messages:
        role = str(message.get("role") or "unknown").upper()
        content = str(message.get("content") or "")
        if role == "ASSISTANT" and message.get("tool_calls"):
            names = []
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict):
                    names.append(str((tool_call.get("function") or {}).get("name") or "?"))
            if names:
                lines.append(f"[ASSISTANT]: [Called: {', '.join(names)}]")
        if content:
            lines.append(f"[{role}]: {content}")
    return "\n\n".join(lines)


def _snippet(text: str, query: str, radius: int = 500) -> str:
    lower = text.lower()
    terms = [term.lower() for term in query.split() if term.strip()]
    pos = -1
    for term in terms or [query.lower()]:
        pos = lower.find(term)
        if pos >= 0:
            break
    if pos < 0:
        return text[: radius * 2]
    start = max(0, pos - radius)
    end = min(len(text), pos + radius)
    return text[start:end]


def _dump(success: bool, **payload: Any) -> str:
    return json.dumps({"success": success, **payload}, ensure_ascii=False)
