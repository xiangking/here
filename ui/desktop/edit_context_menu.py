"""Readable standard edit menus for Qt text inputs."""

from __future__ import annotations

from PySide6.QtCore import QPoint, Qt
from PySide6.QtWidgets import QLineEdit, QPlainTextEdit, QTextEdit, QWidget

from ui.desktop import styles


EDIT_WIDGET_TYPES = (QLineEdit, QPlainTextEdit, QTextEdit)


def install_readable_edit_menus(root: QWidget) -> None:
    """Use the app menu colors for standard cut/copy/paste menus under ``root``."""
    for widget_type in EDIT_WIDGET_TYPES:
        for widget in root.findChildren(widget_type):
            if widget.property("_here_readable_edit_menu"):
                continue
            widget.setProperty("_here_readable_edit_menu", True)
            widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
            widget.customContextMenuRequested.connect(
                lambda pos, w=widget: _show_standard_edit_menu(w, pos)
            )


def _show_standard_edit_menu(widget: QWidget, pos: QPoint) -> None:
    create_menu = getattr(widget, "createStandardContextMenu", None)
    if create_menu is None:
        return
    menu = create_menu()
    menu.setStyleSheet(styles.menu_popup())
    menu.exec(widget.mapToGlobal(pos))
