import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication

from clicky.status_pill import StatusPill


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def test_labels_follow_the_companion_state(qt_app):
    pill = StatusPill(hide_delay_seconds=0.1, fade_seconds=0.1)
    try:
        pill.set_state("listening")
        assert pill.isVisible() and pill.label == "Listening"
        pill.set_audio_level(0.7)
        pill.set_state("processing")
        assert pill.label == "Thinking"
        pill.set_state("responding")
        assert pill.label == "Speaking"
        pump(0.1)
        assert pill.is_animating
        assert not pill.grab().toImage().isNull()
    finally:
        pill.close()


def test_idle_fades_out_hides_and_stops_its_timer(qt_app):
    pill = StatusPill(hide_delay_seconds=0.1, fade_seconds=0.1)
    try:
        pill.set_state("responding")
        pump(0.05)
        pill.set_state("idle")
        assert pill.isVisible()  # lingers briefly
        pump(0.5)
        assert not pill.isVisible()
        assert not pill.is_animating
    finally:
        pill.close()


def test_pill_is_click_through_and_never_focused(qt_app):
    pill = StatusPill()
    try:
        flags = pill.windowFlags()
        assert flags & Qt.WindowType.WindowTransparentForInput
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    finally:
        pill.close()
