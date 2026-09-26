from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from services.storage_migration import is_strict_child, migrate_storage_locations  # noqa: E402


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

    def test_detects_nested_migration_target(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            source = Path(root) / "source"
            self.assertTrue(is_strict_child(source / "nested", source))
            self.assertFalse(is_strict_child(source, source))
            self.assertFalse(is_strict_child(Path(root) / "sibling", source))


if __name__ == "__main__":
    unittest.main()
