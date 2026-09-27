from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from core.sprite.character_profile import default_character_profile  # noqa: E402
from infrastructure.asset_paths import (  # noqa: E402
    UnsafeSpritePrefixError,
    owned_character_dir,
    prepare_owned_character_dir,
    remove_owned_character_dir,
    validate_sprite_prefix,
)
from services.config.character_manager import CharacterManager  # noqa: E402
from services.config.schema import Character, Sprite  # noqa: E402


def _character(name: str, prefix: str) -> Character:
    return Character(
        name=name,
        color="#84c2d5",
        sprite_prefix=prefix,
        sprites=[],
        character_profile=default_character_profile(name),
        character_setting="test",
    )


class FakeConfigManager:
    def __init__(self, characters: list[Character]) -> None:
        self.config = SimpleNamespace(characters=characters)
        self.saved = 0

    def get_character_by_name(self, name: str):
        wanted = str(name or "").strip()
        for character in self.config.characters:
            if character.name == wanted:
                return character
        return None

    def save_characters_config(self) -> None:
        self.saved += 1


class SpritePrefixValidationTests(unittest.TestCase):
    def test_rejects_absolute_traversal_and_root_names(self) -> None:
        with self.assertRaises(UnsafeSpritePrefixError):
            validate_sprite_prefix("/tmp/unrelated")
        with self.assertRaises(UnsafeSpritePrefixError):
            validate_sprite_prefix("../secret")
        with self.assertRaises(UnsafeSpritePrefixError):
            validate_sprite_prefix(".")
        with self.assertRaises(UnsafeSpritePrefixError):
            validate_sprite_prefix("..")
        with self.assertRaises(UnsafeSpritePrefixError):
            validate_sprite_prefix("here/nested")
        self.assertEqual(validate_sprite_prefix("here_ok-1"), "here_ok-1")

    def test_symlink_and_root_are_not_owned_directories(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-asset-guard-") as raw:
            root = Path(raw)
            assets = root / "characters"
            outside = root / "unrelated"
            assets.mkdir()
            outside.mkdir()
            (outside / "important.txt").write_text("keep", encoding="utf-8")
            (assets / "escape").symlink_to(outside)
            with self.assertRaises(UnsafeSpritePrefixError):
                owned_character_dir(assets, "escape")
            self.assertFalse(remove_owned_character_dir(assets, "escape"))
            self.assertTrue((outside / "important.txt").is_file())
            self.assertFalse(remove_owned_character_dir(assets, "."))
            self.assertTrue(assets.is_dir())

    def test_prepare_and_remove_only_owned_child(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-asset-owned-") as raw:
            root = Path(raw) / "characters"
            owned = prepare_owned_character_dir(root, "hero")
            (owned / "neutral.png").write_bytes(b"png")
            self.assertTrue(remove_owned_character_dir(root, "hero"))
            self.assertFalse(owned.exists())
            self.assertTrue(root.is_dir())


class CharacterManagerAssetGuardTests(unittest.TestCase):
    def _manager(self, characters: list[Character], assets: Path, voices: Path, models: Path) -> CharacterManager:
        manager = CharacterManager.__new__(CharacterManager)
        manager._config_manager = FakeConfigManager(characters)
        self.patches = [
            patch("services.config.character_manager._characters_dir", return_value=assets),
            patch("services.config.character_manager._voice_dir", return_value=voices),
            patch("services.config.character_manager._models_dir", return_value=models),
        ]
        for item in self.patches:
            item.start()
        return manager

    def tearDown(self) -> None:
        for item in getattr(self, "patches", []):
            item.stop()

    def test_delete_character_removes_owned_dir_only(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-delete-") as raw:
            base = Path(raw)
            assets = base / "characters"
            voices = base / "voices"
            models = base / "models"
            owned = assets / "hero"
            owned.mkdir(parents=True)
            (owned / "neutral.png").write_bytes(b"png")
            keep = assets / "keep.txt"
            keep.write_text("root", encoding="utf-8")
            characters = [_character("hero", "hero"), _character("other", "other")]
            manager = self._manager(characters, assets, voices, models)

            message, names = manager.delete_character("hero")

            self.assertIn("已删除", message)
            self.assertEqual(names, ["other"])
            self.assertFalse(owned.exists())
            self.assertTrue(keep.is_file())
            self.assertEqual(manager._config_manager.saved, 1)

    def test_delete_character_does_not_remove_absolute_or_shared_paths(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-unsafe-") as raw:
            base = Path(raw)
            assets = base / "characters"
            voices = base / "voices"
            models = base / "models"
            assets.mkdir()
            unrelated = base / "unrelated"
            unrelated.mkdir()
            secret = unrelated / "important.txt"
            secret.write_text("keep", encoding="utf-8")
            shared = assets / "shared"
            shared.mkdir()
            (shared / "sprite.png").write_bytes(b"png")
            characters = [
                _character("escaped", str(unrelated)),
                _character("dot", "."),
                _character("one", "shared"),
                _character("two", "shared"),
            ]
            manager = self._manager(characters, assets, voices, models)

            escaped_message, _ = manager.delete_character("escaped")
            dot_message, _ = manager.delete_character("dot")
            shared_message, _ = manager.delete_character("one")

            self.assertIn("已删除", escaped_message)
            self.assertIn("已删除", dot_message)
            self.assertIn("已删除", shared_message)
            self.assertTrue(secret.is_file())
            self.assertTrue(assets.is_dir())
            self.assertTrue((shared / "sprite.png").is_file())
            self.assertEqual([item.name for item in manager._config_manager.config.characters], ["two"])

    def test_delete_single_sprite_leaves_files_outside_owned_dir(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-sprite-") as raw:
            base = Path(raw)
            assets = base / "characters"
            voices = base / "voices"
            models = base / "models"
            assets.mkdir()
            outside = base / "outside.png"
            outside.write_bytes(b"outside")
            character = _character("hero", "../escape")
            character.sprites = [{"path": outside.as_posix(), "voice_path": ""}]
            manager = self._manager([character], assets, voices, models)

            message, remaining, _ = manager.delete_single_sprite("hero", 0)

            self.assertIn("已删除", message)
            self.assertEqual(remaining, [])
            self.assertTrue(outside.is_file())
            self.assertEqual(character.sprites, [])

    def test_delete_single_sprite_keeps_a_file_shared_with_another_sprite(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-shared-sprite-") as raw:
            base = Path(raw)
            assets = base / "characters"
            owned = assets / "hero"
            owned.mkdir(parents=True)
            shared = owned / "neutral.png"
            shared.write_bytes(b"png")
            character = _character("hero", "hero")
            character.sprites = [
                Sprite(path=shared, state_name="neutral"),
                Sprite(path=shared, state_name="happy"),
            ]
            manager = self._manager([character], assets, base / "voices", base / "models")

            manager.delete_single_sprite("hero", 0)

            self.assertTrue(shared.is_file())
            self.assertEqual(len(character.sprites), 1)

    def test_delete_single_sprite_keeps_a_file_shared_with_another_character(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-shared-file-") as raw:
            base = Path(raw)
            assets = base / "characters"
            shared_dir = assets / "shared"
            shared_dir.mkdir(parents=True)
            shared = shared_dir / "sprite.png"
            shared.write_bytes(b"png")
            one = _character("one", "shared")
            two = _character("two", "shared")
            one.sprites = [Sprite(path=shared, state_name="neutral")]
            two.sprites = [Sprite(path=shared, state_name="neutral")]
            manager = self._manager([one, two], assets, base / "voices", base / "models")

            manager.delete_single_sprite("one", 0)

            self.assertTrue(shared.is_file())
            self.assertEqual(len(one.sprites), 0)
            self.assertEqual(len(two.sprites), 1)

    def test_delete_all_sprites_keeps_a_directory_referenced_by_another_character(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-shared-dir-") as raw:
            base = Path(raw)
            assets = base / "characters"
            shared_dir = assets / "shared"
            shared_dir.mkdir(parents=True)
            shared = shared_dir / "sprite.png"
            shared.write_bytes(b"png")
            one = _character("one", "shared")
            two = _character("two", "other")
            one.sprites = [Sprite(path=shared, state_name="neutral")]
            two.sprites = [Sprite(path=shared, state_name="neutral")]
            manager = self._manager([one, two], assets, base / "voices", base / "models")

            manager.delete_all_sprites("one")

            self.assertTrue(shared.is_file())
            self.assertEqual(one.sprites, [])

    def test_delete_character_keeps_a_file_referenced_by_a_surviving_character(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-survivor-") as raw:
            base = Path(raw)
            assets = base / "characters"
            shared_dir = assets / "shared"
            shared_dir.mkdir(parents=True)
            shared = shared_dir / "sprite.png"
            shared.write_bytes(b"png")
            one = _character("one", "shared")
            two = _character("two", "other")
            one.sprites = [Sprite(path=shared, state_name="neutral")]
            two.sprites = [Sprite(path=shared, state_name="neutral")]
            manager = self._manager([one, two], assets, base / "voices", base / "models")

            message, names = manager.delete_character("one")

            self.assertIn("已删除", message)
            self.assertEqual(names, ["two"])
            self.assertTrue(shared.is_file())

    def test_add_character_rejects_traversal_prefix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-char-add-") as raw:
            base = Path(raw)
            manager = self._manager([], base / "characters", base / "voices", base / "models")
            message, names = manager.add_character(
                "danger",
                "#fff",
                "../escape",
                "setting",
                character_profile=default_character_profile("danger"),
            )
            self.assertIn("资源前缀", message)
            self.assertEqual(names, [])
            self.assertEqual(manager._config_manager.config.characters, [])


if __name__ == "__main__":
    unittest.main()
