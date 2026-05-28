from __future__ import annotations

from services.config.schema import Character, Sprite
from core.sprite.character_profile import default_character_profile
from core.sprite.emotion_resolver import resolve_sprite_index


def _sprite(tmp_path, name: str, state_name: str = "") -> Sprite:
    path = tmp_path / f"{name}.png"
    path.write_bytes(b"fake")
    return Sprite(path=str(path), state_name=state_name)


def test_resolve_sprite_index_prefers_state_name(tmp_path):
    character = Character(
        character_profile=default_character_profile("Alice"),
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        sprites=[
            _sprite(tmp_path, "neutral", "neutral"),
            _sprite(tmp_path, "happy", "happy"),
        ],
    )

    assert resolve_sprite_index(character, "happy") == 1


def test_resolve_sprite_index_uses_emotion_tags_when_state_name_missing(tmp_path):
    character = Character(
        character_profile=default_character_profile("Alice"),
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        sprites=[_sprite(tmp_path, "one"), _sprite(tmp_path, "two")],
        emotion_tags="立绘 1：日常、neutral\n立绘 2：开心、happy",
    )

    assert resolve_sprite_index(character, "happy") == 1


def test_resolve_sprite_index_falls_back_to_neutral_or_first(tmp_path):
    with_neutral = Character(
        character_profile=default_character_profile("Alice"),
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        sprites=[
            _sprite(tmp_path, "happy", "happy"),
            _sprite(tmp_path, "neutral", "neutral"),
        ],
    )
    without_neutral = Character(
        character_profile=default_character_profile("Bob"),
        name="Bob",
        color="#fff",
        sprite_prefix="bob",
        sprites=[_sprite(tmp_path, "one", "happy")],
    )

    assert resolve_sprite_index(with_neutral, "angry") == 1
    assert resolve_sprite_index(without_neutral, "angry") == 0
