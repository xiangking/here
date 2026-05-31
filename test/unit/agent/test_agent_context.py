from __future__ import annotations

from unittest.mock import MagicMock

from services.config.schema import AppConfig, ApiConfig, Character, Sprite, SystemConfig
from internal_agent.context import AgentMemoryStore, build_agent_context, memory_slug
from core.sprite.character_profile import default_character_profile


def test_memory_store_reads_appends_and_deletes_character_memories(tmp_path):
    store = AgentMemoryStore(tmp_path)

    assert memory_slug("Alice / Bob") == "Alice_Bob"
    assert store.read_character_memories("Alice") == []

    store.append_character_memory("Alice", "likes tea")
    store.append_character_memory("Alice", "met user yesterday")
    assert store.character_path("Alice") == tmp_path / "agents" / "Alice" / "memories" / "MEMORY.md"
    assert store.read_character_memories("Alice") == ["likes tea", "met user yesterday"]

    store.delete_character_memory("Alice", 0)
    assert store.read_character_memories("Alice") == ["met user yesterday"]


def test_build_agent_context_includes_soul_memory_and_summary(tmp_path):
    store = AgentMemoryStore(tmp_path)
    store.append_character_memory("Alice", "likes tea")
    store.write_session_summary("default", "Session summary")
    cfg = MagicMock()
    cfg.config = AppConfig(
        api_config=ApiConfig(),
        system_config=SystemConfig(),
        background_list=[],
        characters=[
            Character(
                name="Alice",
                color="#fff",
                sprite_prefix="alice",
                character_profile=default_character_profile("Alice"),
                character_setting="Alice persona",
                visual_identity="red coat",
                emotion_tags="happy=1",
            )
        ],
    )

    ctx = build_agent_context(
        config_manager=cfg,
        memory_store=store,
        system_template="Scene template",
        session_id="default",
    )

    assert ctx.system_template == "Scene template"
    assert ctx.selected_characters == ["Alice"]
    assert ctx.character_souls[0].character_setting == "Alice persona"
    assert ctx.long_term_memories == {"Alice": ["likes tea"]}
    assert ctx.session_summary == "Session summary"
    assert ctx.memory_home == tmp_path / "agents" / "Alice"
    assert (ctx.memory_home / "SOUL.md").read_text(encoding="utf-8").startswith("# Alice")
    assert (ctx.memory_home / "memories" / "MEMORY.md").is_file()
    assert (ctx.memory_home / "memories" / "USER.md").is_file()


def test_build_agent_context_syncs_soul_from_character_config(tmp_path):
    store = AgentMemoryStore(tmp_path)
    cfg = MagicMock()
    character = Character(
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        character_profile=default_character_profile("Alice"),
        character_setting="First persona",
    )
    cfg.config = AppConfig(
        api_config=ApiConfig(),
        system_config=SystemConfig(),
        background_list=[],
        characters=[character],
    )

    build_agent_context(config_manager=cfg, memory_store=store)
    character.character_setting = "Updated persona"
    build_agent_context(config_manager=cfg, memory_store=store)

    assert "Updated persona" in store.soul_path("Alice").read_text(encoding="utf-8")


def test_build_agent_context_filters_selected_characters(tmp_path):
    store = AgentMemoryStore(tmp_path)
    store.append_character_memory("Bob", "likes coffee")
    cfg = MagicMock()
    cfg.config = AppConfig(
        api_config=ApiConfig(),
        system_config=SystemConfig(),
        background_list=[],
        characters=[
            Character(
                name="Alice",
                color="#fff",
                sprite_prefix="alice",
                character_profile=default_character_profile("Alice"),
                character_setting="Alice persona",
            ),
            Character(
                name="Bob",
                color="#000",
                sprite_prefix="bob",
                character_profile=default_character_profile("Bob"),
                character_setting="Bob persona",
            ),
        ],
    )

    ctx = build_agent_context(
        config_manager=cfg,
        memory_store=store,
        selected_character_names=["Bob"],
    )

    assert ctx.selected_characters == ["Bob"]
    assert [s.name for s in ctx.character_souls] == ["Bob"]
    assert ctx.long_term_memories == {"Bob": ["likes coffee"]}


def test_build_agent_context_filters_emotion_tags_to_existing_sprites(tmp_path):
    sprite_1 = tmp_path / "sprite1.png"
    sprite_2 = tmp_path / "sprite2.png"
    sprite_1.write_bytes(b"fake")
    sprite_2.write_bytes(b"fake")
    store = AgentMemoryStore(tmp_path)
    cfg = MagicMock()
    cfg.config = AppConfig(
        api_config=ApiConfig(),
        system_config=SystemConfig(),
        background_list=[],
        characters=[
            Character(
                name="Alice",
                color="#fff",
                sprite_prefix="alice",
                character_profile=default_character_profile("Alice"),
                sprites=[
                    Sprite(path=str(sprite_1), state_name="neutral"),
                    Sprite(path=str(sprite_2), state_name="smile"),
                ],
                emotion_tags=(
                    "核心情绪标准名：neutral/happy/thinking\n"
                    "立绘 1：neutral\n"
                    "立绘 2：happy\n"
                    "立绘 3：thinking\n"
                    "sprite 04：sad"
                ),
            )
        ],
    )

    ctx = build_agent_context(config_manager=cfg, memory_store=store)

    soul = ctx.character_souls[0].emotion_tags
    assert "可用状态名：neutral / smile" in soul
    assert "核心情绪标准名" in soul
    assert "立绘 1：neutral" in soul
    assert "立绘 2：happy" in soul
    assert "立绘 3" not in soul
    assert "sprite 04" not in soul
    soul_file = store.soul_path("Alice").read_text(encoding="utf-8")
    assert "## 本地可用状态名" in soul_file
    assert "可用状态名：neutral / smile" in soul_file
    assert "立绘 3" not in soul_file
    assert "sprite 04" not in soul_file


def test_memory_store_renames_character_home(tmp_path):
    store = AgentMemoryStore(tmp_path)
    store.append_character_memory("角色A", "remembers the first meeting")
    store.write_character_soul("角色A", "# 角色A\nold soul")

    store.rename_character("角色A", "小澪")

    assert not store.agent_home("角色A").exists()
    assert store.read_character_memories("小澪") == ["remembers the first meeting"]
    assert "# 角色A" in store.soul_path("小澪").read_text(encoding="utf-8")
