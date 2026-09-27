from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from infrastructure.paths import AppPaths  # noqa: E402
from services.storage_migration import (  # noqa: E402
    is_strict_child,
    migrate_storage_locations,
    relocate_character_asset_paths,
)


class FakeConfigManager:
    def __init__(self, character: SimpleNamespace) -> None:
        self.config = SimpleNamespace(characters=[character])
        self.saved = False

    def save_characters_config(self) -> None:
        self.saved = True


class StorageMigrationTests(unittest.TestCase):
    def test_copies_data_and_rewrites_only_paths_under_old_asset_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            old_memory = base / "old-memory"
            old_assets = base / "old-assets"
            new_memory = base / "new-memory"
            new_assets = base / "new-assets"
            old_memory.mkdir()
            (old_memory / "MEMORY.md").write_text("memory", encoding="utf-8")
            sprite_file = old_assets / "hero" / "neutral.png"
            sprite_file.parent.mkdir(parents=True)
            sprite_file.write_bytes(b"png")
            external = base / "external.png"
            character = SimpleNamespace(
                visual_reference_image=sprite_file.as_posix(),
                sprites=[{
                    "path": sprite_file.as_posix(),
                    "frames": [sprite_file.as_posix(), external.as_posix()],
                    "voice_path": "https://example.com/voice.wav",
                }],
            )
            config = FakeConfigManager(character)

            changed = migrate_storage_locations(
                old_memory_dir=old_memory,
                old_assets_dir=old_assets,
                new_memory_dir=new_memory,
                new_assets_dir=new_assets,
                config_manager=config,
            )

            self.assertTrue(changed)
            self.assertTrue(config.saved)
            self.assertEqual((new_memory / "MEMORY.md").read_text(encoding="utf-8"), "memory")
            self.assertEqual((new_assets / "hero" / "neutral.png").read_bytes(), b"png")
            self.assertEqual(character.sprites[0]["path"], (new_assets / "hero" / "neutral.png").as_posix())
            self.assertEqual(character.sprites[0]["frames"][1], external.as_posix())
            self.assertEqual(character.sprites[0]["voice_path"], "https://example.com/voice.wav")

    def test_rewrites_paths_reached_through_a_symlinked_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            real_assets = base / "real-assets"
            real_assets.mkdir()
            (real_assets / "hero.png").write_bytes(b"png")
            link = base / "link-assets"
            try:
                link.symlink_to(real_assets, target_is_directory=True)
            except OSError:
                self.skipTest("symlinks unavailable")
            new_assets = base / "new-assets"
            character = SimpleNamespace(
                visual_reference_image="",
                sprites=[{"path": (link / "hero.png").as_posix(), "frames": []}],
            )
            config = FakeConfigManager(character)

            changed = migrate_storage_locations(
                old_memory_dir=base / "unused-memory",
                old_assets_dir=real_assets,
                new_memory_dir=base / "unused-memory-target",
                new_assets_dir=new_assets,
                config_manager=config,
            )

            self.assertTrue(changed)
            self.assertEqual(character.sprites[0]["path"], (new_assets / "hero.png").as_posix())

    def test_relocates_supported_relative_references_using_the_legacy_root(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            legacy_root = base / "legacy"
            legacy_assets = legacy_root / "characters"
            hero = legacy_assets / "hero"
            hero.mkdir(parents=True)
            for name in ("neutral.png", "frame_0001.png", "frame_0002.png", "sheet.png", "visible.png"):
                (hero / name).write_bytes(b"x")
            new_assets = base / "electron-assets"
            character = SimpleNamespace(
                visual_reference_image="characters/hero/visible.png",
                sprites=[{
                    "path": "characters/hero/neutral.png",
                    "frames": ["characters/hero/frame_0001.png", "characters/hero/frame_0002.png"],
                    "spritesheet_path": "characters/hero/sheet.png",
                }],
            )
            config = FakeConfigManager(character)

            changed = relocate_character_asset_paths(
                legacy_layout=AppPaths(legacy_root),
                old_assets_dir=legacy_assets,
                new_assets_dir=new_assets,
                config_manager=config,
            )

            self.assertTrue(changed)
            self.assertTrue(config.saved)
            self.assertEqual(character.visual_reference_image, (new_assets / "hero" / "visible.png").as_posix())
            self.assertEqual(character.sprites[0]["path"], (new_assets / "hero" / "neutral.png").as_posix())
            self.assertEqual(
                character.sprites[0]["frames"],
                [
                    (new_assets / "hero" / "frame_0001.png").as_posix(),
                    (new_assets / "hero" / "frame_0002.png").as_posix(),
                ],
            )
            self.assertEqual(character.sprites[0]["spritesheet_path"], (new_assets / "hero" / "sheet.png").as_posix())

    def test_relocation_leaves_paths_outside_the_legacy_asset_root_alone(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            legacy_root = base / "legacy"
            (legacy_root / "characters").mkdir(parents=True)
            new_assets = base / "electron-assets"
            character = SimpleNamespace(
                visual_reference_image="https://example.com/hero.png",
                sprites=[{"path": "/tmp/unrelated/neutral.png", "frames": ["https://example.com/frame.png"]}],
            )
            config = FakeConfigManager(character)

            changed = relocate_character_asset_paths(
                legacy_layout=AppPaths(legacy_root),
                old_assets_dir=legacy_root / "characters",
                new_assets_dir=new_assets,
                config_manager=config,
            )

            self.assertFalse(changed)
            self.assertEqual(character.visual_reference_image, "https://example.com/hero.png")
            self.assertEqual(character.sprites[0]["path"], "/tmp/unrelated/neutral.png")
            self.assertEqual(character.sprites[0]["frames"], ["https://example.com/frame.png"])

    def test_detects_nested_migration_target(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            self.assertTrue(is_strict_child(source / "nested", source))
            self.assertFalse(is_strict_child(source, source))
            self.assertFalse(is_strict_child(Path(root) / "sibling", source))


if __name__ == "__main__":
    unittest.main()
