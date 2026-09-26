from __future__ import annotations

import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

_PROBE = Path(__file__).resolve().parent / "legacy_import_probe.py"


class LegacyImportRelocationTests(unittest.TestCase):
    def _prepare_legacy(
        self,
        base: Path,
        *,
        custom_memory: Path,
        custom_assets: Path,
        memory_config: str,
        assets_config: str,
    ) -> dict[str, Path]:
        legacy = base / "legacy-src"
        (legacy / "config").mkdir(parents=True)
        sprite = custom_assets / "legacy_hero" / "neutral.png"
        sprite.parent.mkdir(parents=True, exist_ok=True)
        sprite.write_bytes(b"legacy-sprite")
        memory_file = custom_memory / "agents" / "LegacyHero" / "memories" / "MEMORY.md"
        memory_file.parent.mkdir(parents=True, exist_ok=True)
        memory_file.write_text("legacy-memory-entry\n", encoding="utf-8")

        (legacy / "config" / "system_config.yaml").write_text(
            "active_character_name: LegacyHero\n", encoding="utf-8"
        )
        (legacy / "config" / "characters.yaml").write_text(
            yaml.safe_dump(
                [{
                    "name": "LegacyHero",
                    "color": "#84C2D5",
                    "sprite_prefix": "legacy_hero",
                    "sprites": [{
                        "path": sprite.as_posix(),
                        "state_name": "neutral",
                        "state_group": "core_emotion",
                    }],
                    "character_profile": {"identity": {"age": 20}},
                    "character_setting": "legacy setting",
                }],
                allow_unicode=True,
                sort_keys=False,
            ),
            encoding="utf-8",
        )
        legacy_storage = yaml.safe_dump(
            {
                "character_memory_dir": memory_config,
                "character_assets_dir": assets_config,
            },
            allow_unicode=True,
            sort_keys=False,
        )
        (legacy / "config" / "storage_paths.yaml").write_text(legacy_storage, encoding="utf-8")
        return {
            "legacy": legacy,
            "sprite": sprite,
            "memory_file": memory_file,
            "legacy_storage": legacy_storage,
        }

    def _run_probe(self, app_home: Path, legacy: Path) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(_PROBE)],
            cwd=_BACKEND_ROOT,
            env={
                **os.environ,
                "HERE_APP_HOME": str(app_home),
                "HERE_PROJECT_ROOT": str(_BACKEND_ROOT),
                "PROBE_LEGACY": str(legacy),
                "PYTHONUNBUFFERED": "1",
            },
            capture_output=True,
            text=True,
            timeout=120,
        )

    def _assert_relocated(self, app_home: Path, legacy: Path, fixture: dict[str, Path]) -> None:
        electron_memory = app_home / "memory" / "agents" / "LegacyHero" / "memories" / "MEMORY.md"
        self.assertTrue(electron_memory.is_file(), "imported memory must land in the Electron app home")
        self.assertEqual(electron_memory.read_text(encoding="utf-8").strip(), "electron-only-memory")
        # The legacy install must stay byte-for-byte untouched.
        self.assertEqual(fixture["memory_file"].read_text(encoding="utf-8").strip(), "legacy-memory-entry")
        self.assertTrue(fixture["sprite"].is_file())

        relocated_sprite = app_home / "characters" / "legacy_hero" / "neutral.png"
        self.assertTrue(relocated_sprite.is_file(), "legacy assets must be copied into the Electron app home")

        characters = yaml.safe_load((app_home / "config" / "characters.yaml").read_text(encoding="utf-8"))
        sprite_path = Path(characters[0]["sprites"][0]["path"])
        self.assertEqual(sprite_path, relocated_sprite)
        self.assertNotIn(str(legacy), sprite_path.as_posix())

        storage_path = app_home / "config" / "storage_paths.yaml"
        if storage_path.is_file():
            storage = yaml.safe_load(storage_path.read_text(encoding="utf-8")) or {}
            self.assertNotIn("external", str(storage.get("character_memory_dir") or ""))
            self.assertNotIn("external", str(storage.get("character_assets_dir") or ""))
        self.assertEqual(
            (fixture["legacy"] / "config" / "storage_paths.yaml").read_text(encoding="utf-8"),
            fixture["legacy_storage"],
        )

    def test_relative_custom_storage_is_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            fixture = self._prepare_legacy(
                base,
                custom_memory=base / "legacy-src" / "external-memory",
                custom_assets=base / "legacy-src" / "external-assets",
                memory_config="external-memory",
                assets_config="external-assets",
            )
            app_home = base / "app-home"
            result = self._run_probe(app_home, fixture["legacy"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_relocated(app_home, fixture["legacy"], fixture)

    def test_absolute_custom_storage_is_relocated(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            base = Path(root)
            absolute_memory = base / "abs-memory"
            absolute_assets = base / "abs-assets"
            fixture = self._prepare_legacy(
                base,
                custom_memory=absolute_memory,
                custom_assets=absolute_assets,
                memory_config=str(absolute_memory),
                assets_config=str(absolute_assets),
            )
            app_home = base / "app-home"
            result = self._run_probe(app_home, fixture["legacy"])
            self.assertEqual(result.returncode, 0, result.stderr)
            self._assert_relocated(app_home, fixture["legacy"], fixture)


if __name__ == "__main__":
    unittest.main()
