import asyncio
import time

import pytest
from PySide6.QtCore import QCoreApplication

from clicky.async_runner import AsyncRunner
from clicky.claude_client import ClaudeStreamError, StreamFinished, TextDelta
from clicky.controller import CompanionController, CompanionState, resolve_point_target, visible_reply_text
from clicky.prompts import REFUSAL_SPOKEN_REPLY
from clicky.screens import ScreenCapture, ScreenGeometry


@pytest.fixture
def runner():
    async_runner = AsyncRunner()
    yield async_runner
    async_runner.stop()


def wait_until(condition, timeout: float = 3.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met in time")


def make_capture(geometry: ScreenGeometry, is_cursor: bool) -> ScreenCapture:
    return ScreenCapture(b"\xff\xd8jpeg", "label", 1600, 900, geometry, is_cursor)


PRIMARY = make_capture(ScreenGeometry(0, 0, 2560, 1440), True)
SECONDARY = make_capture(ScreenGeometry(2560, 0, 1920, 1080), False)


class FakeSession:
    def __init__(self, transcript: str) -> None:
        self.transcript = transcript
        self.audio: list[bytes] = []
        self.cancelled = False

    async def send_audio(self, pcm16_audio: bytes) -> None:
        self.audio.append(pcm16_audio)

    async def finish(self) -> str:
        return self.transcript

    async def cancel(self) -> None:
        self.cancelled = True


class FakeServices:
    def __init__(
        self,
        transcript="where's the save button",
        reply_chunks=("click save. ", "[POINT:800,450:save]"),
        stop_reason="end_turn",
        chat_error=None,
        tts_error=None,
        start_delay=0.0,
    ) -> None:
        self.session = FakeSession(transcript)
        self.reply_chunks = reply_chunks
        self.stop_reason = stop_reason
        self.chat_error = chat_error
        self.tts_error = tts_error
        self.start_delay = start_delay
        self.request_bodies: list[dict] = []
        self.spoken: list[str] = []

    async def start_transcription(self, on_transcript_update):
        await asyncio.sleep(self.start_delay)
        on_transcript_update("where's")
        return self.session

    async def stream_reply(self, request_body):
        self.request_bodies.append(request_body)
        if self.chat_error:
            raise self.chat_error
        for chunk in self.reply_chunks:
            yield TextDelta(chunk)
        yield StreamFinished(self.stop_reason)

    async def fetch_speech(self, text):
        self.spoken.append(text)
        if self.tts_error:
            raise self.tts_error
        return b"mp3"


class FakeMicrophone:
    def __init__(self, on_audio) -> None:
        self.on_audio = on_audio
        self.running = False

    def start(self) -> None:
        self.running = True
        self.on_audio(b"\x10\x00" * 800)

    def stop(self) -> None:
        self.running = False


class FakePlayer:
    def __init__(self) -> None:
        self.played: list[bytes] = []
        self.stop_calls = 0

    def play(self, mp3_audio: bytes) -> None:
        self.played.append(mp3_audio)

    def stop(self) -> None:
        self.stop_calls += 1


def make_controller(runner, services, captures=(PRIMARY, SECONDARY)):
    microphones: list[FakeMicrophone] = []

    def microphone_factory(on_audio):
        microphones.append(FakeMicrophone(on_audio))
        return microphones[-1]

    player = FakePlayer()
    controller = CompanionController(
        runner=runner,
        services=services,
        microphone_factory=microphone_factory,
        capture_screens=lambda: list(captures),
        player=player,
        model="claude-opus-5-5",
        effort="low",
    )
    recorded = {"states": [], "points": [], "notices": [], "replies": [], "transcripts": []}
    controller.state_changed.connect(recorded["states"].append)
    controller.point_requested.connect(recorded["points"].append)
    controller.notice.connect(recorded["notices"].append)
    controller.reply_text_changed.connect(recorded["replies"].append)
    controller.transcript_changed.connect(recorded["transcripts"].append)
    return controller, player, microphones, recorded


def test_happy_path(qt_app, runner):
    services = FakeServices()
    controller, player, microphones, recorded = make_controller(runner, services)

    controller.handle_push_to_talk_pressed()
    assert controller.state is CompanionState.LISTENING
    assert microphones[0].running
    controller.handle_push_to_talk_released()
    assert not microphones[0].running

    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert player.played == [b"mp3"]
    assert services.spoken == ["click save."]
    assert services.session.audio == [b"\x10\x00" * 800]  # audio captured before the socket opened was kept
    point = recorded["points"][0]
    assert (point.global_x, point.global_y, point.label) == (1280, 720, "save")
    assert "click save." in recorded["replies"]
    assert "where's the save button" in recorded["transcripts"]

    body = services.request_bodies[0]
    assert body["model"] == "claude-opus-5-5"
    image_blocks = [block for block in body["messages"][-1]["content"] if block["type"] == "image"]
    assert len(image_blocks) == 2

    controller.handle_playback_finished()
    assert controller.state is CompanionState.IDLE
    assert recorded["states"] == ["listening", "processing", "responding", "idle"]
    assert len(controller.history) == 1


def test_second_turn_includes_history_and_model_switch(qt_app, runner):
    services = FakeServices()
    controller, player, _, _ = make_controller(runner, services)
    for _ in range(2):
        controller.handle_push_to_talk_pressed()
        controller.handle_push_to_talk_released()
        wait_until(lambda: controller.state is CompanionState.RESPONDING)
        controller.handle_playback_finished()
        controller.set_model("claude-sonnet-5-5")
    second_body = services.request_bodies[1]
    assert second_body["model"] == "claude-sonnet-5-5"
    assert second_body["messages"][0] == {"role": "user", "content": "where's the save button"}
    assert second_body["messages"][1]["role"] == "assistant"


def test_empty_transcript_goes_idle_with_notice(qt_app, runner):
    services = FakeServices(transcript="   ")
    controller, player, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: recorded["notices"])
    assert controller.state is CompanionState.IDLE
    assert services.request_bodies == []
    assert player.played == []


