from __future__ import annotations

import json
import threading
from datetime import datetime, timedelta
from typing import Any

from core.timezone import DEFAULT_FALLBACK_TIMEZONE, now_in_timezone, resolve_timezone
from internal_agent.context import AgentMemoryStore
from internal_agent.context import memory_slug
from internal_agent.session_store import SessionStore


class MemoryDreamer:
    """Daily, best-effort consolidation of recent sessions into memory files."""

    def __init__(
        self,
        memory: AgentMemoryStore,
        agent: Any,
        sessions: SessionStore | None = None,
        timezone: str = DEFAULT_FALLBACK_TIMEZONE,
    ) -> None:
        self.memory = memory
        self.agent = agent
        self.sessions = sessions or SessionStore(memory.root)
        self.timezone = timezone or DEFAULT_FALLBACK_TIMEZONE
        self._lock = threading.Lock()

    def current_dream_date(self, now: datetime | None = None) -> str:
        tz = resolve_timezone(self.timezone)
        current = (now or now_in_timezone(self.timezone)).astimezone(tz)
        return current.date().isoformat()

    def run(self, character: Any, *, min_sessions: int = 1, limit: int = 8, now: datetime | None = None) -> bool:
        if not self._lock.acquire(blocking=False):
            return False
        try:
            name = str(getattr(character, "name", "") or "角色").strip() or "角色"
            marker = self.memory.agent_home(name) / ".dream-date"
            today = self.current_dream_date(now)
            try:
                if marker.read_text(encoding="utf-8").strip() == today:
                    return False
            except OSError:
                pass
            sessions = self.sessions.list_sessions(
                limit=max(limit, min_sessions),
                character_name=memory_slug(name),
            )
            sessions = [s for s in sessions if s.get("message_count", 0) > 0][:limit]
            if len(sessions) < min_sessions:
                return False
            transcripts = []
            for item in sessions:
                sid = str(item.get("id") or "")
                if sid:
                    messages = self.sessions.get_messages_as_conversation(sid)
                    text = "\n".join(f"{m.get('role')}: {m.get('content', '')}" for m in messages if m.get("content"))
                    if text:
                        transcripts.append(text[-6000:])
            if not transcripts:
                return False
            existing_character = self.memory.read_character_memories(name)
            existing_user = self.memory.read_user_profile(name)
            prompt = (
                "请整理以下近期对话中的长期信息。只保留稳定的偏好、约定、纠正和角色事实；忽略一次性任务、敏感信息和普通闲聊。"
                "不要复述已有条目，只输出对现有记忆的新增内容。严格只输出 JSON："
                '{"character":["新增角色长期记忆"],"user":["新增用户稳定偏好"]}。\n\n'
                "已有角色记忆：\n" + json.dumps(existing_character, ensure_ascii=False) + "\n"
                "已有用户记忆：\n" + json.dumps(existing_user, ensure_ascii=False) + "\n\n"
                "近期对话：\n" + "\n---\n".join(transcripts)
            )
            raw = self.agent.oneshot(prompt, system_prompt="你是记忆整理助手。输出必须是合法 JSON。", tools=False)
            start, end = str(raw).find("{"), str(raw).rfind("}")
            if start < 0 or end <= start:
                return False
            data = json.loads(str(raw)[start : end + 1])
            if not isinstance(data, dict):
                return False
            memory_targets = (
                ("character", existing_character, self.memory.write_character_memories),
                ("user", existing_user, self.memory.write_user_profile),
            )
            for key, existing, writer in memory_targets:
                values = data.get(key)
                if isinstance(values, list):
                    clean = [str(v).strip() for v in values if str(v).strip() and len(str(v).strip()) <= 240]
                    if clean:
                        merged = list(existing)
                        seen = {_memory_key(value) for value in merged}
                        for value in clean:
                            normalized = _memory_key(value)
                            if normalized not in seen:
                                merged.append(value)
                                seen.add(normalized)
                        writer(name, merged[-100:])
            marker.parent.mkdir(parents=True, exist_ok=True)
            marker.write_text(today + "\n", encoding="utf-8")
            return True
        except Exception as exc:
            print(f"MemoryDreamer: 记忆整理失败: {exc}")
            return False
        finally:
            self._lock.release()


def _memory_key(value: str) -> str:
    return "".join(str(value).split()).casefold()


class DreamScheduler:
    def __init__(
        self,
        config_manager: Any,
        dreamer: MemoryDreamer,
        timezone: str = DEFAULT_FALLBACK_TIMEZONE,
    ) -> None:
        self.config_manager = config_manager
        self.dreamer = dreamer
        self.timezone = timezone or DEFAULT_FALLBACK_TIMEZONE
        if hasattr(self.dreamer, "timezone"):
            self.dreamer.timezone = self.timezone
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="DreamScheduler", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)

    def next_run_at(self, now: datetime | None = None) -> datetime:
        tz = resolve_timezone(self.timezone)
        current = (now or now_in_timezone(self.timezone)).astimezone(tz)
        tomorrow = (current + timedelta(days=1)).date()
        return datetime.combine(tomorrow, datetime.min.time(), tzinfo=tz) + timedelta(seconds=5)

    def _run(self) -> None:
        self._dream_all()
        while not self._stop.is_set():
            delay = max(1.0, (self.next_run_at() - now_in_timezone(self.timezone)).total_seconds())
            if self._stop.wait(delay):
                return
            self._dream_all()

    def _dream_all(self) -> None:
        for character in list(getattr(self.config_manager.config, "characters", []) or []):
            self.dreamer.run(character)
