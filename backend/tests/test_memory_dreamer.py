from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from core.timezone import resolve_timezone  # noqa: E402
from internal_agent.context import AgentMemoryStore, memory_slug  # noqa: E402
from internal_agent.dream import DreamScheduler, MemoryDreamer  # noqa: E402
from internal_agent.session_store import SessionStore  # noqa: E402


def _zoneinfo_available(name: str) -> bool:
    try:
        from zoneinfo import ZoneInfo

        ZoneInfo(name)
    except Exception:
        return False
    return True


class FakeAgent:
    def __init__(self, response: str) -> None:
        self.response = response
        self.prompts: list[str] = []

    def oneshot(self, prompt: str, **_: object) -> str:
        self.prompts.append(prompt)
        return self.response


class MemoryDreamerTests(unittest.TestCase):
    def test_uses_shared_session_database_and_merges_existing_memories(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            memory = AgentMemoryStore(Path(root) / "memory")
            character = SimpleNamespace(name="角色 A")
            memory.write_character_memories(character.name, ["手工角色记忆"])
            memory.write_user_profile(character.name, ["用户喜欢咖啡"])

            sessions = SessionStore(memory.root)
            sessions.create_session("a-session", character_name=memory_slug(character.name))
            sessions.replace_messages("a-session", [{"role": "user", "content": "我每周跑步"}])
            sessions.create_session("b-session", character_name=memory_slug("角色 B"))
            sessions.replace_messages("b-session", [{"role": "user", "content": "只属于角色 B"}])

            agent = FakeAgent(
                '{"character":["手工角色记忆","新增角色记忆"],'
                '"user":["用户喜欢咖啡","用户每周跑步"]}'
            )
            dreamer = MemoryDreamer(memory, agent)

            self.assertEqual(dreamer.sessions.db_path, memory.root / "state.db")
            self.assertTrue(dreamer.run(character))
            self.assertEqual(
                memory.read_character_memories(character.name),
                ["手工角色记忆", "新增角色记忆"],
            )
            self.assertEqual(
                memory.read_user_profile(character.name),
                ["用户喜欢咖啡", "用户每周跑步"],
            )
            self.assertIn("我每周跑步", agent.prompts[0])
            self.assertNotIn("只属于角色 B", agent.prompts[0])

    def test_migrates_old_database_and_filters_sessions_by_character(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            db_path = Path(root) / "state.db"
            connection = sqlite3.connect(db_path)
            connection.execute(
                """
                CREATE TABLE sessions (
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
                )
                """
            )
            connection.commit()
            connection.close()

            store = SessionStore(root)
            columns = {
                row[1]
                for row in store._conn.execute("PRAGMA table_info(sessions)").fetchall()
            }
            self.assertIn("character_name", columns)

            store.create_session("a", character_name="role_a")
            store.replace_messages("a", [{"role": "user", "content": "shared keyword"}])
            store.create_session("b", character_name="role_b")
            store.replace_messages("b", [{"role": "user", "content": "shared keyword"}])
            store.create_session("legacy")
            store.create_session("legacy", character_name="role_a")

            self.assertEqual(
                {item["id"] for item in store.list_sessions(character_name="role_a")},
                {"a", "legacy"},
            )
            self.assertEqual(
                {item["session_id"] for item in store.search_messages("shared", character_name="role_a")},
                {"a"},
            )
            self.assertEqual(store.get_session("legacy")["character_name"], "role_a")

    def test_dream_date_and_next_run_use_configured_timezone(self) -> None:
        utc = timezone.utc
        now = datetime(2026, 9, 19, 16, 30, tzinfo=utc)  # 2026-09-20 00:30 in Asia/Shanghai
        shanghai = resolve_timezone("Asia/Shanghai")

        with tempfile.TemporaryDirectory() as root:
            memory = AgentMemoryStore(Path(root) / "memory")
            shanghai_dreamer = MemoryDreamer(memory, FakeAgent("{}"), timezone="Asia/Shanghai")
            honolulu_dreamer = MemoryDreamer(memory, FakeAgent("{}"), timezone="Pacific/Honolulu")
            self.assertEqual(shanghai_dreamer.current_dream_date(now), "2026-09-20")
            try:
                from zoneinfo import ZoneInfo
                ZoneInfo("Pacific/Honolulu")
            except Exception:
                pass
            else:
                self.assertEqual(honolulu_dreamer.current_dream_date(now), "2026-09-19")

            scheduler = DreamScheduler(
                SimpleNamespace(config=SimpleNamespace(characters=[])),
                shanghai_dreamer,
                timezone="Asia/Shanghai",
            )
            next_run = scheduler.next_run_at(now)
            self.assertEqual(next_run.tzinfo, shanghai)
            self.assertEqual(next_run, datetime(2026, 9, 21, 0, 0, 5, tzinfo=shanghai))
            self.assertEqual(next_run.astimezone(utc), datetime(2026, 9, 20, 16, 0, 5, tzinfo=utc))
            self.assertEqual(shanghai_dreamer.timezone, "Asia/Shanghai")

    def test_writes_timezone_date_marker_not_naive_local_date(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            memory = AgentMemoryStore(Path(root) / "memory")
            character = SimpleNamespace(name="角色 A")
            sessions = SessionStore(memory.root)
            sessions.create_session("a-session", character_name=memory_slug(character.name))
            sessions.replace_messages("a-session", [{"role": "user", "content": "我每周跑步"}])
            agent = FakeAgent('{"character":["新增角色记忆"],"user":["用户每周跑步"]}')
            dreamer = MemoryDreamer(memory, agent, timezone="Asia/Shanghai")
            now = datetime(2026, 9, 19, 16, 30, tzinfo=timezone.utc)

            self.assertTrue(dreamer.run(character, now=now))
            marker = memory.agent_home(character.name) / ".dream-date"
            self.assertEqual(marker.read_text(encoding="utf-8").strip(), "2026-09-20")
            self.assertFalse(dreamer.run(character, now=now))

    @unittest.skipUnless(_zoneinfo_available("America/New_York"), "America/New_York tzdata required")
    def test_wait_uses_elapsed_seconds_across_dst_transitions(self) -> None:
        from zoneinfo import ZoneInfo

        ny = ZoneInfo("America/New_York")
        cases = (
            (datetime(2026, 3, 8, 0, 0, 5, tzinfo=ny), 82800.0),
            (datetime(2026, 11, 1, 0, 0, 5, tzinfo=ny), 90000.0),
        )
        for now, expected in cases:
            with self.subTest(now=str(now)):
                dreamer = SimpleNamespace(timezone="UTC", run=lambda _character: None)
                scheduler = DreamScheduler(
                    SimpleNamespace(config=SimpleNamespace(characters=[])),
                    dreamer,
                    timezone="America/New_York",
                )
                self.assertEqual(scheduler.seconds_until_next_run(now), expected)
                self.assertNotEqual(
                    (scheduler.next_run_at(now) - now).total_seconds(),
                    expected,
                )

                waits: list[float] = []

                def fake_wait(timeout: float | None = None) -> bool:
                    waits.append(timeout or 0.0)
                    return True

                scheduler._stop.wait = fake_wait  # type: ignore[method-assign]
                with patch("internal_agent.dream.now_in_timezone", return_value=now):
                    scheduler._run()
                self.assertEqual(waits, [expected])
                self.assertEqual(dreamer.timezone, "America/New_York")


if __name__ == "__main__":
    unittest.main()
