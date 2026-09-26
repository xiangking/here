from __future__ import annotations

import os
import sys
import tempfile
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from internal_agent.context import AgentMemoryStore  # noqa: E402


def _filesystem_is_case_insensitive(base: Path) -> bool:
    probe = base / "case-probe"
    probe.mkdir()
    try:
        return (base / "CASE-PROBE").exists() and os.path.samefile(probe, base / "CASE-PROBE")
    finally:
        probe.rmdir()


class MemoryRenameTests(unittest.TestCase):
    def _populate(self, store: AgentMemoryStore, name: str) -> None:
        store.write_character_memories(name, ["记得这件事", "还有那件事"])
        store.write_user_profile(name, ["用户偏好"])
        store.write_character_soul(name, "## 设定")
        extra = store.agent_home(name) / "scratch.txt"
        extra.parent.mkdir(parents=True, exist_ok=True)
        extra.write_text("extra", encoding="utf-8")

    def test_case_only_rename_keeps_the_same_memory_directory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            if not _filesystem_is_case_insensitive(base):
                self.skipTest("requires a case-insensitive filesystem")
            store = AgentMemoryStore(base)
            self._populate(store, "here")

            store.rename_character("here", "HERE")

            home = store.agent_home("here")
            self.assertTrue(home.is_dir())
            self.assertEqual(store.read_character_memories("here"), ["记得这件事", "还有那件事"])
            self.assertEqual(store.read_user_profile("HERE"), ["用户偏好"])
            self.assertTrue((home / "SOUL.md").is_file())
            self.assertEqual((home / "scratch.txt").read_text(encoding="utf-8"), "extra")

    def test_different_directory_rename_moves_memory(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = AgentMemoryStore(Path(root))
            self._populate(store, "old")

            store.rename_character("old", "new")

            self.assertFalse(store.agent_home("old").exists())
            self.assertEqual(store.read_character_memories("new"), ["记得这件事", "还有那件事"])
            self.assertTrue((store.agent_home("new") / "SOUL.md").is_file())
            self.assertEqual((store.agent_home("new") / "scratch.txt").read_text(encoding="utf-8"), "extra")

    def test_rename_into_existing_home_merges_without_losing_either_side(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = AgentMemoryStore(Path(root))
            self._populate(store, "source")
            self._populate(store, "target")
            store.write_character_memories("target", ["目标已有记忆"])
            (store.agent_home("target") / "scratch.txt").write_text("target-extra", encoding="utf-8")

            store.rename_character("source", "target")

            self.assertFalse(store.agent_home("source").exists())
            merged = store.read_character_memories("target")
            self.assertTrue(any("目标已有记忆" in entry for entry in merged))
            self.assertTrue(any("记得这件事" in entry for entry in merged))
            self.assertEqual((store.agent_home("target") / "scratch.txt").read_text(encoding="utf-8"), "target-extra")

    def test_rename_with_missing_source_is_a_no_op(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            store = AgentMemoryStore(Path(root))
            store.rename_character("missing", "unused")
            self.assertFalse(store.agent_home("unused").exists())


if __name__ == "__main__":
    unittest.main()
