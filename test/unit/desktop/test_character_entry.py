from __future__ import annotations

from ui.desktop.character_entry import character_entry_sprite
from services.config.config_manager import SYSTEM_CHARACTER_NAME


class _Config:
    def __init__(self, character):
        self._character = character

    def get_character_by_name(self, _name):
        return self._character


def test_system_character_entry_prefers_welcome_sprite():
    character = type(
        "Character",
        (),
        {
            "sprites": [
                {"path": "/tmp/neutral.png", "state_name": "neutral"},
                {"path": "/tmp/welcome.png", "state_name": "welcome"},
            ],
        },
    )()

    entry = character_entry_sprite(SYSTEM_CHARACTER_NAME, _Config(character))

    assert entry.asset_id == "2"
    assert entry.emotion == "welcome"


def test_regular_character_entry_uses_neutral_sprite():
    character = type(
        "Character",
        (),
        {
            "sprites": [
                {"path": "/tmp/happy.png", "state_name": "happy"},
                {"path": "/tmp/neutral.png", "state_name": "neutral"},
            ],
        },
    )()

    entry = character_entry_sprite("Alice", _Config(character))

    assert entry.asset_id == "2"
    assert entry.emotion == "neutral"
