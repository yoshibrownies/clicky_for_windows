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
        hotkey_text="ctrl+alt", models=AVAILABLE_MODELS, selected_model="gpt-6.1-terra", always_visible=True
    )
    chosen = []
    tray.model_selected.connect(chosen.append)
    model_menu = next(action.menu() for action in tray._menu.actions() if action.text() == "Model")
    sol_action = next(action for action in model_menu.actions() if "Sol" in action.text())
    sol_action.trigger()
    assert chosen == ["gpt-6.1-sol"]
    assert not any("Claude" in action.text() for action in model_menu.actions())
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


def test_idle_overlay_stops_repainting_and_uses_a_coarse_timer(qt_app):
    from PySide6.QtCore import Qt

    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        assert overlay._frame_timer.timerType() != Qt.TimerType.PreciseTimer
        pump(0.8)  # fade in and settle next to the (unmoving) cursor
        update_calls = []
        original_update = overlay.update
        overlay.update = lambda *arguments: (update_calls.append(1), original_update(*arguments))
        pump(0.5)
        assert len(update_calls) <= 2, f"idle overlay repainted {len(update_calls)} times in 0.5 s"
        overlay.set_state("listening")  # animating states still repaint every frame
        pump(0.3)
        assert len(update_calls) >= 10
    finally:
        overlay.close()


def test_hidden_idle_overlay_slows_its_timer(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        overlay.set_always_visible(False)
        pump(1.6)  # past the idle fade delay
        assert not overlay.isVisible()
        assert overlay._frame_timer.interval() >= 100
        overlay.set_state("listening")
        assert overlay._frame_timer.interval() <= 20
    finally:
        overlay.close()


def test_tray_thinking_menu_and_notepad_toggle(qt_app):
    from clicky.config import EFFORT_LEVELS
    from clicky.tray import ClickyTray

    tray = ClickyTray(
        hotkey_text="ctrl+alt",
        models=AVAILABLE_MODELS,
        selected_model="gpt-6.1-terra",
        always_visible=True,
        effort_levels=EFFORT_LEVELS,
        selected_effort="medium",
        notepad_visible=True,
    )
    efforts, notepad_states = [], []
    tray.effort_selected.connect(efforts.append)
    tray.notepad_toggled.connect(notepad_states.append)
    thinking_menu = next(action.menu() for action in tray._menu.actions() if action.text() == "Thinking")
    deep_action = next(action for action in thinking_menu.actions() if action.text().startswith("Deep"))
    deep_action.trigger()
    notepad_action = next(action for action in tray._menu.actions() if action.text() == "Show lesson card")
    assert notepad_action.isChecked()
    notepad_action.trigger()
    assert efforts == ["high"]
    assert notepad_states == [False]


def test_tray_clear_screen_item_emits(qt_app):
    from clicky.tray import ClickyTray

    tray = ClickyTray(
        hotkey_text="ctrl+alt", models=AVAILABLE_MODELS, selected_model="gpt-6.1-terra", always_visible=True
    )
    requests = []
    tray.clear_requested.connect(lambda: requests.append(True))
    clear_action = next(action for action in tray._menu.actions() if action.text().startswith("Clear screen"))
    clear_action.trigger()
    assert requests == [True]


def test_overlay_dismiss_bubble_hides_it_and_brings_the_buddy_back(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        overlay.show_notice("something")
        overlay.fly_to(400, 300, "x")
        assert overlay.has_bubble
        overlay.dismiss_bubble()
        assert not overlay.has_bubble
        assert overlay._mode == "returning"
    finally:
        overlay.close()


def test_clear_all_reaches_every_visual_and_reports_visibility(qt_app):
    from clicky.app import build_clear_controls

    calls = []

    class Fake:
        def __init__(self, name, visible=False):
            self.name, self.visible = name, visible

        def clear(self):
            calls.append(self.name)

        cancel = dismiss_bubble = hide_options = release_guide = forget_marks = clear

        def isVisible(self):  # noqa: N802 (mirrors Qt)
            return self.visible

        def visible_windows(self):
            return [1] if self.visible else []

        @property
        def has_bubble(self):
            return self.visible

    director, layer, card, chips, overlay = (
        Fake("director"),
        Fake("layer"),
        Fake("card", visible=True),
        Fake("chips"),
        Fake("overlay"),
    )
    clear_all, something_visible = build_clear_controls(director, layer, card, chips, overlay)
    assert something_visible()
    clear_all()
    # the card forgets its marks then clears; the overlay drops the bubble, then frees the buddy
    assert calls == ["director", "layer", "card", "card", "chips", "overlay", "overlay"]
    card.visible = False
    assert not something_visible()


def test_overlay_guide_mode_follows_the_pen_then_returns(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        overlay.guide_to(700, 420)
        pump(0.5)
        x, y = overlay._buddy_position
        assert abs(x - 700) < 25 and abs(y - 420) < 25
        assert overlay.is_guided
        overlay.release_guide()
        assert not overlay.is_guided
        assert overlay._mode == "returning"
    finally:
        overlay.close()


def test_explicit_point_wins_over_guiding(qt_app):
    from clicky.overlay import BuddyOverlay

    overlay = BuddyOverlay()
    try:
        overlay.guide_to(100, 100)
        overlay.fly_to(900, 500, "button")
        overlay.guide_to(120, 110)  # the pen keeps moving, but the point flight continues
        assert overlay._mode in ("flying", "holding")
    finally:
        overlay.close()
