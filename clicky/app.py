"""Entry point: wires settings, hotkey, controller, overlay, tray and playback together."""

from __future__ import annotations

import logging
import os
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path
from urllib.parse import urlparse

from dotenv import load_dotenv
from PySide6.QtCore import QLockFile, QObject, QPoint, QRect, QStandardPaths, Signal
from PySide6.QtGui import QCursor, QGuiApplication
from PySide6.QtWidgets import QApplication, QMessageBox

from clicky.annotations import AnnotationLayer
from clicky.async_runner import AsyncRunner
from clicky.audio_capture import MicrophoneStreamer
from clicky.config import AVAILABLE_MODELS, EFFORT_LEVELS, ConfigError, load_settings
from clicky.controller import CompanionController, PointTarget
from clicky.dns_fallback import install_dns_fallback
from clicky.followup_chips import FollowUpChips
from clicky.fonts import load_fonts
from clicky.hotkey import VK_ESCAPE, HotkeyParseError, HotkeyPoller, KeyTapWatcher, PushToTalkEvent, parse_hotkey
from clicky.kokoro_voice import KokoroSpeech, default_model_dir
from clicky.lesson_card import DEFAULT_LINGER_SECONDS, LessonCard
from clicky.overlay import BuddyOverlay
from clicky.playback import SpeechPlayer
from clicky.scene import parse_scene
from clicky.screens import capture_all_screens
from clicky.services import WorkerServices
from clicky.status_pill import StatusPill
from clicky.system_voice import SystemVoice, VoiceOutput
from clicky.tray import ClickyTray
from clicky.visual_director import VisualDirector

logger = logging.getLogger("clicky")
PROJECT_ROOT = Path(__file__).resolve().parent.parent


class HotkeyBridge(QObject):
    """Carries hotkey events from the polling thread to the GUI thread (Qt queues cross-thread signals)."""

    pressed = Signal()
    released = Signal()
    cancelled = Signal()

    def forward(self, event: PushToTalkEvent) -> None:
        if event is PushToTalkEvent.PRESSED:
            self.pressed.emit()
        elif event is PushToTalkEvent.RELEASED:
            self.released.emit()
        else:
            self.cancelled.emit()


def configure_logging() -> Path:
    log_directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "Clicky"
    log_directory.mkdir(parents=True, exist_ok=True)
    log_path = log_directory / "clicky.log"
    file_handler = RotatingFileHandler(log_path, maxBytes=1_000_000, backupCount=2, encoding="utf-8")
    handlers: list[logging.Handler] = [file_handler]
    if sys.stderr is not None:  # None under pythonw.exe
        handlers.append(logging.StreamHandler())
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s", handlers=handlers)
    # httpx logs every request URL at INFO; keep the log about Clicky.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    return log_path


def install_exception_logging() -> None:
    """Send uncaught exceptions (Qt slots, paint events, plain threads) to the log.

    PySide prints slot exceptions to sys.stderr, which is None under pythonw.exe, so without this a bug in,
    say, the overlay's paintEvent would vanish without a trace."""

    def log_uncaught_exception(exception_type, exception, traceback) -> None:
        if issubclass(exception_type, KeyboardInterrupt):
            sys.__excepthook__(exception_type, exception, traceback)
            return
        logger.critical("Uncaught exception", exc_info=(exception_type, exception, traceback))

    def log_uncaught_thread_exception(arguments: threading.ExceptHookArgs) -> None:
        thread_name = arguments.thread.name if arguments.thread is not None else "unknown"
        logger.critical(
            "Uncaught exception in thread %s",
            thread_name,
            exc_info=(arguments.exc_type, arguments.exc_value, arguments.exc_traceback),
        )

    sys.excepthook = log_uncaught_exception
    threading.excepthook = log_uncaught_thread_exception


def mask_worker_url(worker_url: str) -> str:
    """The Worker has no auth, so its URL can spend the owner's API credit: never write it to logs in full."""
    parsed_url = urlparse(worker_url)
    host = parsed_url.hostname or ""
    if host in ("localhost", "127.0.0.1", "::1"):
        return worker_url
    first_label = host.split(".", 1)[0]
    return f"{parsed_url.scheme}://{first_label[:4]}…(hidden)"


def build_clear_controls(director, annotation_layer, card, chips, overlay):
    """(clear_all, something_visible) for the Esc key and the tray's Clear screen item.

    Clearing removes every mark, the lesson card, the follow-up chips and the speech bubble at once. The tray's
    Clear screen leaves speech playing; Esc also stops it (see build_escape_handler).
    """

    def clear_all() -> None:
        director.cancel()
        annotation_layer.clear()
        card.forget_marks()
        card.clear()
        chips.hide_options()
        overlay.dismiss_bubble()
        overlay.release_guide()  # the pen is gone, so the buddy goes back to the mouse

    def something_visible() -> bool:
        return bool(annotation_layer.visible_windows() or card.isVisible() or chips.isVisible() or overlay.has_bubble)

    return clear_all, something_visible


