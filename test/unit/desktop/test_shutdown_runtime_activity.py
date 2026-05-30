from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import numpy as np
from PySide6.QtWidgets import QApplication

from ui.desktop.busy_bar import BusyBar
from ui.desktop.components import SpritePanel, TypingLabel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_busy_bar_shutdown_stops_timers() -> None:
    app = _app()
    bar = BusyBar(None)
    bar.show_with("working", 10)

    assert bar._timer.isActive()
    assert bar._breathe_timer.isActive()

    bar.stop_runtime_activity()
    app.processEvents()

    assert not bar._timer.isActive()
    assert not bar._breathe_timer.isActive()


def test_typing_label_shutdown_stops_typewriter_timer() -> None:
    _app()
    label = TypingLabel()
    label.setDisplayWords("hello shutdown")

    assert label.typing_timer.isActive()
    assert label._is_typing is True

    label.stop_runtime_activity()

    assert not label.typing_timer.isActive()
    assert label._is_typing is False


def test_sprite_panel_shutdown_stops_frame_animation() -> None:
    _app()
    panel = SpritePanel(320, 240, max_slots_num=1)
    frames = [
        np.full((4, 4, 4), fill_value=255, dtype=np.uint8),
        np.full((4, 4, 4), fill_value=128, dtype=np.uint8),
    ]

    panel.switch_animation("here", frames, character_rate=1.0, frame_interval_ms=20)
    sprite = panel.sprite_slots[0]

    assert sprite.frame_timer.isActive()

    panel.stop_runtime_activity()

    assert not sprite.frame_timer.isActive()
    assert sprite._animation_frames == []
