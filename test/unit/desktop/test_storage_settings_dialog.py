from __future__ import annotations

from pathlib import Path

from services.config.schema import Character, Sprite
from ui.desktop.storage_settings_dialog import rewrite_character_asset_paths


class _ConfigManagerStub:
    def __init__(self, character: Character) -> None:
        self.config = type("Config", (), {"characters": [character]})()
        self.saved = False

    def save_characters_config(self) -> None:
        self.saved = True


def test_rewrite_character_asset_paths_updates_sprite_paths(tmp_path):
    old_root = tmp_path / "old-assets"
    new_root = tmp_path / "new-assets"
    old_root.mkdir()
    ref = old_root / "alice" / "neutral.png"
    frame_1 = old_root / "alice" / "animations" / "neutral" / "frame_01.png"
    frame_2 = old_root / "alice" / "animations" / "neutral" / "frame_02.png"
    sheet = old_root / "alice" / "spritesheet.png"
    voice = old_root / "alice" / "voice.wav"
    for path in (ref, frame_1, frame_2, sheet, voice):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"x")
    character = Character(
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        sprites=[
            Sprite(
                path=str(ref),
                frames=[str(frame_1), str(frame_2)],
                spritesheet_path=str(sheet),
                voice_path=str(voice),
            )
        ],
        character_profile={
            "identity": {},
            "personality": {},
            "speech": {},
            "relationship": {},
            "preferences": {},
            "boundaries": {},
        },
        visual_reference_image=str(ref),
    )
    cfg = _ConfigManagerStub(character)

    changed = rewrite_character_asset_paths(old_root, new_root, config_manager=cfg)

    assert changed is True
    assert cfg.saved is True
    assert character.visual_reference_image == (new_root / "alice" / "neutral.png").as_posix()
    sprite = character.sprites[0]
    assert sprite.path == (new_root / "alice" / "neutral.png").as_posix()
    assert sprite.frames == [
        (new_root / "alice" / "animations" / "neutral" / "frame_01.png").as_posix(),
        (new_root / "alice" / "animations" / "neutral" / "frame_02.png").as_posix(),
    ]
    assert sprite.spritesheet_path == (new_root / "alice" / "spritesheet.png").as_posix()
    assert str(sprite.voice_path) == (new_root / "alice" / "voice.wav").as_posix()


def test_rewrite_character_asset_paths_keeps_urls_and_external_paths(tmp_path):
    old_root = tmp_path / "old-assets"
    new_root = tmp_path / "new-assets"
    external = tmp_path / "elsewhere" / "neutral.png"
    external.parent.mkdir()
    external.write_bytes(b"x")
    character = Character(
        name="Alice",
        color="#fff",
        sprite_prefix="alice",
        sprites=[{"path": str(external), "frames": ["https://example.test/frame.png"]}],
        character_profile={
            "identity": {},
            "personality": {},
            "speech": {},
            "relationship": {},
            "preferences": {},
            "boundaries": {},
        },
        visual_reference_image="https://example.test/ref.png",
    )
    cfg = _ConfigManagerStub(character)

    changed = rewrite_character_asset_paths(old_root, new_root, config_manager=cfg)

    assert changed is False
    assert cfg.saved is False
    assert character.visual_reference_image == "https://example.test/ref.png"
    assert character.sprites[0]["path"] == str(external)