def build_escape_handler(controller, clear_all, something_visible):
    """Esc stops Clicky talking (or an answer on its way) and clears whatever it has drawn."""

    def handle_escape() -> None:
        controller.stop_speaking()
        if something_visible():
            clear_all()

    return handle_escape


def chips_anchor(card) -> QRect:
    """Where follow-up chips go: under the lesson card, or where the card would sit when there isn't one."""
    if card.isVisible():
        return card.geometry()
    screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
    available = screen.availableGeometry() if screen else QRect(0, 0, 1280, 800)
    return QRect(available.right() - card.width() - 16, available.top() + 56, card.width(), 0)


class KeyTapBridge(QObject):
    """Carries Esc presses from the polling thread to the GUI thread."""

    tapped = Signal()


def show_fatal_error(message: str) -> None:
    logger.error(message)
    QMessageBox.critical(None, "Clicky", message)


def main() -> int:
    try:
        log_path = configure_logging()
    except OSError as logging_error:
        # Still tell the user something under pythonw, where there is no console.
        application = QApplication(sys.argv)
        QMessageBox.critical(None, "Clicky", f"Couldn't create the log file: {logging_error}")
        del application
        return 1
    install_exception_logging()
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv()  # also a .env in the current folder, if any

    application = QApplication(sys.argv)
    application.setApplicationName("Clicky")
    application.setQuitOnLastWindowClosed(False)
    load_fonts()  # Inter + Geist Mono, bundled in clicky/fonts

    lock_file = QLockFile(
        str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)) / "clicky.lock")
    )
    if not lock_file.tryLock(100):
        show_fatal_error("Clicky is already running. Look for the blue triangle in the system tray.")
        return 1

    try:
        settings = load_settings(os.environ)
        # Some networks (mobile carriers) refuse *.workers.dev in DNS: look the Worker up over HTTPS then.
        install_dns_fallback([urlparse(settings.worker_base_url).hostname or ""])
        parsed_hotkey = parse_hotkey(settings.hotkey)
    except (ConfigError, HotkeyParseError) as settings_error:
        show_fatal_error(str(settings_error))
        return 1
    if settings.model not in AVAILABLE_MODELS:
        logger.warning("CLICKY_MODEL %s isn't in the tray menu list; using it anyway", settings.model)

    runner = AsyncRunner()
    # Kokoro (local, free) or ElevenLabs per CLICKY_VOICE; Windows' own voice speaks when that voice can't.
    services = WorkerServices(settings, kokoro_speech=KokoroSpeech(default_model_dir(), settings.kokoro_voice))
    runner.submit(services.warm_up_voice())
    player = VoiceOutput(SpeechPlayer(), SystemVoice())
    overlay = BuddyOverlay()
    controller = CompanionController(
        runner=runner,
        services=services,
        microphone_factory=MicrophoneStreamer,
        capture_screens=capture_all_screens,
        player=player,
        model=settings.model,
        effort=settings.effort,
    )
    tray = ClickyTray(
        hotkey_text=settings.hotkey,
        models=AVAILABLE_MODELS,
        selected_model=settings.model,
        always_visible=overlay.always_visible,
        effort_levels=EFFORT_LEVELS,
        selected_effort=settings.effort,
        notepad_visible=True,
    )
    annotation_layer = AnnotationLayer()
    card = LessonCard()
    chips = FollowUpChips()
    pill = StatusPill()

    def play_animation(scene_text: str) -> None:
        scene = parse_scene(scene_text)
        if scene is None:
            logger.info("Ignored an animation scene that didn't parse")
            return
        card.play_animation(scene)

    def add_card_text(kind: str, text: str) -> None:
        {
            "title": card.set_title,
            "heading": card.add_heading,
            "formula": card.add_formula,
            "highlight": card.highlight,
        }[kind](text)

    def add_mark(event) -> None:
        annotation_layer.add_mark(event)
        if event.box is not None:
            # Clicky can't see its card, so it may mark something underneath: the card moves out of the way.
            left, top, right, bottom = event.box
            card.avoid(QRect(QPoint(left, top), QPoint(right, bottom)).normalized())
        overlay.raise_()

    def point_at_event(event) -> None:
        overlay.fly_to(event.point[0], event.point[1], event.label)

    def clear_visuals() -> None:
        annotation_layer.clear()
        card.forget_marks()
        card.clear()
        card.start_reply()
        chips.hide_options()

    def finish_visuals() -> None:
        annotation_layer.finish()
        card.finish()

    def show_followups(options: list[str]) -> None:
        # With a card, the chips go when it fades. Without one they get the same linger on their own.
        hide_after = None if card.isVisible() else DEFAULT_LINGER_SECONDS
        chips.show_options(options, below=chips_anchor(card), hide_after=hide_after)

    visual_director = VisualDirector(
        annotate=add_mark,
        note=card.add_note,
        diagram=card.set_diagram,
        point=point_at_event,
        clear=clear_visuals,
        finish=finish_visuals,
        animate=play_animation,
        card_text=add_card_text,
        followups=show_followups,
    )

    controller.state_changed.connect(overlay.set_state)
    controller.state_changed.connect(tray.set_state)
    controller.state_changed.connect(pill.set_state)
    controller.audio_level_changed.connect(overlay.set_audio_level)
    controller.audio_level_changed.connect(pill.set_audio_level)
    controller.transcript_changed.connect(overlay.show_transcript)
    controller.notice.connect(overlay.show_notice)

    def point_at(target: PointTarget) -> None:
        overlay.fly_to(target.global_x, target.global_y, target.label)

    controller.point_requested.connect(point_at)
    player.finished.connect(controller.handle_playback_finished)
    player.failed.connect(controller.handle_voice_failed)
    player.progress.connect(controller.handle_playback_progress)  # where you'd got to, if you cut it off

    # Underlines, circles and the lesson card, timed to the speech.
    controller.visuals_ready.connect(visual_director.start)
    controller.interrupted.connect(visual_director.cancel)
    controller.state_changed.connect(visual_director.on_state)
    player.progress.connect(visual_director.on_progress)
    player.finished.connect(visual_director.on_playback_finished)

    # The buddy follows the card's pen while Clicky answers, then goes back to the mouse.
    def follow_pen(point) -> None:
        if controller.state.value == "responding":
            overlay.guide_to(point.x(), point.y())

    def on_state_for_pen_and_chips(state: str) -> None:
        if state in ("idle", "listening"):
            overlay.release_guide()
        if state == "listening":
            chips.hide_options()

    card.writing_point.connect(follow_pen)
    card.faded.connect(chips.hide_options)

    def chips_follow_card() -> None:
        if chips.isVisible() and card.isVisible():
            chips.show_options(chips.options(), below=card.geometry())

    card.moved.connect(chips_follow_card)
    card.closed.connect(overlay.release_guide)  # no card, no pen to follow
    annotation_layer.emptied.connect(card.forget_marks)  # marks gone: the card may use its usual spot again
    # Every Clicky window is always-on-top, and Windows stacks the newest one highest: lift the buddy back above
    # the card, the chips and fresh marks so it is never drawn behind them.
    card.appeared.connect(overlay.raise_)
    chips.appeared.connect(overlay.raise_)
    pill.appeared.connect(overlay.raise_)
    controller.state_changed.connect(on_state_for_pen_and_chips)
    chips.chosen.connect(controller.ask_typed)

    tray.model_selected.connect(controller.set_model)
    tray.effort_selected.connect(controller.set_effort)
    tray.notepad_toggled.connect(card.set_enabled)
    tray.notepad_toggled.connect(lambda enabled: None if enabled else overlay.release_guide())
    tray.always_visible_toggled.connect(overlay.set_always_visible)
    clear_all, something_visible = build_clear_controls(visual_director, annotation_layer, card, chips, overlay)
    tray.clear_requested.connect(clear_all)
    escape_bridge = KeyTapBridge()

    escape_bridge.tapped.connect(build_escape_handler(controller, clear_all, something_visible))
    escape_watcher = KeyTapWatcher(VK_ESCAPE, escape_bridge.tapped.emit)
    tray.forget_requested.connect(controller.forget)
    tray.forget_requested.connect(lambda: overlay.show_notice("okay, fresh start."))

    hotkey_bridge = HotkeyBridge()
    hotkey_bridge.pressed.connect(controller.handle_push_to_talk_pressed)
    hotkey_bridge.released.connect(controller.handle_push_to_talk_released)
    hotkey_bridge.cancelled.connect(controller.handle_push_to_talk_cancelled)
    hotkey_poller = HotkeyPoller(parsed_hotkey, hotkey_bridge.forward)

    def shut_down() -> None:
        logger.info("Shutting down")
        hotkey_poller.stop()
        escape_watcher.stop()
        controller.shutdown()
        try:
            runner.run(services.aclose(), timeout=3)
        except Exception:
            logger.debug("Error closing HTTP client", exc_info=True)
        runner.stop()
        annotation_layer.close_all()
        card.close()
        chips.close()
        pill.close()
        tray.hide()
        lock_file.unlock()

    tray.quit_requested.connect(application.quit)
    application.aboutToQuit.connect(shut_down)

    tray.show()
    hotkey_poller.start()
    escape_watcher.start()
    overlay.show_notice(f"hi! hold {tray.pretty_hotkey} and talk to me.")
    tray.show_message("Clicky is running", f"Hold {tray.pretty_hotkey} and talk. Logs: {log_path}")
    logger.info(
        "Clicky started (worker %s, model %s, hotkey %s)",
        mask_worker_url(settings.worker_base_url),
        settings.model,
        settings.hotkey,
    )
    return application.exec()
