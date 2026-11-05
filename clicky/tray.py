"""System tray icon and menu: status, model picker, buddy visibility, forget conversation, quit."""

from __future__ import annotations

from collections.abc import Callable, Mapping

from PySide6.QtCore import QObject, QPointF, Qt, Signal
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

STATE_DESCRIPTIONS = {
    "idle": "ready",
    "listening": "listening…",
    "processing": "thinking…",
    "responding": "talking…",
}
STATE_COLORS = {
    "idle": QColor(59, 130, 246),
    "listening": QColor(34, 197, 94),
    "processing": QColor(168, 85, 247),
    "responding": QColor(59, 130, 246),
}


def draw_tray_icon(fill_color: QColor) -> QIcon:
    icon = QIcon()
    for size in (16, 20, 24, 32, 48, 64):
        pixmap = QPixmap(size, size)
        pixmap.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        scale = size / 32
        triangle = QPolygonF(
            [QPointF(5 * scale, 3 * scale), QPointF(12 * scale, 29 * scale), QPointF(28 * scale, 15 * scale)]
        )
        painter.setPen(QPen(QColor(255, 255, 255), max(1.0, 2.0 * scale)))
        painter.setBrush(fill_color)
        painter.drawPolygon(triangle)
        painter.end()
        icon.addPixmap(pixmap)
    return icon


class ClickyTray(QObject):
    model_selected = Signal(str)
    always_visible_toggled = Signal(bool)
    effort_selected = Signal(str)
    notepad_toggled = Signal(bool)
    forget_requested = Signal()
    clear_requested = Signal()
    quit_requested = Signal()

    def __init__(
        self,
        *,
        hotkey_text: str,
        models: Mapping[str, str],
        selected_model: str,
        always_visible: bool,
        effort_levels: Mapping[str, str] | None = None,
        selected_effort: str = "medium",
        notepad_visible: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self._hotkey_text = hotkey_text
        self._icons = {state: draw_tray_icon(color) for state, color in STATE_COLORS.items()}
        self._tray_icon = QSystemTrayIcon(self._icons["idle"], self)
        self._menu = QMenu()

        self._status_action = QAction("Clicky — ready", self._menu)
        self._status_action.setEnabled(False)
        self._menu.addAction(self._status_action)
        hint_action = QAction(f"Hold {self.pretty_hotkey} and talk", self._menu)
        hint_action.setEnabled(False)
        self._menu.addAction(hint_action)
        self._menu.addSeparator()

        model_menu = self._menu.addMenu("Model")
        model_group = QActionGroup(model_menu)
        model_group.setExclusive(True)
        for model_id, model_name in models.items():
            model_action = QAction(model_name, model_menu, checkable=True)
            model_action.setChecked(model_id == selected_model)
            model_action.triggered.connect(self._make_model_handler(model_id))
            model_group.addAction(model_action)
            model_menu.addAction(model_action)

        if effort_levels:
            thinking_menu = self._menu.addMenu("Thinking")
            effort_group = QActionGroup(thinking_menu)
            effort_group.setExclusive(True)
            effort_hints = {
                "low": "quickest replies",
                "medium": "smarter, a bit slower",
                "high": "most careful, slowest",
            }
            for effort_id, effort_name in effort_levels.items():
                hint = effort_hints.get(effort_id)
                effort_action = QAction(
                    f"{effort_name} ({hint})" if hint else effort_name, thinking_menu, checkable=True
                )
                effort_action.setChecked(effort_id == selected_effort)
                effort_action.triggered.connect(self._make_effort_handler(effort_id))
                effort_group.addAction(effort_action)
                thinking_menu.addAction(effort_action)

        notepad_action = QAction("Show notepad", self._menu, checkable=True)
        notepad_action.setChecked(notepad_visible)
        notepad_action.toggled.connect(self.notepad_toggled.emit)
        self._menu.addAction(notepad_action)

        always_visible_action = QAction("Always show buddy", self._menu, checkable=True)
        always_visible_action.setChecked(always_visible)
        always_visible_action.toggled.connect(self.always_visible_toggled.emit)
        self._menu.addAction(always_visible_action)

        clear_action = QAction("Clear screen (Esc)", self._menu)
        clear_action.triggered.connect(self.clear_requested.emit)
        self._menu.addAction(clear_action)

        forget_action = QAction("Forget conversation", self._menu)
        forget_action.triggered.connect(self.forget_requested.emit)
        self._menu.addAction(forget_action)
        self._menu.addSeparator()

        quit_action = QAction("Quit Clicky", self._menu)
        quit_action.triggered.connect(self.quit_requested.emit)
        self._menu.addAction(quit_action)

        self._tray_icon.setContextMenu(self._menu)
        self._tray_icon.setToolTip(f"Clicky — hold {self.pretty_hotkey} to talk")
        self._tray_icon.activated.connect(self._on_activated)

    @property
    def pretty_hotkey(self) -> str:
        return " + ".join(part.strip().replace("_", " ").title() for part in self._hotkey_text.split("+"))

    def _make_model_handler(self, model_id: str) -> Callable[[bool], None]:
        def handle_model_triggered(checked: bool) -> None:
            if checked:
                self.model_selected.emit(model_id)

        return handle_model_triggered

    def _make_effort_handler(self, effort_id: str) -> Callable[[bool], None]:
        def handle_effort_triggered(checked: bool) -> None:
            if checked:
                self.effort_selected.emit(effort_id)

        return handle_effort_triggered

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._tray_icon.showMessage(
                "Clicky",
                f"Hold {self.pretty_hotkey} and talk. Right-click for options.",
                QSystemTrayIcon.MessageIcon.Information,
                3000,
            )

    def show(self) -> None:
        self._tray_icon.show()

    def hide(self) -> None:
        self._tray_icon.hide()

    def set_state(self, state: str) -> None:
        self._status_action.setText(f"Clicky — {STATE_DESCRIPTIONS.get(state, state)}")
        self._tray_icon.setIcon(self._icons.get(state, self._icons["idle"]))

    def show_message(self, title: str, message: str) -> None:
        self._tray_icon.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 4000)
