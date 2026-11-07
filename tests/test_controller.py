import asyncio
import time

import pytest
from PySide6.QtCore import QCoreApplication

from clicky.async_runner import AsyncRunner
from clicky.claude_client import ClaudeStreamError, StreamFinished, TextDelta
from clicky.controller import CompanionController, CompanionState, resolve_point_target, visible_reply_text
from clicky.prompts import CUT_OFF_MARKER, REFUSAL_SPOKEN_REPLY
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


def test_set_effort_changes_the_next_request(qt_app, runner):
    services = FakeServices()
    controller, _, _, _ = make_controller(runner, services)
    controller.set_effort("high")
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert services.request_bodies[0]["output_config"] == {"effort": "high"}


def run_reply(runner, reply_chunks, stop_reason="end_turn"):
    services = FakeServices(reply_chunks=reply_chunks, stop_reason=stop_reason)
    controller, player, _, recorded = make_controller(runner, services)
    plans = []
    controller.visuals_ready.connect(plans.append)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    return services, recorded, plans


def test_visual_tags_become_screen_events_and_never_reach_the_voice(qt_app, runner):
    services, recorded, plans = run_reply(
        runner,
        (
            "look at [UNDERLINE:0,0,1600,900] this line ",
            "[NOTE:a key idea] and here [POINT:800,450:mid] ",
            "is the end [POINT:0,0:corner:screen2]",
        ),
    )
    assert services.spoken == ["look at this line and here is the end"]
    plan = plans[0]
    assert plan.spoken_text == "look at this line and here is the end"
    assert plan.has_audio
    kinds = [event.kind for event in plan.events]
    assert kinds == ["underline", "note", "point"]
    underline, note, point = plan.events
    assert underline.box == (0, 0, 2559, 1439)  # PRIMARY: 2560x1440 logical, image 1600x900
    assert note.text == "a key idea"
    assert point.point == (1280, 720) and point.label == "mid"
    assert [event.fraction for event in plan.events] == sorted(event.fraction for event in plan.events)
    # The tag at the very end keeps the classic behaviour: the buddy flies there straight away.
    legacy = recorded["points"][0]
    assert (legacy.global_x, legacy.global_y, legacy.label) == (2560, 0, "corner")


def test_marks_on_the_second_screen_are_mapped_there(qt_app, runner):
    _, _, plans = run_reply(runner, ("over there [CIRCLE:0,0,800,450:screen2] ok",))
    assert plans[0].events[0].box == (2560, 0, 2560 + 960, 540)


def test_refusal_has_no_visuals(qt_app, runner):
    services, _, plans = run_reply(runner, ("[NOTE:secret]",), stop_reason="refusal")
    assert plans[0].events == ()
    assert services.spoken == [REFUSAL_SPOKEN_REPLY]


def test_streaming_bubble_hides_every_kind_of_tag():
    assert visible_reply_text("this line [UNDERLINE:1,2,3,4] repeats [NOTE:loop] it") == "this line repeats it"
    assert visible_reply_text("see [CIRCLE:10,20") == "see"
    assert visible_reply_text("steps: [DIAGRAM:a -> b") == "steps:"
    assert visible_reply_text("an [array] of things") == "an [array] of things"


# ---------- review fixes ----------


class StopEmittingPlayer(FakePlayer):
    """Like the real SpeechPlayer: stop() reports playback finished straight away."""

    def __init__(self) -> None:
        super().__init__()
        self.on_finished = None

    def stop(self) -> None:
        super().stop()
        if self.on_finished is not None:
            self.on_finished()


