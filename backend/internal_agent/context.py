from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

from infrastructure.paths import get_app_paths
from typing import Any

from internal_agent.emotion_tags import (
    filter_emotion_tags_for_character,
    render_available_state_names,
)


@dataclass(frozen=True)
class CharacterSoul:
    name: str
    character_setting: str = ""
    visual_identity: str = ""
    emotion_tags: str = ""


@dataclass(frozen=True)
class AgentContext:
    system_template: str = ""
    selected_characters: list[str] = field(default_factory=list)
    character_souls: list[CharacterSoul] = field(default_factory=list)
    long_term_memories: dict[str, list[str]] = field(default_factory=dict)
    session_summary: str = ""
    life_state: str = ""
    dialog_protocol: str = ""
    memory_home: Path | None = None


def memory_slug(name: str) -> str:
    text = str(name or "").strip()
    text = re.sub(r"[\\/:*?\"<>|\s]+", "_", text)
    text = text.strip("._")
    return text or "user"


def _bullet_text(line: str) -> str:
    return re.sub(r"^\s*(?:[-*]|\d+[.)])\s*", "", line).strip()


_ENTRY_DELIMITER = "\n§\n"




class AgentMemoryStore:
    def __init__(self, root: str | Path | None = None) -> None:
        self.root = Path(root) if root is not None else get_app_paths().memory_dir
        self.agents_dir = self.root / "agents"
        self.sessions_dir = self.root / "sessions"

    def agent_home(self, character_name: str) -> Path:
        return self.agents_dir / memory_slug(character_name)

    def character_path(self, character_name: str) -> Path:
        return self.agent_home(character_name) / "memories" / "MEMORY.md"

    def user_path(self, character_name: str) -> Path:
        return self.agent_home(character_name) / "memories" / "USER.md"

    def soul_path(self, character_name: str) -> Path:
        return self.agent_home(character_name) / "SOUL.md"

    def session_path(self, session_id: str) -> Path:
        return self.sessions_dir / f"{memory_slug(session_id)}.md"

    def read_character_memories(self, character_name: str) -> list[str]:
        path = self.character_path(character_name)
        if not path.is_file():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return []
        if _ENTRY_DELIMITER in raw:
            memories = [part.strip() for part in raw.split(_ENTRY_DELIMITER)]
        else:
            memories = [_bullet_text(line) for line in raw.splitlines()]
        return [m for m in memories if m and not m.startswith("#")]

    def write_character_memories(self, character_name: str, memories: list[str]) -> None:
        self.character_path(character_name).parent.mkdir(parents=True, exist_ok=True)
        clean = [str(m).strip() for m in memories if str(m).strip()]
        body = _ENTRY_DELIMITER.join(clean)
        self.character_path(character_name).write_text(body + ("\n" if body else ""), encoding="utf-8")

    def read_user_profile(self, character_name: str) -> list[str]:
        path = self.user_path(character_name)
        if not path.is_file():
            return []
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            return []
        return [part.strip() for part in raw.split(_ENTRY_DELIMITER) if part.strip()]

    def write_user_profile(self, character_name: str, entries: list[str]) -> None:
        self.user_path(character_name).parent.mkdir(parents=True, exist_ok=True)
        clean = [str(m).strip() for m in entries if str(m).strip()]
        body = _ENTRY_DELIMITER.join(clean)
        self.user_path(character_name).write_text(body + ("\n" if body else ""), encoding="utf-8")

    def write_character_soul(self, character_name: str, content: str) -> None:
        self.soul_path(character_name).parent.mkdir(parents=True, exist_ok=True)
        path = self.soul_path(character_name)
        body = str(content or "").strip() + "\n"
        try:
            if path.is_file() and path.read_text(encoding="utf-8") == body:
                return
        except OSError:
            pass
        path.write_text(body, encoding="utf-8")

    def sync_character_soul(self, character: Any) -> Path:
        name = str(getattr(character, "name", "") or "").strip() or "user"
        self.write_character_soul(name, self.render_character_soul(character))
        return self.soul_path(name)

    def ensure_character_home(self, character: Any) -> Path:
        name = str(getattr(character, "name", "") or "").strip()
        if not name:
            name = "user"
        home = self.agent_home(name)
        memories_dir = home / "memories"
        memories_dir.mkdir(parents=True, exist_ok=True)
        for path in (memories_dir / "MEMORY.md", memories_dir / "USER.md"):
            path.touch(exist_ok=True)
        self.sync_character_soul(character)
        return home

    def render_character_soul(self, character: Any) -> str:
        name = str(getattr(character, "name", "") or "").strip() or "角色"
        parts = [
            f"# {name}",
            "你是当前应用中的一个角色。你只能依据本文件、聊天模板和 memories/ 目录里的记忆来维持长期身份。",
            "不要引用其他 agent 的默认身份、默认记忆或其他 profile 的记忆。",
            "",
            "## 角色设定",
            str(getattr(character, "character_setting", "") or "").strip() or "暂无。",
        ]
        visual_identity = str(getattr(character, "visual_identity", "") or "").strip()
        if visual_identity:
            parts.extend(["", "## 视觉身份", visual_identity])
        state_names = render_available_state_names(character).strip()
        if state_names:
            parts.extend(["", "## 本地可用状态名", state_names])
        emotion_tags = filter_emotion_tags_for_character(character).strip()
        if emotion_tags:
            parts.extend(["", "## 立绘与情绪标签", emotion_tags])
        return "\n".join(parts).strip()

    def append_character_memory(self, character_name: str, memory: str) -> list[str]:
        memories = self.read_character_memories(character_name)
        text = str(memory or "").strip()
        if text:
            memories.append(text)
            self.write_character_memories(character_name, memories)
        return memories

    def delete_character_memory(self, character_name: str, index: int) -> list[str]:
        memories = self.read_character_memories(character_name)
        if 0 <= index < len(memories):
            del memories[index]
            self.write_character_memories(character_name, memories)
        return memories

    def read_session_summary(self, session_id: str) -> str:
        path = self.session_path(session_id)
        if not path.is_file():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError:
            return ""

    def write_session_summary(self, session_id: str, summary: str) -> None:
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self.session_path(session_id).write_text(str(summary or "").strip() + "\n", encoding="utf-8")

    def rename_character(self, old_name: str, new_name: str) -> None:
        """Move memory files after a role is renamed."""
        old_home = self.agent_home(old_name)
        new_home = self.agent_home(new_name)
        if old_home != new_home and old_home.exists():
            new_home.parent.mkdir(parents=True, exist_ok=True)
            if not new_home.exists():
                shutil.move(str(old_home), str(new_home))
            else:
                self._merge_agent_home(old_home, new_home)
                shutil.rmtree(old_home, ignore_errors=True)

    def delete_character(self, character_name: str) -> None:
        """Delete memory files for a removed role."""
        home = self.agent_home(character_name)
        if home.exists():
            shutil.rmtree(home, ignore_errors=True)

    def _merge_agent_home(self, source: Path, target: Path) -> None:
        for src_path in source.rglob("*"):
            if src_path.is_dir():
                continue
            rel = src_path.relative_to(source)
            dst_path = target / rel
            dst_path.parent.mkdir(parents=True, exist_ok=True)
            if not dst_path.exists():
                shutil.copy2(src_path, dst_path)
                continue
            try:
                src_text = src_path.read_text(encoding="utf-8").strip()
                dst_text = dst_path.read_text(encoding="utf-8").strip()
            except UnicodeDecodeError:
                continue
            if src_text and src_text not in dst_text:
                joined = "\n\n".join(part for part in (dst_text, src_text) if part)
                dst_path.write_text(joined + "\n", encoding="utf-8")

