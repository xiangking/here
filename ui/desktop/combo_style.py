"""Shared styling for combo-box popup views."""

from __future__ import annotations

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QApplication, QComboBox


COMBO_POPUP_QSS = """
QAbstractItemView {
    color: rgba(255, 255, 255, 230);
    background-color: rgb(24, 26, 32);
    selection-background-color: rgba(76, 175, 80, 190);
    selection-color: rgb(255, 255, 255);
    border: 1px solid rgba(255, 255, 255, 58);
    border-radius: 6px;
    outline: 0;
    padding: 4px 0;
}
QAbstractItemView::item {
    min-height: 28px;
    padding: 5px 10px;
    border: none;
    background: transparent;
}
QAbstractItemView::item:selected {
    background: rgba(76, 175, 80, 190);
    color: rgb(255, 255, 255);
}
QAbstractItemView::item:hover {
    background: rgba(255, 255, 255, 28);
}
QScrollBar:vertical {
    width: 8px;
    background: transparent;
    margin: 4px 2px 4px 0;
}
QScrollBar::handle:vertical {
    background: rgba(255, 255, 255, 90);
    border-radius: 4px;
    min-height: 22px;
}
QScrollBar::add-line:vertical,
QScrollBar::sub-line:vertical {
    height: 0;
    border: none;
    background: transparent;
}
"""


def style_combo_popup(combo: QComboBox) -> None:
    if bool(combo.property("_here_combo_popup_styling")):
        return
    combo.setProperty("_here_combo_popup_styling", True)
    try:
        view = combo.view()
    finally:
        combo.setProperty("_here_combo_popup_styling", False)
    if view is None:
        return
    if bool(view.property("_here_combo_popup_styled")):
        return
    combo.setProperty("_here_combo_popup_styled", True)
    view.setProperty("_here_combo_popup_styled", True)
    view.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    view.setFrameShape(view.Shape.StyledPanel)
    view.setUniformItemSizes(True)
    view.setMouseTracking(True)
    view.setAutoFillBackground(True)
    view.setStyleSheet(COMBO_POPUP_QSS)
    viewport = view.viewport()
    if viewport is not None:
        viewport.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        viewport.setAutoFillBackground(True)
        viewport.setStyleSheet("background-color: rgb(24, 26, 32);")


class _ComboPopupStyleFilter(QObject):
    def eventFilter(self, obj, event):  # noqa: N802 - Qt API name
        if isinstance(obj, QComboBox) and event.type() in {
            QEvent.Type.Polish,
            QEvent.Type.Show,
        }:
            try:
                style_combo_popup(obj)
            except RuntimeError:
                pass
        return False


def install_combo_popup_style(app: QApplication | None = None) -> _ComboPopupStyleFilter | None:
    qapp = app if app is not None else QApplication.instance()
    if qapp is None:
        return None
    existing = getattr(qapp, "_here_combo_popup_style_filter", None)
    if existing is not None:
        return existing
    event_filter = _ComboPopupStyleFilter(qapp)
    qapp.installEventFilter(event_filter)
    setattr(qapp, "_here_combo_popup_style_filter", event_filter)
    for widget in qapp.allWidgets():
        if isinstance(widget, QComboBox):
            style_combo_popup(widget)
    return event_filter
