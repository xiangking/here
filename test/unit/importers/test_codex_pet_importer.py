import json
from pathlib import Path

import yaml
from PIL import Image

from services.config.config_manager import ConfigManager
from services.config.schema import Sprite
from core.importers.codex_pet_importer import _mapped_dialog_sprites, import_codex_pet_as_character


def _write_minimal_config(tmp_path: Path, monkeypatch) -> Path:
    app_home = tmp_path / ".local" / "here"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    cfg = app_home / "config"
    cfg.mkdir(parents=True)
    (app_home / "memory" / "characters").mkdir(parents=True)
    (cfg / "api.yaml").write_text("tts_provider: none\n", encoding="utf-8")
    (cfg / "system_config.yaml").write_text("active_character_name: ''\n", encoding="utf-8")
    (cfg / "background.yaml").write_text("[]\n", encoding="utf-8")
    (cfg / "characters.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": "系统精灵",
                    "color": "#84C2D5",
                    "sprite_prefix": "system",
                    "sprites": [],
                    "character_profile": {
                        "identity": {},
                        "personality": {},
                        "speech": {},
                        "relationship": {},
                        "preferences": {},
                        "boundaries": {},
                    },
                }
            ],
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    return app_home


def _write_fake_pet(tmp_path: Path, *, blank_tail_frames: bool = False) -> Path:
    pet_dir = tmp_path / "pet"
    pet_dir.mkdir()
    (pet_dir / "pet.json").write_text(
        json.dumps(
            {
                "id": "test-pet",
                "displayName": "测试宠物",
                "description": "一只用于测试的 Codex Pet。",
                "fps": 10,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    sheet = Image.new("RGBA", (192 * 8, 208 * 9), (0, 0, 0, 0))
    for row in range(9):
        for col in range(8):
            if blank_tail_frames and col >= 6:
                continue
            color = (20 * row, 20 * col, 120, 255)
            cell = Image.new("RGBA", (192, 208), color)
            sheet.paste(cell, (col * 192, row * 208))
    sheet.save(pet_dir / "spritesheet.png")
    return pet_dir


def test_import_codex_pet_as_character(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ConfigManager._instance = None
    ConfigManager._config = None
    app_home = _write_minimal_config(tmp_path, monkeypatch)
    pet_dir = _write_fake_pet(tmp_path)

    cfg = ConfigManager()
    result = import_codex_pet_as_character(pet_dir, config_manager=cfg)

    assert result.character_name == "测试宠物"
    assert result.state_count == 9
    assert result.frame_count == 72
    assert (app_home / "characters" / "codex_pets" / "test-pet" / "spritesheet.png").exists()
    assert (
        app_home / "memory" / "agents" / "测试宠物" / "memories" / "MEMORY.md"
    ).exists()

    imported = cfg.get_character_by_name("测试宠物")
    assert imported is not None
    assert len(imported.sprites) == 9
    assert [sprite.state_name for sprite in imported.sprites] == [
        "neutral",
        "happy",
        "thinking",
        "surprised",
        "sad",
        "working",
        "reviewing",
        "moving_right",
        "moving_left",
    ]
    assert [sprite.state_group for sprite in imported.sprites] == [
        "core_emotion",
        "core_emotion",
        "core_emotion",
        "core_emotion",
        "core_emotion",
        "system_optional_emotion",
        "system_optional_emotion",
        "mouse_event",
        "mouse_event",
    ]
    assert imported.sprites[3].source_state == "jumping"
    assert imported.sprites[4].source_state == "failed"
    assert imported.sprites[0].frame_interval_ms == 100
    assert len(imported.sprites[0].frames) == 8
    assert "核心情绪标准名：neutral/happy/thinking/surprised/sad/angry" in imported.emotion_tags
    assert cfg.resolve_active_character_name() == "测试宠物"

    saved = yaml.safe_load((app_home / "config" / "characters.yaml").read_text(encoding="utf-8"))
    assert any(item["name"] == "测试宠物" for item in saved)


def test_import_filters_transparent_tail_frames(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    ConfigManager._instance = None
    ConfigManager._config = None
    app_home = _write_minimal_config(tmp_path, monkeypatch)
    pet_dir = _write_fake_pet(tmp_path, blank_tail_frames=True)

    cfg = ConfigManager()
    result = import_codex_pet_as_character(pet_dir, config_manager=cfg)

    assert result.state_count == 9
    assert result.frame_count == 54
    imported = cfg.get_character_by_name("测试宠物")
    assert imported is not None
    assert len(imported.sprites[0].frames) == 6
    assert imported.sprites[0].frame_count == 6


def test_mapping_allows_missing_core_states_and_preserves_custom(tmp_path):
    idle = tmp_path / "idle.png"
    custom = tmp_path / "dance.png"
    idle.write_text("fake")
    custom.write_text("fake")
    extracted = {
        "idle": Sprite(path=str(idle), frames=[str(idle)]),
        "dance": Sprite(path=str(custom), frames=[str(custom)]),
    }

    sprites, rows = _mapped_dialog_sprites(extracted)

    assert [sprite.state_name for sprite in sprites] == ["neutral", "dance"]
    assert [sprite.state_group for sprite in sprites] == ["core_emotion", "custom"]
    assert [sprite.source_state for sprite in sprites] == ["idle", "dance"]
    assert rows == [
        ("neutral", "core_emotion", "idle", "默认、平静、普通、neutral"),
        ("dance", "custom", "dance", "dance"),
    ]