def test_interrupting_mid_speech_never_flashes_the_old_replys_remaining_visuals(qt_app, runner):
    from clicky.visual_director import VisualDirector

    services = FakeServices(reply_chunks=("first point. ", "second point [NOTE:later note] ", "end [NOTE:last note]"))
    player = StopEmittingPlayer()
    controller = CompanionController(
        runner=runner,
        services=services,
        microphone_factory=FakeMicrophone,
        capture_screens=lambda: [PRIMARY],
        player=player,
        model="m",
        effort="low",
    )
    player.on_finished = controller.handle_playback_finished
    drawn = []
    director = VisualDirector(
        annotate=lambda event: drawn.append("mark"),
        note=lambda text: drawn.append(f"note:{text}"),
        diagram=lambda spec: drawn.append("diagram"),
        point=lambda event: drawn.append("point"),
        clear=lambda: drawn.append("clear"),
        finish=lambda: drawn.append("finish"),
    )
    controller.visuals_ready.connect(director.start)
    controller.state_changed.connect(director.on_state)
    controller.interrupted.connect(director.cancel)

    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    director.on_progress(0.1)  # early in the speech: the notes are not due yet
    drawn.clear()
    controller.handle_push_to_talk_pressed()  # interrupt
    assert not any(item.startswith("note:") for item in drawn), drawn
    assert "finish" not in drawn


def test_offscreen_marks_are_dropped_not_squashed_into_a_corner():
    from clicky.controller import build_visual_plan

    _, legacy_point, events = build_visual_plan(
        "a [CIRCLE:5000,5000,6000,6000] b [UNDERLINE:10,10,200,30] c [POINT:9000,20:x] d", [PRIMARY]
    )
    assert [event.kind for event in events] == ["underline"]
    assert legacy_point is None


def test_animate_events_pass_through_with_their_scene_text():
    from clicky.controller import build_visual_plan

    scene = '{"objects": [{"type": "point", "x": 1, "y": 1}]}'
    _, _, events = build_visual_plan(f'see [ANIMATE:s] this <scene name="s">{scene}</scene>', [PRIMARY])
    assert [(event.kind, event.text) for event in events] == [("animate", scene)]


def test_card_events_pass_through():
    from clicky.controller import build_visual_plan

    _, _, events = build_visual_plan("[TITLE:t] [HEADING:h] x [FORMULA:f] [FOLLOWUP:q]", [PRIMARY])
    assert [(event.kind, event.text) for event in events] == [
        ("title", "t"),
        ("heading", "h"),
        ("formula", "f"),
        ("followup", "q"),
    ]


class CountingServices(FakeServices):
    def __init__(self, **options) -> None:
        super().__init__(**options)
        self.transcription_starts = 0

    async def start_transcription(self, on_transcript_update):
        self.transcription_starts += 1
        return await super().start_transcription(on_transcript_update)


def test_typed_question_runs_the_answer_without_listening(qt_app, runner):
    services = CountingServices()
    controller, player, microphones, recorded = make_controller(runner, services)
    controller.ask_typed("Explain terminal speed")
    assert controller.state is CompanionState.PROCESSING
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert services.transcription_starts == 0
    assert microphones == []
    body = services.request_bodies[0]
    assert body["messages"][-1]["content"][-1]["text"] == "Explain terminal speed"
    assert len([block for block in body["messages"][-1]["content"] if block["type"] == "image"]) == 2
    assert "Explain terminal speed" in recorded["transcripts"]
    assert player.played == [b"mp3"]


def test_typed_question_interrupts_a_reply_in_progress(qt_app, runner):
    services = CountingServices()
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    stops = player.stop_calls
    controller.ask_typed("Try a calculation")
    assert player.stop_calls == stops + 1
    wait_until(lambda: len(services.request_bodies) == 2 and controller.state is CompanionState.RESPONDING)
    assert services.request_bodies[1]["messages"][-1]["content"][-1]["text"] == "Try a calculation"


def test_blank_typed_question_is_ignored(qt_app, runner):
    services = CountingServices()
    controller, _, _, _ = make_controller(runner, services)
    controller.ask_typed("   ")
    assert controller.state is CompanionState.IDLE