def _character_soul(character: Any) -> CharacterSoul:
    state_names = render_available_state_names(character).strip()
    emotion_tags = filter_emotion_tags_for_character(character)
    combined_tags = "\n".join(part for part in (state_names, emotion_tags) if part)
    return CharacterSoul(
        name=str(getattr(character, "name", "") or ""),
        character_setting=str(getattr(character, "character_setting", "") or ""),
        visual_identity=str(getattr(character, "visual_identity", "") or ""),
        emotion_tags=combined_tags,
    )


def build_agent_context(
    *,
    config_manager: Any,
    memory_store: AgentMemoryStore,
    system_template: str = "",
    session_id: str = "default",
    selected_character_names: list[str] | None = None,
    life_state: str = "",
) -> AgentContext:
    characters = list(getattr(config_manager.config, "characters", []) or [])
    if selected_character_names is not None:
        wanted = {str(name).strip() for name in selected_character_names if str(name).strip()}
        characters = [c for c in characters if str(getattr(c, "name", "") or "").strip() in wanted]
    souls = [_character_soul(c) for c in characters if getattr(c, "name", None)]
    selected = [s.name for s in souls if s.name]
    memory_home = None
    if characters:
        memory_home = memory_store.ensure_character_home(characters[0])
    memories = {
        name: memory_store.read_character_memories(name)
        for name in selected
    }
    return AgentContext(
        system_template=system_template or "",
        selected_characters=selected,
        character_souls=souls,
        long_term_memories=memories,
        session_summary=memory_store.read_session_summary(session_id),
        life_state=life_state,
        memory_home=memory_home,
    )
