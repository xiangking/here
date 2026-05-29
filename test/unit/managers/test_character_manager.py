from __future__ import annotations

from services.config.character_manager import CharacterManager
from services.config.config_manager import SYSTEM_CHARACTER_NAME
from test.conftest import make_character, make_app_config


class _ConfigManagerStub:
    def __init__(self) -> None:
        self.config = make_app_config(characters=[make_character(name=SYSTEM_CHARACTER_NAME)])
        self.saved = False

    def save_characters_config(self) -> None:
        self.saved = True

    def get_character_by_name(self, name: str):
        for character in self.config.characters:
            if character.name == name:
                return character
        return None


def test_character_manager_keeps_system_character():
    manager = CharacterManager.__new__(CharacterManager)
    manager._config_manager = _ConfigManagerStub()

    message, names = manager.delete_character(SYSTEM_CHARACTER_NAME)

    assert "不能删除" in message
    assert names == [SYSTEM_CHARACTER_NAME]
    assert manager._config_manager.config.characters[0].name == SYSTEM_CHARACTER_NAME
    assert manager._config_manager.saved is False
