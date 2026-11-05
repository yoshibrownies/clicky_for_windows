"""Offscreen smoke tests: the GUI pieces construct, animate and paint without errors."""

import time

from PySide6.QtGui import QImage
from PySide6.QtWidgets import QApplication

from clicky.config import AVAILABLE_MODELS
from clicky.hotkey import PushToTalkEvent


def pump(seconds: float) -> None:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        time.sleep(0.005)


def render(widget) -> QImage:
    return widget.grab().toImage()


def test_overlay_runs_through_every_state_and_paints(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        for state in ("listening", "processing", "responding", "idle"):
            overlay.set_state(state)
            overlay.set_audio_level(0.8)
            overlay.show_transcript("where is the save button")
            overlay.show_reply("it's up in the top left, see the floppy disk? " * 8)
            overlay.show_notice("couldn't reach the worker")
            pump(0.05)
            assert not render(overlay).isNull()
        overlay.fly_to(300, 200, "save button")
        pump(0.1)
        assert overlay._mode in ("flying", "holding")
        rendered = render(overlay)
        assert any(rendered.pixel(x, y) != 0 for x in range(0, 120, 3) for y in range(0, 120, 3))
    finally:
        overlay.close()


def test_overlay_returns_to_cursor_when_user_talks_again(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        overlay.set_state("responding")
        overlay.fly_to(500, 500, "x")
        pump(0.05)
        overlay.set_state("listening")
        assert overlay._mode == "returning"
    finally:
        overlay.close()


def test_tray_builds_menu_and_emits_model_choice(qt_app):
    from clicky.tray import ClickyTray

    tray = ClickyTray(
        hotkey_text="ctrl+alt", models=AVAILABLE_MODELS, selected_model="claude-opus-5-5", always_visible=True
    )
    chosen = []
    tray.model_selected.connect(chosen.append)
    model_menu = next(action.menu() for action in tray._menu.actions() if action.text() == "Model")
    sonnet_action = next(action for action in model_menu.actions() if "Sonnet" in action.text())
    sonnet_action.trigger()
    assert chosen == ["claude-sonnet-5-5"]
    assert tray.pretty_hotkey == "Ctrl + Alt"
    tray.set_state("listening")
    assert "listening" in tray._status_action.text()


def test_speech_player_stop_without_play_is_safe(qt_app):
    from clicky.playback import SpeechPlayer

    player = SpeechPlayer()
    finished = []
    player.finished.connect(lambda: finished.append(True))
    player.stop()
    assert finished == []
    player.play(b"not really an mp3")
    player.stop()
    assert finished == [True]
    assert not player.is_playing


def test_hotkey_bridge_forwards_events(qt_app):
    from clicky.app import HotkeyBridge

    bridge = HotkeyBridge()
    received = []
    bridge.pressed.connect(lambda: received.append("pressed"))
    bridge.released.connect(lambda: received.append("released"))
    bridge.cancelled.connect(lambda: received.append("cancelled"))
    for event in (PushToTalkEvent.PRESSED, PushToTalkEvent.RELEASED, PushToTalkEvent.CANCELLED):
        bridge.forward(event)
    assert received == ["pressed", "released", "cancelled"]
