from __future__ import annotations

from pathlib import Path

import yaml

from services.config.config_manager import ConfigManager, SYSTEM_CHARACTER_NAME


def _write_config(app_home: Path, *, character_name: str, active_name: str) -> None:
    cfg = app_home / "config"
    cfg.mkdir(parents=True)
    (cfg / "api.yaml").write_text("tts_provider: none\n", encoding="utf-8")
    (cfg / "background.yaml").write_text("[]\n", encoding="utf-8")
    (cfg / "system_config.yaml").write_text(
        yaml.safe_dump(
            {"active_character_name": active_name},
            allow_unicode=True,
            sort_keys=False,
        ),
        encoding="utf-8",
    )
    (cfg / "characters.yaml").write_text(
        yaml.safe_dump(
            [
                {
                    "name": character_name,
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


def test_config_manager_migrates_legacy_system_character_name(tmp_path, monkeypatch):
    app_home = tmp_path / "here-home"
    monkeypatch.setenv("HERE_APP_HOME", str(app_home))
    _write_config(app_home, character_name="系统精灵", active_name="系统精灵")
    ConfigManager._instance = None
    ConfigManager._config = None

    manager = ConfigManager()

    assert manager.resolve_active_character_name() == SYSTEM_CHARACTER_NAME
    assert manager.get_character_by_name(SYSTEM_CHARACTER_NAME) is not None
    saved_characters = yaml.safe_load((app_home / "config" / "characters.yaml").read_text(encoding="utf-8"))
    saved_system = yaml.safe_load((app_home / "config" / "system_config.yaml").read_text(encoding="utf-8"))
    assert saved_characters[0]["name"] == SYSTEM_CHARACTER_NAME
    assert saved_system["active_character_name"] == SYSTEM_CHARACTER_NAME