def test_tts_failure_shows_the_answer_as_text(qt_app, runner):
    services = FakeServices(tts_error=RuntimeError("Text-to-speech failed (401)"))
    controller, player, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: recorded["notices"])
    notice = recorded["notices"][-1]
    assert "couldn't play the voice" in notice
    assert len(notice) > len("couldn't play the voice: Text-to-speech failed (401)") + 5  # the answer is in it


def test_streaming_does_not_reparse_the_whole_reply_on_every_chunk(qt_app, runner, monkeypatch):
    import clicky.controller as controller_module

    calls = []
    monkeypatch.setattr(controller_module, "visible_reply_text", lambda text: calls.append(text) or text)
    services = FakeServices(reply_chunks=tuple(f"word{n} " for n in range(50)))
    controller, player, _, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: player.played)
    assert len(calls) == 0  # nothing shows the partial reply any more


def test_history_keeps_the_words_not_the_scene_json(qt_app, runner):
    scene = '<scene name="drop">{"duration": 3, "world": {"x": [0, 1], "y": [0, 1]}, "objects": []}</scene>'
    services = FakeServices(reply_chunks=("watch it fall. [ANIMATE:drop] [NOTE:gravity] ", scene))
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: player.played)
    controller.handle_playback_finished()  # remembered once heard
    remembered = controller.history.as_messages()[-1]["content"]
    assert "watch it fall." in remembered
    assert "<scene" not in remembered and '"objects"' not in remembered
    assert "[ANIMATE:drop]" in remembered  # it still knows it showed an animation


def test_an_answer_interrupted_before_it_was_spoken_is_not_remembered(qt_app, runner):
    class SlowSpeech(FakeServices):
        async def fetch_speech(self, text):
            self.spoken.append(text)
            await asyncio.sleep(5)
            return b"mp3"

    services = SlowSpeech()
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: services.spoken)  # the reply text is in; the voice is still loading
    controller.handle_push_to_talk_pressed()  # talk over it
    controller.handle_push_to_talk_cancelled()
    wait_until(lambda: runner.in_flight_count == 0)
    assert len(controller.history) == 0


# ---------- Esc stops Clicky talking ----------


class SlowSpeechServices(FakeServices):
    async def fetch_speech(self, text):
        await asyncio.sleep(0.3)
        return await super().fetch_speech(text)


def test_stop_speaking_cuts_off_the_voice(qt_app, runner):
    services = FakeServices()
    controller, player, _, _ = make_controller(runner, services)
    interrupted = []
    controller.interrupted.connect(lambda: interrupted.append(True))
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    stops_before, interruptions_before = player.stop_calls, len(interrupted)
    assert controller.stop_speaking() is True
    assert player.stop_calls == stops_before + 1
    assert controller.state is CompanionState.IDLE
    assert len(interrupted) == interruptions_before + 1  # the lesson visuals stop with the voice


def test_stop_speaking_while_thinking_drops_the_coming_answer(qt_app, runner):
    services = SlowSpeechServices()
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.PROCESSING)
    assert controller.stop_speaking() is True
    assert controller.state is CompanionState.IDLE
    time.sleep(0.5)
    QCoreApplication.processEvents()
    assert player.played == []
    assert controller.state is CompanionState.IDLE


def test_stop_speaking_leaves_listening_and_idle_alone(qt_app, runner):
    services = FakeServices()
    controller, player, microphones, _ = make_controller(runner, services)
    assert controller.stop_speaking() is False
    controller.handle_push_to_talk_pressed()
    assert controller.stop_speaking() is False
    assert controller.state is CompanionState.LISTENING
    assert microphones[0].running


# ---------- remembering only what was heard ----------

LONG_REPLY = (
    "the hippocampus links a memory together. [NOTE:hippocampus = index] ",
    "later it moves into the cortex. [NOTE:cortex = long term] [FOLLOWUP:What is LTP?]",
)


