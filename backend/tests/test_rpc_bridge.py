from __future__ import annotations

import json
import os
import copy
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import yaml


_APP_HOME = tempfile.TemporaryDirectory(prefix="here-electron-tests-")
os.environ["HERE_APP_HOME"] = _APP_HOME.name
_BACKEND_ROOT = Path(__file__).resolve().parents[1]
os.environ["HERE_PROJECT_ROOT"] = str(_BACKEND_ROOT)
sys.path.insert(0, str(_BACKEND_ROOT))

import rpc_bridge  # noqa: E402
from core.messaging.messages import AgentDialogMessage  # noqa: E402
from core.sprite.character_profile import default_character_profile  # noqa: E402
from infrastructure.asset_paths import UnsafeSpritePrefixError  # noqa: E402
from infrastructure.paths import load_storage_paths  # noqa: E402
from services.config.schema import Character, Sprite  # noqa: E402


class RpcBridgeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.backend = rpc_bridge.HereBackend()
        self.backend.clear_history()

    def tearDown(self) -> None:
        self.backend.shutdown()

    def test_dispatch_method_names_match_snapshot(self) -> None:
        expected = {
            "ping",
            "get_state",
            "save_config",
            "set_active_character",
            "chat",
            "observe_screen",
            "stop_chat",
            "clear_history",
            "revert_history",
            "update_memory",
            "create_character",
            "upload_character_sprites",
            "import_character_state_assets",
            "delete_character_sprite",
            "delete_character",
            "generate_image",
            "generate_realtime_sprite",
            "start_asr",
            "stop_asr",
            "pause_asr",
            "resume_asr",
            "codex_pet_candidates",
            "import_codex_pet",
            "wechat_login_start",
            "wechat_login_poll",
            "wechat_status",
            "telegram_discover",
            "list_models",
            "dependency_status",
            "install_dependencies",
            "prepare_asr",
            "save_messaging",
            "save_storage",
            "import_legacy",
            "resolve_assets",
        }
        self.assertEqual(set(rpc_bridge.RPC_METHOD_NAMES), expected)
        self.assertEqual(set(rpc_bridge.rpc_methods(self.backend)), expected)

    def test_reserved_dialog_names_remain_system_messages(self) -> None:
        for name in ("COT", "CHOICE", "STAT", "SCENE", "bgm", "CG", "NARR", "选项", "场景"):
            self.assertTrue(self.backend._is_reserved_dialog_name(name), name)
        self.assertFalse(self.backend._is_reserved_dialog_name(self.backend.config.resolve_active_character_name()))

    def test_video_call_import_preserves_native_video(self) -> None:
        character = self.backend.config.get_character_by_name(self.backend.config.resolve_active_character_name())
        original_sprites = copy.deepcopy(character.sprites)
        video = Path(_APP_HOME.name) / "call-source.mp4"
        video.write_bytes(b"native video fixture")
        try:
            result = self.backend.import_character_state_assets({
                "character_name": character.name, "state_name": "video_call",
                "state_group": "custom", "paths": [str(video)],
            })
            saved = next(item for item in result["config"]["characters"] if item["name"] == character.name)
            call = next(item for item in saved["sprites"] if item["state_name"] == "video_call")
            self.assertEqual(call["frames"], [])
            self.assertEqual(Path(call["path"]).suffix, ".mp4")
            self.assertEqual(Path(call["path"]).read_bytes(), video.read_bytes())
            with self.assertRaises(ValueError):
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": "video_call", "paths": [str(video), str(video)],
                })
            self.assertEqual(Path(call["path"]).read_bytes(), video.read_bytes())
        finally:
            character.sprites = original_sprites
            self.backend.config.save_characters_config()

    def _add_probe_character(self, name: str, prefix: str) -> Character:
        character = Character(
            name=name,
            color="#84c2d5",
            sprite_prefix=prefix,
            sprites=[],
            character_profile=default_character_profile(name),
            character_setting="test",
        )
        self.backend.config.config.characters.append(character)
        self.backend.config.save_characters_config()
        return character

    def _remove_probe_character(self, character: Character) -> None:
        self.backend.config.config.characters = [
            item for item in self.backend.config.config.characters if item.name != character.name
        ]
        self.backend.config.save_characters_config()
        shutil.rmtree(self.backend.paths.characters_dir / character.sprite_prefix, ignore_errors=True)
        self.backend.reload_runtime()

    @staticmethod
    def _sprite_path(sprite: object) -> Path:
        raw = sprite.path if hasattr(sprite, "path") else sprite.get("path")
        return Path(str(raw))

    def test_failed_gif_replacement_keeps_previous_asset_and_config(self) -> None:
        from PIL import UnidentifiedImageError

        character = self._add_probe_character("AtomicGifProbe", "atomic_gif_probe")
        state = "atomic_gif_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"good")
                bad = Path(root) / "bad.gif"
                bad.write_bytes(b"definitely not a gif")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])
                self.assertTrue(previous_path.is_file())

                with self.assertRaises(UnidentifiedImageError):
                    self.backend.import_character_state_assets({
                        "character_name": character.name, "state_name": state, "paths": [bad.as_posix()],
                    })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(len(after.sprites), 1)
                self.assertEqual(self._sprite_path(after.sprites[0]), previous_path)
                self.assertTrue(previous_path.is_file(), "failed replacement must keep the previous sprite file")
                leftovers = [
                    item.name for item in previous_path.parent.parent.iterdir()
                    if item.name.startswith((".pending-", ".backup-"))
                ]
                self.assertEqual(leftovers, [])
        finally:
            self._remove_probe_character(character)

    def test_undecodable_video_replacement_keeps_previous_asset(self) -> None:
        character = self._add_probe_character("AtomicVideoProbe", "atomic_video_probe")
        state = "atomic_video_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"good")
                broken_video = Path(root) / "broken.mov"
                broken_video.write_bytes(b"not a real video")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])

                with self.assertRaises(RuntimeError):
                    self.backend.import_character_state_assets({
                        "character_name": character.name, "state_name": state, "paths": [broken_video.as_posix()],
                    })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(self._sprite_path(after.sprites[0]), previous_path)
                self.assertTrue(previous_path.is_file())
        finally:
            self._remove_probe_character(character)

    def test_video_frame_write_failure_keeps_previous_asset_and_config(self) -> None:
        character = self._add_probe_character("AtomicImwriteProbe", "atomic_imwrite_probe")
        state = "atomic_imwrite_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"previous-good-bytes")
                video = Path(root) / "clip.mov"
                video.write_bytes(b"video")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])
                previous_bytes = previous_path.read_bytes()
                config_path = self.backend.paths.config_dir / "characters.yaml"

                class FakeCapture:
                    def __init__(self) -> None:
                        self.reads = 0

                    def isOpened(self) -> bool:
                        return True

                    def read(self):
                        self.reads += 1
                        if self.reads <= 2:
                            return True, object()
                        return False, None

                    def release(self) -> None:
                        pass

                calls = {"imwrite": 0}

                def fake_imwrite(path: str, frame: object) -> bool:
                    calls["imwrite"] += 1
                    if calls["imwrite"] == 1:
                        Path(path).write_bytes(b"frame-one")
                        return True
                    return False

                fake_cv2 = SimpleNamespace(
                    VideoCapture=lambda source: FakeCapture(),
                    imwrite=fake_imwrite,
                )
                with patch.dict(sys.modules, {"cv2": fake_cv2}):
                    with self.assertRaisesRegex(RuntimeError, "写入视频帧失败"):
                        self.backend.import_character_state_assets({
                            "character_name": character.name, "state_name": state,
                            "paths": [video.as_posix()],
                        })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(self._sprite_path(after.sprites[0]), previous_path)
                self.assertEqual(previous_path.read_bytes(), previous_bytes)
                disk = yaml.safe_load(config_path.read_text(encoding="utf-8"))
                disk_character = next(item for item in disk if item["name"] == character.name)
                self.assertEqual(Path(disk_character["sprites"][0]["path"]), previous_path)
                leftovers = [
                    item.name for item in previous_path.parent.parent.iterdir()
                    if item.name.startswith((".pending-", ".backup-"))
                ]
                self.assertEqual(leftovers, [])
        finally:
            self._remove_probe_character(character)

    def test_copy_failure_during_replacement_keeps_previous_asset(self) -> None:
        character = self._add_probe_character("AtomicCopyProbe", "atomic_copy_probe")
        state = "atomic_copy_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"good")
                replacement = Path(root) / "replacement.png"
                replacement.write_bytes(b"replacement")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])

                with patch("bridge.characters.shutil.copy2", side_effect=OSError("simulated copy failure")):
                    with self.assertRaises(OSError):
                        self.backend.import_character_state_assets({
                            "character_name": character.name, "state_name": state,
                            "paths": [replacement.as_posix()],
                        })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(self._sprite_path(after.sprites[0]), previous_path)
                self.assertTrue(previous_path.is_file())
        finally:
            self._remove_probe_character(character)

    def test_config_save_failure_during_replacement_restores_previous_asset(self) -> None:
        character = self._add_probe_character("AtomicSaveProbe", "atomic_save_probe")
        state = "atomic_save_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"good")
                replacement = Path(root) / "replacement.png"
                replacement.write_bytes(b"replacement")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])

                with patch.object(self.backend.config, "save_characters_config", side_effect=OSError("disk full")):
                    with self.assertRaises(OSError):
                        self.backend.import_character_state_assets({
                            "character_name": character.name, "state_name": state,
                            "paths": [replacement.as_posix()],
                        })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(self._sprite_path(after.sprites[0]), previous_path)
                self.assertTrue(previous_path.is_file(), "config failure must restore the previous sprite folder")
                leftovers = [
                    item.name for item in previous_path.parent.parent.iterdir()
                    if item.name.startswith((".pending-", ".backup-"))
                ]
                self.assertEqual(leftovers, [])
        finally:
            self._remove_probe_character(character)

    def test_replacement_using_source_inside_target_directory_succeeds(self) -> None:
        character = self._add_probe_character("AtomicSelfProbe", "atomic_self_probe")
        state = "atomic_self_state"
        try:
            with tempfile.TemporaryDirectory() as root:
                good = Path(root) / "good.png"
                good.write_bytes(b"good")
                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state, "paths": [good.as_posix()],
                })
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                previous_path = self._sprite_path(saved.sprites[0])

                self.backend.import_character_state_assets({
                    "character_name": character.name, "state_name": state,
                    "paths": [previous_path.as_posix()],
                })

                after = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertTrue(self._sprite_path(after.sprites[0]).is_file())
                leftovers = [
                    item.name for item in previous_path.parent.parent.iterdir()
                    if item.name.startswith((".pending-", ".backup-"))
                ]
                self.assertEqual(leftovers, [])
        finally:
            self._remove_probe_character(character)

    def test_choice_is_published_as_options_and_recorded(self) -> None:
        events: list[tuple[str, object]] = []
        with patch.object(rpc_bridge, "event", side_effect=lambda name, payload=None: events.append((name, payload))):
            self.backend._emit_dialog(
                AgentDialogMessage(character_name="CHOICE", speech="去散步/留在家", emotion="neutral"),
                "request-1",
            )
        self.assertIn("options", [name for name, _ in events])
        history = self.backend._history()
        self.assertEqual(history[-1]["character_name"], "CHOICE")
        self.assertEqual(history[-1]["request_id"], "request-1")

    def test_revert_history_removes_selected_user_turn_and_everything_after_it(self) -> None:
        self.backend._append_history("assistant", "here", "第一条")
        target = self.backend._append_history("user", "你", "从这里重来")
        self.backend._append_history("assistant", "here", "将被删除")
        with patch.object(rpc_bridge, "event"):
            response = self.backend.revert_history({"user_message_id": target["id"]})
        self.assertEqual([item["text"] for item in response["history"]], ["第一条"])
        self.assertEqual(response["display"]["text"], "第一条")

    def test_targeted_sprite_replacement_preserves_voice(self) -> None:
        character = self.backend.config.get_character_by_name(self.backend.config.resolve_active_character_name())
        self.assertIsNotNone(character)
        asset_dir = Path(_APP_HOME.name) / "targeted-sprite-test"
        asset_dir.mkdir(parents=True, exist_ok=True)
        original_image = asset_dir / "original.png"
        replacement_image = asset_dir / "replacement.png"
        voice = asset_dir / "line.wav"
        original_image.write_bytes(b"original")
        replacement_image.write_bytes(b"replacement")
        voice.write_bytes(b"voice")
        character.sprites = [Sprite(
            path=original_image,
            state_name="neutral",
            state_group="core_emotion",
            voice_path=voice,
            voice_text="你好",
        )]
        self.backend.config.save_characters_config()

        response = self.backend.import_character_state_assets({
            "character_name": character.name,
            "sprite_index": 0,
            "state_name": "happy",
            "state_group": "core_emotion",
            "frame_interval_ms": 80,
            "paths": [replacement_image.as_posix()],
        })

        saved = next(item for item in response["config"]["characters"] if item["name"] == character.name)["sprites"][0]
        self.assertEqual(saved["state_name"], "happy")
        self.assertEqual(saved["frame_interval_ms"], 80)
        self.assertEqual(saved["voice_path"], voice.as_posix())
        self.assertEqual(saved["voice_text"], "你好")

    def test_delete_sprite_removes_owned_assets_and_reindexes_emotion_tags(self) -> None:
        character = self.backend.config.get_character_by_name(self.backend.config.resolve_active_character_name())
        self.assertIsNotNone(character)
        original = copy.deepcopy(character)
        prefix = "delete-sprite-test"
        asset_root = self.backend.paths.characters_dir / prefix
        voice_root = self.backend.paths.generated_dir / "voices" / prefix
        first = asset_root / "neutral.png"
        second = asset_root / "happy.png"
        first_voice = voice_root / "neutral.wav"
        external = Path(_APP_HOME.name) / "external-voice.wav"
        try:
            asset_root.mkdir(parents=True, exist_ok=True)
            voice_root.mkdir(parents=True, exist_ok=True)
            first.write_bytes(b"neutral")
            second.write_bytes(b"happy")
            first_voice.write_bytes(b"voice")
            external.write_bytes(b"external")
            character.sprite_prefix = prefix
            character.sprites = [
                Sprite(path=first, state_name="neutral", voice_path=first_voice),
                Sprite(path=second, state_name="happy", voice_path=external),
            ]
            character.emotion_tags = "立绘 1：中立\n立绘 2：开心"
            self.backend.config.save_characters_config()

            response = self.backend.delete_character_sprite({"character_name": character.name, "index": 0})
            saved = next(item for item in response["config"]["characters"] if item["name"] == character.name)
            self.assertEqual(len(saved["sprites"]), 1)
            self.assertEqual(saved["emotion_tags"], "立绘 1：开心")
            self.assertFalse(first.exists())
            self.assertFalse(first_voice.exists())
            self.assertTrue(external.exists())
        finally:
            shutil.rmtree(asset_root, ignore_errors=True)
            shutil.rmtree(voice_root, ignore_errors=True)
            external.unlink(missing_ok=True)
            character.__dict__.update(copy.deepcopy(original.__dict__))
            self.backend.config.save_characters_config()

    def test_delete_character_does_not_remove_unrelated_absolute_prefix(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-unrelated-") as raw:
            unrelated = Path(raw)
            secret = unrelated / "important.txt"
            secret.write_text("keep", encoding="utf-8")
            extra = Character(
                name="AssetGuardVictim",
                color="#84c2d5",
                sprite_prefix=str(unrelated),
                sprites=[],
                character_profile=default_character_profile("AssetGuardVictim"),
                character_setting="test",
            )
            self.backend.config.config.characters.append(extra)
            self.backend.config.save_characters_config()
            try:
                self.backend.delete_character({"name": extra.name})
                names = [item.name for item in self.backend.config.config.characters]
                self.assertNotIn(extra.name, names)
                self.assertTrue(secret.is_file())
            finally:
                self.backend.config.config.characters = [
                    item for item in self.backend.config.config.characters if item.name != extra.name
                ]
                self.backend.config.save_characters_config()

    def test_delete_character_sprite_leaves_files_outside_owned_dir(self) -> None:
        character = self.backend.config.get_character_by_name(self.backend.config.resolve_active_character_name())
        self.assertIsNotNone(character)
        original = copy.deepcopy(character)
        with tempfile.TemporaryDirectory(prefix="here-sprite-out-") as raw:
            outside = Path(raw) / "outside.png"
            outside.write_bytes(b"outside")
            character.sprite_prefix = "../escape"
            character.sprites = [Sprite(path=outside, state_name="neutral")]
            character.emotion_tags = "立绘 1：中立"
            self.backend.config.save_characters_config()
            try:
                self.backend.delete_character_sprite({"character_name": character.name, "index": 0})
                self.assertTrue(outside.is_file())
                saved = next(item for item in self.backend.config.config.characters if item.name == character.name)
                self.assertEqual(saved.sprites, [])
            finally:
                character.__dict__.update(copy.deepcopy(original.__dict__))
                self.backend.config.save_characters_config()

    def test_delete_character_sprite_keeps_shared_prefix_file_used_by_another_character(self) -> None:
        prefix = "shared_sprite_guard"
        asset_root = self.backend.paths.characters_dir / prefix
        shared_file = asset_root / "sprite.png"
        original_characters = list(self.backend.config.config.characters)
        try:
            asset_root.mkdir(parents=True, exist_ok=True)
            shared_file.write_bytes(b"shared")
            owners = [
                Character(
                    name=name,
                    color="#84c2d5",
                    sprite_prefix=prefix,
                    sprites=[Sprite(path=shared_file, state_name="neutral")],
                    character_profile=default_character_profile(name),
                    character_setting="test",
                )
                for name in ("SharedOwnerA", "SharedOwnerB")
            ]
            self.backend.config.config.characters.extend(owners)
            self.backend.config.save_characters_config()

            self.backend.delete_character_sprite({"character_name": "SharedOwnerA", "index": 0})

            self.assertTrue(shared_file.is_file(), "a file another character references must survive")
            remaining_owner = self.backend.config.get_character_by_name("SharedOwnerB")
            self.assertIsNotNone(remaining_owner)
            self.assertEqual(len(remaining_owner.sprites), 1)
            self.assertEqual(Path(remaining_owner.sprites[0].path), shared_file)
        finally:
            self.backend.config.config.characters = original_characters
            shutil.rmtree(asset_root, ignore_errors=True)
            self.backend.config.save_characters_config()

    def test_import_state_assets_refuses_to_clobber_shared_prefix_frames(self) -> None:
        prefix = "shared_import_guard"
        asset_root = self.backend.paths.characters_dir / prefix
        state_dir = asset_root / "animations" / "shared_state"
        shared_file = state_dir / "frame_0001.png"
        original_characters = list(self.backend.config.config.characters)
        try:
            state_dir.mkdir(parents=True, exist_ok=True)
            shared_file.write_bytes(b"shared-frame")
            owners = [
                Character(
                    name=name,
                    color="#84c2d5",
                    sprite_prefix=prefix,
                    sprites=[Sprite(path=shared_file, state_name="shared_state")],
                    character_profile=default_character_profile(name),
                    character_setting="test",
                )
                for name in ("ImportOwnerA", "ImportOwnerB")
            ]
            self.backend.config.config.characters.extend(owners)
            self.backend.config.save_characters_config()

            with tempfile.TemporaryDirectory() as root:
                replacement = Path(root) / "replacement.png"
                replacement.write_bytes(b"replacement")
                with self.assertRaises(UnsafeSpritePrefixError):
                    self.backend.import_character_state_assets({
                        "character_name": "ImportOwnerA",
                        "state_name": "shared_state",
                        "paths": [replacement.as_posix()],
                    })

            self.assertTrue(shared_file.is_file())
            self.assertEqual(shared_file.read_bytes(), b"shared-frame")
            owner_a = self.backend.config.get_character_by_name("ImportOwnerA")
            self.assertEqual(Path(owner_a.sprites[0].path), shared_file)
        finally:
            self.backend.config.config.characters = original_characters
            shutil.rmtree(asset_root, ignore_errors=True)
            self.backend.config.save_characters_config()

    def test_case_only_character_rename_through_save_config_keeps_memory(self) -> None:
        probe = Path(_APP_HOME.name) / "case-probe"
        probe.mkdir()
        try:
            if not (Path(_APP_HOME.name) / "CASE-PROBE").exists():
                self.skipTest("requires a case-insensitive filesystem")
        finally:
            probe.rmdir()
        name = "RenameCaseProbe"
        renamed = name.upper()
        extra = Character(
            name=name,
            color="#84c2d5",
            sprite_prefix="rename_case_probe",
            sprites=[],
            character_profile=default_character_profile(name),
            character_setting="test",
        )
        self.backend.config.config.characters.append(extra)
        self.backend.config.save_characters_config()
        try:
            self.backend.update_memory({"character_name": name, "kind": "character", "entries": ["必须保留"]})
            payload = self.backend.state()
            characters = payload["config"]["characters"]
            for item in characters:
                if item["name"] == name:
                    item["name"] = renamed
            self.backend.save_config({
                "characters": characters,
                "character_rename": {"old_name": name, "new_name": renamed},
            })
            self.assertIn("必须保留", self.backend.memory.read_character_memories(renamed))
            self.assertTrue((self.backend.memory.agent_home(renamed) / "memories" / "MEMORY.md").is_file())
        finally:
            self.backend.memory.delete_character(name)
            self.backend.config.config.characters = [
                item for item in self.backend.config.config.characters if item.name != renamed
            ]
            self.backend.config.save_characters_config()
            self.backend.reload_runtime()

    def test_save_config_rejects_absolute_sprite_prefix(self) -> None:
        payload = self.backend.state()
        characters = payload["config"]["characters"]
        original_prefix = characters[0]["sprite_prefix"]
        characters[0]["sprite_prefix"] = "/tmp/not-owned"
        with self.assertRaises(ValueError):
            self.backend.save_config({"characters": characters})
        saved = next(item for item in self.backend.config.config.characters if item.name == characters[0]["name"])
        self.assertEqual(saved.sprite_prefix, original_prefix)

    def test_chat_ui_theme_snapshot_filters_qss_and_clamps_layout(self) -> None:
        with tempfile.TemporaryDirectory() as root:
            theme_path = Path(root) / "chat_ui_theme.json"
            theme_path.write_text(
                '{"dialog_offset_y": 900, "dialog_width_pct": 12, "dialog_padding": 500, '
                '"options_gap": -4, "dialog_label": {"extra_qss": "color: white; width: 900px; border: 1px solid red;"}}',
                encoding="utf-8",
            )
            snapshot = rpc_bridge.chat_ui_theme_snapshot(theme_path.as_posix())

        self.assertTrue(snapshot["loaded"])
        self.assertEqual(snapshot["dialog_offset_y"], 500)
        self.assertEqual(snapshot["dialog_width_pct"], 30)
        self.assertEqual(snapshot["dialog_padding"], 120)
        self.assertEqual(snapshot["options_gap"], 0)
        self.assertEqual(snapshot["extras"]["dialog_label.extra_qss"], "color: white; border: 1px solid red;")

    def test_chat_platform_bridge_is_restarted_with_selected_channel(self) -> None:
        sentinel = object()
        with (
            patch.object(rpc_bridge, "stop_chat_platform_bridge") as stop,
            patch.object(rpc_bridge, "start_chat_platform_bridge", return_value=sentinel) as start,
        ):
            self.backend._restart_chat_platform_bridge()
        stop.assert_called_once()
        self.assertEqual(start.call_args.kwargs["channel"], self.backend.config.config.system_config.chat_delivery_channel)
        self.assertIs(self.backend.chat_platform_bridge, sentinel)

    def test_asr_callback_accepts_partial_keyword_and_emits_final_semantics(self) -> None:
        class FakeAsrAdapter:
            def __init__(self, callback):
                self.callback = callback
                self.started = False

            def start(self) -> None:
                self.started = True

            def stop(self) -> None:
                pass

            def get_status(self) -> str:
                return "Running" if self.started else "Stopped"

        events: list[tuple[str, object]] = []
        adapter: FakeAsrAdapter | None = None

        def create_adapter(callback):
            nonlocal adapter
            adapter = FakeAsrAdapter(callback)
            return adapter

        with (
            patch.object(rpc_bridge, "create_default_asr_adapter", side_effect=create_adapter),
            patch.object(rpc_bridge, "request_macos_microphone_permission", return_value=(True, "")),
            patch.object(rpc_bridge, "event", side_effect=lambda name, payload=None: events.append((name, payload))),
        ):
            result = self.backend.start_asr()
            self.assertIsNotNone(adapter)
            adapter.callback("正在识别", is_partial=True)
            adapter.callback("识别完成", is_partial=False)

        self.assertEqual(result, {"status": "Running"})
        self.assertEqual(events, [
            ("asr_state", {"running": True, "paused": False}),
            ("transcript", {"text": "正在识别", "final": False}),
            ("transcript", {"text": "识别完成", "final": True}),
        ])

    def test_asr_does_not_start_when_backend_microphone_permission_is_denied(self) -> None:
        with (
            patch.object(
                rpc_bridge,
                "request_macos_microphone_permission",
                return_value=(False, "麦克风权限被拒绝"),
            ),
            patch.object(rpc_bridge, "create_default_asr_adapter") as create_adapter,
        ):
            with self.assertRaisesRegex(RuntimeError, "麦克风权限被拒绝"):
                self.backend.start_asr()

        create_adapter.assert_not_called()

    def test_asr_uses_host_permission_without_rechecking_python_tcc_identity(self) -> None:
        class FakeAsrAdapter:
            def start(self) -> None:
                pass

            def get_status(self) -> str:
                return "Running"

        with (
            patch.object(
                rpc_bridge,
                "request_macos_microphone_permission",
                side_effect=AssertionError("host authorization should skip the sidecar check"),
            ),
            patch.object(rpc_bridge, "create_default_asr_adapter", return_value=FakeAsrAdapter()),
            patch.object(rpc_bridge, "event"),
        ):
            result = self.backend.start_asr({"__here_macos_microphone_authorized": True})

        self.assertEqual(result, {"status": "Running"})

    def test_prepare_asr_uses_explicit_vosk_model_path(self) -> None:
        custom_path = "/tmp/custom-vosk-model"
        with (
            patch.object(rpc_bridge, "missing_asr_requirements", return_value=[]),
            patch.object(rpc_bridge, "build_asr_setup_status", return_value=SimpleNamespace(ready=True, needs_model=False)) as build_status,
        ):
            result = self.backend.prepare_asr({"provider": "vosk", "model_path": custom_path})

        self.assertEqual(result["model"], custom_path)
        build_status.assert_called_once_with("vosk", model_path=custom_path)

    def test_prepare_asr_downloads_missing_vosk_model_before_ready_check(self) -> None:
        custom_path = "/tmp/missing-vosk-model"
        statuses = iter([
            SimpleNamespace(ready=False, needs_model=True, user_message=lambda: "missing"),
            SimpleNamespace(ready=True, needs_model=False, user_message=lambda: "ready"),
        ])
        with (
            patch.object(rpc_bridge, "missing_asr_requirements", return_value=[]),
            patch.object(rpc_bridge, "build_asr_setup_status", side_effect=lambda *_args, **_kwargs: next(statuses)),
            patch.object(self.backend, "_download_vosk_model", return_value=custom_path) as download,
        ):
            result = self.backend.prepare_asr({"provider": "vosk", "model_path": custom_path})

        download.assert_called_once_with(custom_path)
        self.assertEqual(result["model"], custom_path)

    def test_dependency_status_uses_saved_vosk_model_path(self) -> None:
        custom_path = "/tmp/saved-vosk-model"
        self.backend.config.config.api_config.asr_extra_configs["vosk"] = {"model_path": custom_path}
        with patch.object(
            rpc_bridge,
            "build_asr_setup_status",
            return_value=SimpleNamespace(ready=True),
        ) as build_status:
            self.backend.dependency_status()

        vosk_call = next(call for call in build_status.call_args_list if call.args[0] == "vosk")
        self.assertEqual(vosk_call.kwargs["model_path"], custom_path)

    def test_cg_marks_no_person_scene_as_background_only(self) -> None:
        class FakeT2I:
            def t2i(self, prompt: str) -> str:
                return "/tmp/generated-background.png"

        events: list[tuple[str, object]] = []
        with (
            patch.object(self.backend, "t2i", FakeT2I()),
            patch.object(rpc_bridge, "event", side_effect=lambda name, payload=None: events.append((name, payload))),
        ):
            self.backend._emit_dialog(
                AgentDialogMessage(character_name="CG", speech="a room, no person in the scene"),
                "request-cg",
            )

        cg_payload = next(payload for name, payload in events if name == "cg")
        self.assertTrue(cg_payload["background_only"])
        self.assertEqual(cg_payload["request_id"], "request-cg")

    def test_runtime_reload_discards_the_old_asr_adapter(self) -> None:
        class FakeAsrAdapter:
            stopped = False

            def stop(self) -> None:
                self.stopped = True

        adapter = FakeAsrAdapter()
        self.backend.asr_adapter = adapter

        events: list[tuple[str, object]] = []
        with patch.object(rpc_bridge, "event", side_effect=lambda name, payload=None: events.append((name, payload))):
            self.backend.reload_runtime()

        self.assertTrue(adapter.stopped)
        self.assertIsNone(self.backend.asr_adapter)
        self.assertIn(("asr_state", {"running": False, "paused": False}), events)

    def test_realtime_sprite_uses_cache_for_same_prompt_and_provider(self) -> None:
        class FakeT2I:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []

            def t2i(self, prompt: str, *, file_path: str) -> str:
                self.calls.append((prompt, file_path))
                Path(file_path).write_bytes(b"generated")
                return file_path

        fake = FakeT2I()
        with tempfile.TemporaryDirectory() as cache_dir, patch.object(self.backend, "t2i", fake):
            system = self.backend.config.config.system_config
            system.sprite_realtime_enabled = True
            system.sprite_realtime_cache_dir = cache_dir
            system.sprite_realtime_prompt_template = "{character_name}|{emotion}|{scene}"
            payload = {"character_name": self.backend.config.resolve_active_character_name(), "emotion": "happy", "scene": "park"}

            first = self.backend.generate_realtime_sprite(payload)
            second = self.backend.generate_realtime_sprite(payload)

        self.assertEqual(len(fake.calls), 1)
        self.assertEqual(fake.calls[0][0], f"{payload['character_name']}|happy|park")
        self.assertEqual(first["path"], second["path"])

    def test_storage_config_rolls_back_when_migration_fails(self) -> None:
        before = load_storage_paths(self.backend.paths.root)
        with tempfile.TemporaryDirectory() as root, patch.object(
            rpc_bridge, "migrate_storage_locations", side_effect=RuntimeError("copy failed")
        ):
            with self.assertRaisesRegex(RuntimeError, "copy failed"):
                self.backend.save_storage({
                    "character_memory_dir": str(Path(root) / "memory"),
                    "character_assets_dir": str(Path(root) / "assets"),
                    "copy_memory": True,
                    "copy_assets": True,
                })
        self.assertEqual(load_storage_paths(self.backend.paths.root), before)

    def test_create_character_requires_confirmation_payload_and_imports_states(self) -> None:
        count = len(self.backend.config.config.characters)
        with self.assertRaisesRegex(ValueError, "角色名"):
            self.backend.create_character({})
        self.assertEqual(len(self.backend.config.config.characters), count)

        original_characters = copy.deepcopy(self.backend.config.config.characters)
        original_active = self.backend.config.resolve_active_character_name()
        created_prefix = ""
        with tempfile.TemporaryDirectory() as root:
            neutral = Path(root) / "neutral.png"
            happy = Path(root) / "happy.png"
            neutral.write_bytes(b"neutral")
            happy.write_bytes(b"happy")
            try:
                result = self.backend.create_character({
                    "name": "Electron创建测试",
                    "setting": "测试人设",
                    "visual_identity": "测试外观",
                    "character_profile": {
                        "identity": {"age": 28, "gender": "虚拟角色", "occupation": "设计师"},
                        "personality": {"mbti": "INTJ", "custom_traits": ["冷静"]},
                        "speech": {"tone": ["简洁"]},
                        "relationship": {"stage": "朋友"},
                        "preferences": {"likes": ["绘画"]},
                        "boundaries": {"adult": True, "intimacy_level": "普通陪伴"},
                    },
                    "states": [
                        {"state_name": "neutral", "paths": [neutral.as_posix()], "frame_interval_ms": 120},
                        {"state_name": "happy", "paths": [happy.as_posix()], "frame_interval_ms": 80},
                    ],
                })
                created = next(item for item in result["config"]["characters"] if item["name"] == "Electron创建测试")
                created_prefix = created["sprite_prefix"]
                self.assertEqual(created["visual_identity"], "测试外观")
                self.assertEqual(created["character_profile"]["identity"]["age"], 28)
                self.assertEqual(created["character_profile"]["identity"]["occupation"], "设计师")
                self.assertEqual(created["character_profile"]["personality"]["mbti"], "INTJ")
                self.assertEqual(created["character_profile"]["preferences"]["likes"], ["绘画"])
                self.assertEqual({item["state_name"] for item in created["sprites"]}, {"neutral", "happy"})
                self.assertEqual(created["visual_reference_image"], created["sprites"][0]["path"])
                self.assertIn("neutral", created["emotion_tags"])
                self.assertIn("happy", created["emotion_tags"])
            finally:
                if created_prefix:
                    import shutil
                    shutil.rmtree(self.backend.paths.characters_dir / created_prefix, ignore_errors=True)
                self.backend.config.config.characters = original_characters
                self.backend.config.save_characters_config()
                self.backend.config.set_active_character_name(original_active)
                self.backend.reload_runtime()


class RpcBridgeScriptEntryTests(unittest.TestCase):
    def test_script_entry_emits_ready_and_answers_ping(self) -> None:
        with tempfile.TemporaryDirectory(prefix="here-rpc-entry-") as app_home:
            process = subprocess.Popen(
                [sys.executable, str(_BACKEND_ROOT / "rpc_bridge.py")],
                cwd=_BACKEND_ROOT,
                env={
                    **os.environ,
                    "HERE_APP_HOME": app_home,
                    "HERE_PROJECT_ROOT": str(_BACKEND_ROOT),
                    "PYTHONUNBUFFERED": "1",
                },
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            try:
                stdout, stderr = process.communicate(
                    '{"id":"entry-ping","method":"ping","params":{}}\n',
                    timeout=20,
                )
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                self.fail(f"rpc_bridge.py timed out\nstdout={stdout}\nstderr={stderr}")

        self.assertEqual(process.returncode, 0, stderr)
        messages = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        self.assertTrue(messages, stdout)
        for message in messages:
            self.assertIn(message.get("type"), {"event", "response"})
        self.assertEqual(messages[0]["type"], "event")
        self.assertEqual(messages[0]["event"], "ready")
        ping = next(item for item in messages if item.get("type") == "response" and item.get("id") == "entry-ping")
        self.assertTrue(ping["ok"])
        self.assertEqual(ping["result"]["ok"], True)


if __name__ == "__main__":
    unittest.main()
