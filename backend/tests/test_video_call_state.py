from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


_BACKEND_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_BACKEND_ROOT))

from services.config.video_call_state import migrate_here_video_call  # noqa: E402


class VideoCallStateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.defaults = root / "defaults"
        (self.defaults / "here").mkdir(parents=True)
        for name in ("here_neutral.png", "video_call.mp4"):
            (self.defaults / "here" / name).write_bytes(name.encode())
        self.assets = root / "characters"

    def test_migrates_old_frames_to_still_and_separate_video(self):
        neutral = {"path": "defaults/characters/here/animations/neutral/frame_001.png",
                   "frames": ["a.png", "b.png"], "state_name": "neutral"}
        characters = [{"name": "here", "sprites": [neutral]}]
        self.assertTrue(migrate_here_video_call(characters, self.assets, self.defaults))
        self.assertEqual(neutral["frames"], [])
        self.assertTrue(Path(neutral["path"]).is_file())
        self.assertEqual(characters[0]["sprites"][1]["state_name"], "video_call")
        self.assertTrue(Path(characters[0]["sprites"][1]["path"]).is_file())
        self.assertFalse(migrate_here_video_call(characters, self.assets, self.defaults))

    def test_preserves_existing_static_portrait_and_call(self):
        neutral = {"path": "/user/here/here_neutral.png", "state_name": "neutral"}
        call = {"path": "/custom.mp4", "state_name": "video_call"}
        characters = [{"name": "here", "sprites": [neutral, call]}]
        self.assertFalse(migrate_here_video_call(characters, self.assets, self.defaults))
        self.assertEqual(characters[0]["sprites"], [neutral, call])

    def test_leaves_unrelated_user_portraits_untouched(self):
        characters = [{"name": "here", "sprites": [{"path": "/my-image.png", "state_name": "neutral"}]}]
        self.assertFalse(migrate_here_video_call(characters, self.assets, self.defaults))
        self.assertEqual(len(characters[0]["sprites"]), 1)