def start_long_reply(runner):
    services = FakeServices(reply_chunks=LONG_REPLY)
    controller, player, microphones, recorded = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    return services, controller, player


def test_nothing_is_remembered_until_the_answer_has_been_heard(qt_app, runner):
    _, controller, _ = start_long_reply(runner)
    assert len(controller.history) == 0
    controller.handle_playback_progress(0.5)
    controller.handle_playback_finished()
    remembered = controller.history.as_messages()[-1]["content"]
    assert "cortex = long term" in remembered
    assert CUT_OFF_MARKER not in remembered


def test_cutting_in_remembers_only_what_was_heard(qt_app, runner):
    services, controller, _ = start_long_reply(runner)
    controller.handle_playback_progress(0.6)
    controller.handle_push_to_talk_pressed()  # "wait, what's an index?"
    messages = controller.history.as_messages()
    assert messages[0] == {"role": "user", "content": "where's the save button"}
    remembered = messages[1]["content"]
    assert remembered.startswith("the hippocampus links a memory together.")
    assert remembered.endswith(CUT_OFF_MARKER)
    assert "cortex" not in remembered and "FOLLOWUP" not in remembered
    controller.handle_push_to_talk_released()
    wait_until(lambda: len(services.request_bodies) == 2)
    assert services.request_bodies[1]["messages"][1]["content"] == remembered


def test_escape_remembers_only_what_was_heard(qt_app, runner):
    _, controller, _ = start_long_reply(runner)
    controller.handle_playback_progress(0.4)
    controller.stop_speaking()
    remembered = controller.history.as_messages()[-1]["content"]
    assert remembered.endswith(CUT_OFF_MARKER)
    assert "cortex" not in remembered
    assert len(controller.history) == 1


def test_cut_off_before_any_speech_was_heard_is_forgotten(qt_app, runner):
    _, controller, _ = start_long_reply(runner)
    controller.stop_speaking()
    assert len(controller.history) == 0


def test_a_cut_off_answer_is_not_saved_again_when_the_player_reports_finished(qt_app, runner):
    _, controller, player = start_long_reply(runner)
    controller.handle_playback_progress(0.4)
    controller.stop_speaking()
    controller.handle_playback_finished()  # the real player emits finished on stop()
    assert len(controller.history) == 1


def test_forget_during_speech_also_forgets_the_answer_being_spoken(qt_app, runner):
    _, controller, _ = start_long_reply(runner)
    controller.history.add("older question", "older answer")
    controller.handle_playback_progress(0.6)
    controller.forget()  # tray "Forget" while Clicky is mid-answer
    controller.handle_playback_finished()
    assert len(controller.history) == 0


# ---------- the voice starts while the drawings are still being written ----------


class SceneStreamingServices(FakeServices):
    """Speech comes first, then scene blocks; the stream waits (up to 2 s) for the voice to be requested."""

    def __init__(self, **kwargs) -> None:
        scene = (
            '{"duration": 3, "world": {"x": [0, 1], "y": [0, 1]}, "objects": [{"type": "circle", "x": 0.5, "y": 0.5}]}'
        )
        super().__init__(
            reply_chunks=("watch this. [ANIMATE:a] it grows. ", '<scene name="a">', scene, "</scene>"), **kwargs
        )
        self.order: list[str] = []

    async def stream_reply(self, request_body):
        self.request_bodies.append(request_body)
        for chunk in self.reply_chunks:
            yield TextDelta(chunk)
            if chunk.startswith("<scene"):
                for _ in range(200):
                    if self.spoken:
                        break
                    await asyncio.sleep(0.01)
        self.order.append("stream finished")
        yield StreamFinished(self.stop_reason)

    async def fetch_speech(self, text):
        self.order.append("speech requested")
        return await super().fetch_speech(text)


def test_the_voice_is_fetched_while_scene_blocks_are_still_streaming(qt_app, runner):
    services = SceneStreamingServices()
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert services.order == ["speech requested", "stream finished"]
    assert services.spoken == ["watch this. it grows."]  # fetched once, with the final words
    assert player.played == [b"mp3"]