def test_claude_error_goes_idle_with_message(qt_app, runner):
    services = FakeServices(chat_error=ClaudeStreamError("Claude request failed (401): invalid x-api-key"))
    controller, player, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: recorded["notices"])
    assert controller.state is CompanionState.IDLE
    assert "401" in recorded["notices"][0]
    assert len(controller.history) == 0


def test_tts_failure_still_points_and_goes_idle(qt_app, runner):
    services = FakeServices(tts_error=RuntimeError("Text-to-speech failed (401)"))
    controller, player, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: recorded["notices"])
    assert controller.state is CompanionState.IDLE
    assert recorded["points"]
    assert player.played == []


def test_refusal_speaks_apology_and_skips_history(qt_app, runner):
    services = FakeServices(reply_chunks=(), stop_reason="refusal")
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert services.spoken == [REFUSAL_SPOKEN_REPLY]
    assert len(controller.history) == 0


def test_cancel_while_listening_stops_everything(qt_app, runner):
    services = FakeServices()
    controller, player, microphones, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    wait_until(lambda: services.session.audio)
    controller.handle_push_to_talk_cancelled()
    assert controller.state is CompanionState.IDLE
    assert not microphones[0].running
    wait_until(lambda: services.session.cancelled)
    controller.handle_push_to_talk_released()  # stray release after cancel is ignored
    assert controller.state is CompanionState.IDLE
    assert services.request_bodies == []


def test_pressing_while_responding_interrupts_playback(qt_app, runner):
    services = FakeServices()
    controller, player, microphones, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    stops_before = player.stop_calls
    controller.handle_push_to_talk_pressed()
    assert player.stop_calls == stops_before + 1
    assert controller.state is CompanionState.LISTENING
    assert len(microphones) == 2


def test_stale_results_are_ignored(qt_app, runner):
    services = FakeServices(start_delay=0.2)
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    controller.handle_push_to_talk_pressed()  # interrupts the first interaction
    controller.handle_push_to_talk_cancelled()
    time.sleep(0.5)
    QCoreApplication.processEvents()
    assert controller.state is CompanionState.IDLE
    assert player.played == []


def test_stale_nothing_heard_does_not_reset_a_newer_interaction(qt_app, runner):
    services = FakeServices(transcript="")
    controller, _, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    controller.handle_push_to_talk_pressed()  # new interaction starts before the old one reports back
    stale_generation = controller._generation - 2  # the first interaction (abort bumps once, press once)
    controller._nothing_heard.emit(stale_generation)
    QCoreApplication.processEvents()
    assert controller.state is CompanionState.LISTENING
    assert recorded["notices"] == []


def test_microphone_failure_reports_notice(qt_app, runner):
    services = FakeServices()

    def broken_microphone_factory(on_audio):
        raise RuntimeError("Couldn't open the microphone.")

    controller = CompanionController(
        runner=runner,
        services=services,
        microphone_factory=broken_microphone_factory,
        capture_screens=list,
        player=FakePlayer(),
        model="m",
        effort="low",
    )
    notices = []
    controller.notice.connect(notices.append)
    controller.handle_push_to_talk_pressed()
    assert controller.state is CompanionState.IDLE
    assert notices == ["Couldn't open the microphone."]


def test_resolve_point_target_uses_screen_number_and_falls_back():
    spoken, target = resolve_point_target("over there [POINT:0,0:terminal:screen2]", [PRIMARY, SECONDARY])
    assert spoken == "over there"
    assert (target.global_x, target.global_y) == (2560, 0)
    _, fallback_target = resolve_point_target("x [POINT:0,0:t:screen9]", [PRIMARY, SECONDARY])
    assert (fallback_target.global_x, fallback_target.global_y) == (0, 0)
    assert resolve_point_target("no point [POINT:none]", [PRIMARY]) == ("no point", None)
    assert resolve_point_target("x [POINT:5,5:y]", []) == ("x", None)


def test_visible_reply_text_hides_partial_tag():
    assert visible_reply_text("click save. [POI") == "click save."
    assert visible_reply_text("click save. [") == "click save."
    assert visible_reply_text("click save. [POINT:80") == "click save."
    assert visible_reply_text("an [array] of things") == "an [array] of things"


def test_openai_model_gets_an_openai_shaped_request(qt_app, runner):
    services = FakeServices()
    controller, _, _, _ = make_controller(runner, services)
    controller.set_model("gpt-6.1-terra")
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    body = services.request_bodies[0]
    assert body["model"] == "gpt-6.1-terra"
    assert body["reasoning_effort"] == "low"
    assert body["messages"][0]["role"] == "developer"
    assert "output_config" not in body
