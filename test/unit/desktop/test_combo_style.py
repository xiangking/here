from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QApplication, QComboBox

from ui.desktop.combo_style import install_combo_popup_style, style_combo_popup


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_combo_popup_style_applies_to_explicit_combo() -> None:
    _app()
    combo = QComboBox()
    combo.addItems(["one", "two"])

    style_combo_popup(combo)

    view = combo.view()
    assert view.property("_here_combo_popup_styled") is True
    assert "rgb(24, 26, 32)" in view.styleSheet()
    assert "rgb(24, 26, 32)" in view.viewport().styleSheet()


def test_combo_popup_style_filter_applies_to_new_combos() -> None:
    app = _app()
    install_combo_popup_style(app)
    combo = QComboBox()
    combo.addItems(["one", "two"])

    app.sendEvent(combo, QEvent(QEvent.Type.Polish))

    view = combo.view()
    assert view.property("_here_combo_popup_styled") is True
    assert "rgb(24, 26, 32)" in view.styleSheet()
