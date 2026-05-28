from __future__ import annotations

from PySide6.QtCore import QCoreApplication
import numpy as np

from core.runtime import ui_update_manager as ui_mod
from core.runtime.ui_update_manager import UIUpdateManager


def _app():
    return QCoreApplication.instance() or QCoreApplication([])


def _write_png(path):
    import cv2

    rgba = np.zeros((2, 2, 4), dtype=np.uint8)
    rgba[:, :, 3] = 255
    bgra = cv2.cvtColor(rgba, cv2.COLOR_RGBA2BGRA)
    ok, data = cv2.imencode(".png", bgra)
    assert ok
    path.write_bytes(data.tobytes())


def test_update_sprite_keeps_current_state_when_static_path_is_empty(monkeypatch):
    _app()
    manager = UIUpdateManager()
    character = type("Character", (), {"sprites": [{"path": ""}], "sprite_scale": 1.0})()
    monkeypatch.setattr(ui_mod, "get_character_by_name", lambda _name: character)

    called = []
    manager.update_sprite_signal.connect(lambda *args: called.append(args))
    manager.update_sprite_animation_signal.connect(lambda *args: called.append(args))

    manager.update_sprite("TestChar", 0)

    assert called == []


def test_update_sprite_keeps_current_state_when_assets_are_missing(monkeypatch, tmp_path):
    _app()
    manager = UIUpdateManager()
    character = type(
        "Character",
        (),
        {
            "sprites": [
                {
                    "path": str(tmp_path / "missing.png"),
                    "frames": [str(tmp_path / "frame_01.png"), str(tmp_path / "frame_02.png")],
                }
            ],
            "sprite_scale": 1.0,
        },
    )()
    monkeypatch.setattr(ui_mod, "get_character_by_name", lambda _name: character)

    called = []
    manager.update_sprite_signal.connect(lambda *args: called.append(args))
    manager.update_sprite_animation_signal.connect(lambda *args: called.append(args))

    manager.update_sprite("TestChar", 0)

    assert called == []


def test_update_sprite_posts_animation_when_multiple_frames_exist(monkeypatch, tmp_path):
    _app()
    frame_1 = tmp_path / "frame_01.png"
    frame_2 = tmp_path / "frame_02.png"
    _write_png(frame_1)
    _write_png(frame_2)
    manager = UIUpdateManager()
    character = type(
        "Character",
        (),
        {
            "sprites": [
                {
                    "path": "",
                    "frames": [str(frame_1), str(frame_2)],
                    "frame_interval_ms": 80,
                }
            ],
            "sprite_scale": 0.75,
        },
    )()
    monkeypatch.setattr(ui_mod, "get_character_by_name", lambda _name: character)

    static_updates = []
    animation_updates = []
    manager.update_sprite_signal.connect(lambda *args: static_updates.append(args))
    manager.update_sprite_animation_signal.connect(lambda *args: animation_updates.append(args))

    manager.update_sprite("TestChar", 0)

    assert static_updates == []
    assert len(animation_updates) == 1
    frames, name, scale, interval = animation_updates[0]
    assert len(frames) == 2
    assert name == "TestChar"
    assert scale == 0.75
    assert interval == 80


def test_update_sprite_treats_single_valid_frame_as_static_image(monkeypatch, tmp_path):
    _app()
    frame_1 = tmp_path / "frame_01.png"
    _write_png(frame_1)
    manager = UIUpdateManager()
    character = type(
        "Character",
        (),
        {
            "sprites": [
                {
                    "path": "",
                    "frames": [str(frame_1), str(tmp_path / "missing.png")],
                    "frame_interval_ms": 80,
                }
            ],
            "sprite_scale": 0.75,
        },
    )()
    monkeypatch.setattr(ui_mod, "get_character_by_name", lambda _name: character)

    static_updates = []
    animation_updates = []
    manager.update_sprite_signal.connect(lambda *args: static_updates.append(args))
    manager.update_sprite_animation_signal.connect(lambda *args: animation_updates.append(args))

    manager.update_sprite("TestChar", 0)

    assert len(static_updates) == 1
    assert animation_updates == []
    image, name, scale = static_updates[0]
    assert image.shape == (2, 2, 4)
    assert name == "TestChar"
    assert scale == 0.75
