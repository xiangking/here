from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any


SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id TEXT PRIMARY KEY,
    source TEXT NOT NULL,
    model TEXT,
    system_prompt TEXT,
    parent_session_id TEXT,
    started_at REAL NOT NULL,
    ended_at REAL,
    end_reason TEXT,
    message_count INTEGER DEFAULT 0,
    tool_call_count INTEGER DEFAULT 0,
    title TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id TEXT NOT NULL REFERENCES sessions(id),
    role TEXT NOT NULL,
    content TEXT,
    tool_call_id TEXT,
    tool_calls TEXT,
    tool_name TEXT,
    timestamp REAL NOT NULL,
    finish_reason TEXT,
    reasoning TEXT,
    reasoning_content TEXT
);

CREATE INDEX IF NOT EXISTS idx_sessions_started ON sessions(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_messages_session ON messages(session_id, timestamp, id);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(content);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts_trigram USING fts5(content, tokenize='trigram');

CREATE TRIGGER IF NOT EXISTS messages_fts_insert AFTER INSERT ON messages BEGIN
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
    INSERT INTO messages_fts_trigram(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_delete AFTER DELETE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
    DELETE FROM messages_fts_trigram WHERE rowid = old.id;
END;
CREATE TRIGGER IF NOT EXISTS messages_fts_update AFTER UPDATE ON messages BEGIN
    DELETE FROM messages_fts WHERE rowid = old.id;
    DELETE FROM messages_fts_trigram WHERE rowid = old.id;
    INSERT INTO messages_fts(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
    INSERT INTO messages_fts_trigram(rowid, content) VALUES (
        new.id,
        COALESCE(new.content, '') || ' ' || COALESCE(new.tool_name, '') || ' ' || COALESCE(new.tool_calls, '')
    );
END;
"""


class SessionStore:
    """SQLite-backed session store following Hermes' state.db shape in miniature."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "state.db"
        self._conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create_session(
        self,
        session_id: str,
        *,
        source: str = "desktop_chat",
        model: str = "",
        system_prompt: str = "",
        parent_session_id: str | None = None,
        title: str | None = None,
    ) -> None:
        self._conn.execute(
            """
            INSERT OR IGNORE INTO sessions
            (id, source, model, system_prompt, parent_session_id, started_at, title)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (session_id, source, model, system_prompt, parent_session_id, time.time(), title),
        )
        self._conn.commit()

    def replace_messages(self, session_id: str, messages: list[dict[str, Any]]) -> None:
        self.create_session(session_id)
        with self._conn:
            self._conn.execute("DELETE FROM messages WHERE session_id = ?", (session_id,))
            self._conn.execute(
                "UPDATE sessions SET message_count = 0, tool_call_count = 0 WHERE id = ?",
                (session_id,),
            )
            for message in messages:
                self._append_message_uncommitted(session_id, message)

    def append_message(self, session_id: str, message: dict[str, Any]) -> None:
        self.create_session(session_id)
        with self._conn:
            self._append_message_uncommitted(session_id, message)

    def search_messages(
        self,
        query: str,
        *,
        role_filter: list[str] | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        query = str(query or "").strip()
        if not query:
            return []
        role_clause = ""
        role_params: list[Any] = []
        if role_filter:
            placeholders = ",".join("?" for _ in role_filter)
            role_clause = f" AND m.role IN ({placeholders})"
            role_params.extend(role_filter)
        if _contains_cjk(query) and _requires_like_search(query):
            return self._search_messages_like(
                query,
                role_clause=role_clause,
                role_params=role_params,
                limit=limit,
            )
        table, escaped = _search_table_and_query(query)
        params: list[Any] = [escaped, *role_params, int(limit or 50)]
        rows = self._conn.execute(
            f"""
            SELECT m.session_id, m.role, m.content, m.timestamp,
                   s.source, s.model, s.started_at
            FROM {table} f
            JOIN messages m ON m.id = f.rowid
            JOIN sessions s ON s.id = m.session_id
            WHERE {table} MATCH ? {role_clause}
            ORDER BY bm25({table})
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def _search_messages_like(
        self,
        query: str,
        *,
        role_clause: str,
        role_params: list[Any],
        limit: int,
    ) -> list[dict[str, Any]]:
        terms = [
            token
            for token in query.replace('"', " ").split()
            if token.upper() not in {"AND", "OR", "NOT"}
        ] or [query]
        clauses = []
        params: list[Any] = []
        for term in terms:
            pattern = f"%{_like_escape(term)}%"
            clauses.append(
                "(m.content LIKE ? ESCAPE '\\' OR m.tool_name LIKE ? ESCAPE '\\' OR m.tool_calls LIKE ? ESCAPE '\\')"
            )
            params.extend([pattern, pattern, pattern])
        params.extend(role_params)
        params.append(int(limit or 50))
        rows = self._conn.execute(
            f"""
            SELECT m.session_id, m.role, m.content, m.timestamp,
                   s.source, s.model, s.started_at
            FROM messages m
            JOIN sessions s ON s.id = m.session_id
            WHERE ({' OR '.join(clauses)}) {role_clause}
            ORDER BY m.timestamp DESC, m.id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [dict(row) for row in rows]

    def get_session(self, session_id: str) -> dict[str, Any] | None:
        row = self._conn.execute(
            "SELECT * FROM sessions WHERE id = ?", (session_id,)
        ).fetchone()
        return dict(row) if row else None

    def get_messages_as_conversation(self, session_id: str) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT role, content, tool_call_id, tool_calls, tool_name,
                   finish_reason, reasoning, reasoning_content
            FROM messages
            WHERE session_id = ?
            ORDER BY timestamp, id
            """,
            (session_id,),
        ).fetchall()
        messages: list[dict[str, Any]] = []
        for row in rows:
            msg = {
                "role": row["role"],
                "content": _decode_content(row["content"]),
            }
            for key in ("tool_call_id", "tool_name", "finish_reason", "reasoning", "reasoning_content"):
                if row[key]:
                    msg[key] = row[key]
            if row["tool_calls"]:
                try:
                    msg["tool_calls"] = json.loads(row["tool_calls"])
                except json.JSONDecodeError:
                    msg["tool_calls"] = []
            messages.append(msg)
        return messages

    def list_sessions(self, *, limit: int = 5, exclude_session_id: str | None = None) -> list[dict[str, Any]]:
        rows = self._conn.execute(
            """
            SELECT s.*,
                   (SELECT content FROM messages WHERE session_id = s.id ORDER BY timestamp DESC, id DESC LIMIT 1) AS preview
            FROM sessions s
            WHERE (? IS NULL OR s.id != ?)
            ORDER BY COALESCE((SELECT MAX(timestamp) FROM messages WHERE session_id = s.id), s.started_at) DESC
            LIMIT ?
            """,
            (exclude_session_id, exclude_session_id, int(limit or 5)),
        ).fetchall()
        return [dict(row) for row in rows]

    def _append_message_uncommitted(self, session_id: str, message: dict[str, Any]) -> None:
        role = str(message.get("role") or "unknown")
        tool_calls = message.get("tool_calls")
        tool_calls_json = json.dumps(tool_calls, ensure_ascii=False) if tool_calls else None
        content = _encode_content(message.get("content"))
        self._conn.execute(
            """
            INSERT INTO messages
            (session_id, role, content, tool_call_id, tool_calls, tool_name,
             timestamp, finish_reason, reasoning, reasoning_content)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                session_id,
                role,
                content,
                message.get("tool_call_id"),
                tool_calls_json,
                message.get("tool_name") or message.get("name"),
                time.time(),
                message.get("finish_reason"),
                message.get("reasoning"),
                message.get("reasoning_content"),
            ),
        )
        tool_count = len(tool_calls) if isinstance(tool_calls, list) else 0
        self._conn.execute(
            """
            UPDATE sessions
            SET message_count = message_count + 1,
                tool_call_count = tool_call_count + ?
            WHERE id = ?
            """,
            (tool_count, session_id),
        )


def _encode_content(content: Any) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and item.get("type") == "text":
                parts.append(str(item.get("text") or ""))
            elif isinstance(item, dict) and item.get("type") in {"image", "image_url", "input_image"}:
                parts.append("[image]")
            else:
                parts.append(str(item))
        return "\n".join(part for part in parts if part)
    if isinstance(content, dict):
        return json.dumps(content, ensure_ascii=False)
    return str(content)


def _decode_content(content: Any) -> str:
    return "" if content is None else str(content)


def _fts_query(query: str) -> str:
    terms = [term for term in query.replace('"', " ").split() if term]
    if not terms:
        return '""'
    return " OR ".join(f'"{term}"' for term in terms)


def _search_table_and_query(query: str) -> tuple[str, str]:
    text = str(query or "").strip()
    if _contains_cjk(text):
        parts = []
        for token in text.replace('"', " ").split():
            if token.upper() in {"AND", "OR", "NOT"}:
                parts.append(token.upper())
            else:
                parts.append(f'"{token}"')
        return "messages_fts_trigram", " ".join(parts) or '""'
    return "messages_fts", _fts_query(text)


def _contains_cjk(text: str) -> bool:
    return any(_is_cjk_codepoint(ord(ch)) for ch in text)


def _is_cjk_codepoint(codepoint: int) -> bool:
    return (
        0x4E00 <= codepoint <= 0x9FFF
        or 0x3400 <= codepoint <= 0x4DBF
        or 0x20000 <= codepoint <= 0x2A6DF
        or 0x3000 <= codepoint <= 0x303F
        or 0x3040 <= codepoint <= 0x309F
        or 0x30A0 <= codepoint <= 0x30FF
        or 0xAC00 <= codepoint <= 0xD7AF
    )


def _count_cjk(text: str) -> int:
    return sum(1 for ch in text if _is_cjk_codepoint(ord(ch)))


def _requires_like_search(query: str) -> bool:
    text = str(query or "").strip()
    if _count_cjk(text) < 3:
        return True
    tokens = [
        token
        for token in text.replace('"', " ").split()
        if token.upper() not in {"AND", "OR", "NOT"} and _contains_cjk(token)
    ]
    return any(_count_cjk(token) < 3 for token in tokens)


def _like_escape(text: str) -> str:
    return str(text).replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
