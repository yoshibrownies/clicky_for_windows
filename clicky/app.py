"""Entry point: wires settings, hotkey, controller, overlay, tray and playback together."""

from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from dotenv import load_dotenv
from PySide6.QtCore import QLockFile, QObject, QStandardPaths, Signal
from PySide6.QtWidgets import QApplication, QMessageBox

from clicky.async_runner import AsyncRunner
from clicky.audio_capture import MicrophoneStreamer
from clicky.config import AVAILABLE_MODELS, ConfigError, load_settings
from clicky.controller import CompanionController, PointTarget
from clicky.hotkey import HotkeyParseError, HotkeyPoller, PushToTalkEvent, parse_hotkey
from clicky.overlay import BuddyOverlay
from clicky.playback import SpeechPlayer
from clicky.screens import capture_all_screens
from clicky.services import WorkerServices
from clicky.tray import ClickyTray

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


def show_fatal_error(message: str) -> None:
    logger.error(message)
    QMessageBox.critical(None, "Clicky", message)


def main() -> int:
    log_path = configure_logging()
    load_dotenv(PROJECT_ROOT / ".env")
    load_dotenv()  # also a .env in the current folder, if any

    application = QApplication(sys.argv)
    application.setApplicationName("Clicky")
    application.setQuitOnLastWindowClosed(False)

    lock_file = QLockFile(
        str(Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.TempLocation)) / "clicky.lock")
    )
    if not lock_file.tryLock(100):
        show_fatal_error("Clicky is already running. Look for the blue triangle in the system tray.")
        return 1

    try:
        settings = load_settings(os.environ)
        parsed_hotkey = parse_hotkey(settings.hotkey)
    except (ConfigError, HotkeyParseError) as settings_error:
        show_fatal_error(str(settings_error))
        return 1
    if settings.model not in AVAILABLE_MODELS:
        logger.warning("CLICKY_MODEL %s isn't in the tray menu list; using it anyway", settings.model)

    runner = AsyncRunner()
    services = WorkerServices(settings)
    player = SpeechPlayer()
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
    )

    controller.state_changed.connect(overlay.set_state)
    controller.state_changed.connect(tray.set_state)
    controller.audio_level_changed.connect(overlay.set_audio_level)
    controller.transcript_changed.connect(overlay.show_transcript)
    controller.reply_text_changed.connect(overlay.show_reply)
    controller.notice.connect(overlay.show_notice)

    def point_at(target: PointTarget) -> None:
        overlay.fly_to(target.global_x, target.global_y, target.label)

    controller.point_requested.connect(point_at)
    player.finished.connect(controller.handle_playback_finished)

    tray.model_selected.connect(controller.set_model)
    tray.always_visible_toggled.connect(overlay.set_always_visible)
    tray.forget_requested.connect(controller.history.clear)
    tray.forget_requested.connect(lambda: overlay.show_notice("okay, fresh start."))

    hotkey_bridge = HotkeyBridge()
    hotkey_bridge.pressed.connect(controller.handle_push_to_talk_pressed)
    hotkey_bridge.released.connect(controller.handle_push_to_talk_released)
    hotkey_bridge.cancelled.connect(controller.handle_push_to_talk_cancelled)
    hotkey_poller = HotkeyPoller(parsed_hotkey, hotkey_bridge.forward)

    def shut_down() -> None:
        logger.info("Shutting down")
        hotkey_poller.stop()
        controller.shutdown()
        try:
            runner.run(services.aclose(), timeout=3)
        except Exception:
            logger.debug("Error closing HTTP client", exc_info=True)
        runner.stop()
        tray.hide()
        lock_file.unlock()

    tray.quit_requested.connect(application.quit)
    application.aboutToQuit.connect(shut_down)

    tray.show()
    hotkey_poller.start()
    overlay.show_notice(f"hi! hold {tray.pretty_hotkey} and talk to me.")
    tray.show_message("Clicky is running", f"Hold {tray.pretty_hotkey} and talk. Logs: {log_path}")
    logger.info(
        "Clicky started (worker %s, model %s, hotkey %s)", settings.worker_base_url, settings.model, settings.hotkey
    )
    return application.exec()
