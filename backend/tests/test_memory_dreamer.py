from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace

from internal_agent.context import AgentMemoryStore, memory_slug
from internal_agent.dream import MemoryDreamer
from internal_agent.session_store import SessionStore


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


if __name__ == "__main__":
    unittest.main()