def test_words_after_a_scene_block_get_the_voice_refetched(qt_app, runner):
    scene = '<scene name="a">{"duration": 3, "objects": [{"type": "circle", "x": 1, "y": 1}]}</scene>'
    services = FakeServices(reply_chunks=("first part. [ANIMATE:a] ", scene, " and a late sentence."))
    controller, player, _, _ = make_controller(runner, services)
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()
    wait_until(lambda: controller.state is CompanionState.RESPONDING)
    assert services.spoken[-1] == "first part. and a late sentence."
    assert player.played == [b"mp3"]


# ---------- Windows voice fallback ----------


class SpeakingPlayer(FakePlayer):
    """A player that can also speak text with the Windows voice (like VoiceOutput)."""

    def __init__(self) -> None:
        super().__init__()
        self.spoken_texts: list[str] = []

    def speak_text(self, text: str) -> None:
        self.spoken_texts.append(text)


class CountingVoiceServices(FakeServices):
    def __init__(self, error_message: str, **kwargs) -> None:
        super().__init__(**kwargs)
        self.error_message = error_message

    async def fetch_speech(self, text):
        self.spoken.append(text)
        raise RuntimeError(self.error_message)


QUOTA_ERROR = (
    'Text-to-speech failed (401): {"detail":{"code":"quota_exceeded","message":"This request exceeds your quota"}}'
)


def controller_with_speaking_player(runner, services):
    player = SpeakingPlayer()
    controller = CompanionController(
        runner=runner,
        services=services,
        microphone_factory=FakeMicrophone,
        capture_screens=lambda: [PRIMARY],
        player=player,
        model="m",
        effort="low",
    )
    notices: list[str] = []
    controller.notice.connect(notices.append)
    return controller, player, notices


def ask(controller):
    controller.handle_push_to_talk_pressed()
    controller.handle_push_to_talk_released()


def test_a_failed_voice_falls_back_to_speaking_the_text(qt_app, runner):
    services = CountingVoiceServices(QUOTA_ERROR)
    controller, player, notices = controller_with_speaking_player(runner, services)
    ask(controller)
    wait_until(lambda: player.spoken_texts)
    assert player.spoken_texts == ["click save."]
    assert controller.state is CompanionState.RESPONDING and notices == []
    controller.handle_playback_finished()
    assert controller.history.as_messages()[-1]["content"].startswith("click save.")


def test_after_a_quota_error_elevenlabs_is_not_asked_again(qt_app, runner):
    services = CountingVoiceServices(QUOTA_ERROR)
    controller, player, _ = controller_with_speaking_player(runner, services)
    ask(controller)
    wait_until(lambda: len(player.spoken_texts) == 1)
    controller.handle_playback_finished()
    ask(controller)
    wait_until(lambda: len(player.spoken_texts) == 2)
    assert len(services.spoken) == 1  # the second answer went straight to the Windows voice


def test_other_voice_errors_still_retry_elevenlabs(qt_app, runner):
    services = CountingVoiceServices("Couldn't reach the Clicky Worker: timed out")
    controller, player, _ = controller_with_speaking_player(runner, services)
    for expected in (1, 2):
        ask(controller)
        wait_until(lambda expected=expected: len(player.spoken_texts) == expected)
        controller.handle_playback_finished()
    assert len(services.spoken) == 2


def test_if_the_windows_voice_fails_too_the_answer_is_shown(qt_app, runner):
    services = CountingVoiceServices(QUOTA_ERROR)
    controller, player, notices = controller_with_speaking_player(runner, services)
    ask(controller)
    wait_until(lambda: player.spoken_texts)
    controller.handle_voice_failed("no windows voice is available")
    assert controller.state is CompanionState.IDLE
    assert notices and "click save." in notices[-1]
