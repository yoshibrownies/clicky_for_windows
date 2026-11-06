"""The companion's state machine: hotkey → listen → look → think → speak → point.

Threading rules:
- Public methods (handle_push_to_talk_*, handle_playback_finished, set_model) run on the Qt GUI thread.
- One interaction is one coroutine on the AsyncRunner loop. It reports back only through Qt signals,
  which Qt queues onto the GUI thread because this QObject lives there.
- Every interaction has a generation number; results from an interaction that has since been cancelled or
  replaced are dropped.
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
from collections.abc import AsyncIterator, Callable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from PySide6.QtCore import QObject, Signal, Slot

from clicky.async_runner import AsyncRunner
from clicky.audio_capture import compute_audio_level
from clicky.claude_client import ChatStreamEvent, StreamFinished, TextDelta, build_chat_request_body
from clicky.config import is_openai_model
from clicky.conversation import ConversationHistory
from clicky.openai_client import build_openai_chat_request_body
from clicky.pointing import parse_point_tag
from clicky.prompts import COMPANION_SYSTEM_PROMPT, REFUSAL_SPOKEN_REPLY
from clicky.screens import ScreenCapture, map_image_point_to_screen
from clicky.visuals import parse_visual_reply, visible_text

logger = logging.getLogger(__name__)


class CompanionState(StrEnum):
    IDLE = "idle"
    LISTENING = "listening"
    PROCESSING = "processing"
    RESPONDING = "responding"


class TranscriptionSession(Protocol):
    async def send_audio(self, pcm16_audio: bytes) -> None: ...
    async def finish(self) -> str: ...
    async def cancel(self) -> None: ...


class CompanionServices(Protocol):
    async def start_transcription(self, on_transcript_update: Callable[[str], None]) -> TranscriptionSession: ...
    def stream_reply(self, request_body: dict) -> AsyncIterator[ChatStreamEvent]: ...
    async def fetch_speech(self, text: str) -> bytes: ...


class Microphone(Protocol):
    def start(self) -> None: ...
    def stop(self) -> None: ...


class SpeechPlayer(Protocol):
    def play(self, mp3_audio: bytes) -> None: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class PointTarget:
    global_x: int
    global_y: int
    label: str


@dataclass(frozen=True)
class ScreenVisualEvent:
    """A visual tag mapped onto the desktop (Qt global logical coordinates), ready to draw."""

    kind: str  # "point" | "underline" | "circle" | "note" | "diagram"
    fraction: float
    box: tuple[int, int, int, int] | None = None
    point: tuple[int, int] | None = None
    label: str = ""
    text: str = ""


@dataclass(frozen=True)
class VisualPlan:
    spoken_text: str
    events: tuple[ScreenVisualEvent, ...]
    has_audio: bool


@dataclass(frozen=True)
class CompanionReply:
    generation: int
    spoken_text: str
    point_target: PointTarget | None
    speech_audio: bytes | None
    speech_error: str | None
    visual_events: tuple[ScreenVisualEvent, ...] = ()


@dataclass(frozen=True)
class _ReleaseMarker:
    """Put on the audio queue when the key is released; carries the screenshots taken at that moment."""

    screen_captures: tuple[ScreenCapture, ...]


NOTHING_HEARD_MESSAGE = "didn't catch that — hold the keys while you talk."


def resolve_point_target(reply_text: str, screen_captures: Sequence[ScreenCapture]) -> tuple[str, PointTarget | None]:
    """Strip the POINT tag from a reply and map its coordinate onto the right monitor."""
    pointing = parse_point_tag(reply_text)
    if pointing.coordinate is None or not screen_captures:
        return pointing.spoken_text, None
    capture_index = 0
    if pointing.screen_number is not None and 1 <= pointing.screen_number <= len(screen_captures):
        capture_index = pointing.screen_number - 1
    capture = screen_captures[capture_index]
    global_x, global_y = map_image_point_to_screen(
        pointing.coordinate, (capture.image_width, capture.image_height), capture.geometry
    )
    return pointing.spoken_text, PointTarget(global_x, global_y, pointing.label or "")


def _inside_image(event, capture: ScreenCapture) -> bool:
    width, height = capture.image_width, capture.image_height
    if event.point is not None:
        x, y = event.point
        return x <= width * 1.02 and y <= height * 1.02
    if event.box is not None:
        left, top, right, bottom = event.box
        return left < width and top < height and right <= width * 1.05 and bottom <= height * 1.05
    return True


# A POINT this close to the end is the classic "point while answering" tag: fly there straight away.
LEGACY_POINT_FRACTION = 0.9


def build_visual_plan(
    reply_text: str, screen_captures: Sequence[ScreenCapture]
) -> tuple[str, PointTarget | None, tuple[ScreenVisualEvent, ...]]:
    """Split a reply into spoken text, an immediate (end-of-reply) point, and timed screen events."""
    visual_reply = parse_visual_reply(reply_text)
    legacy_point: PointTarget | None = None
    screen_events: list[ScreenVisualEvent] = []

    def capture_for(screen_number: int | None) -> ScreenCapture | None:
        if not screen_captures:
            return None
        if screen_number is not None and 1 <= screen_number <= len(screen_captures):
            return screen_captures[screen_number - 1]
        return screen_captures[0]

    def to_screen(capture: ScreenCapture, image_point: tuple[int, int]) -> tuple[int, int]:
        return map_image_point_to_screen(image_point, (capture.image_width, capture.image_height), capture.geometry)

    for event in visual_reply.events:
        if event.kind in ("note", "diagram", "animate", "title", "heading", "formula", "followup", "highlight"):
            screen_events.append(ScreenVisualEvent(kind=event.kind, fraction=event.fraction, text=event.text))
            continue
        capture = capture_for(event.screen_number)
        if capture is None:
            continue  # nothing to map onto (screen capture failed)
        if not _inside_image(event, capture):
            continue  # the model pointed outside the screenshot; drawing it would land in a screen corner
        if event.kind == "point" and event.point is not None:
            global_x, global_y = to_screen(capture, event.point)
            if event.fraction >= LEGACY_POINT_FRACTION and legacy_point is None:
                legacy_point = PointTarget(global_x, global_y, event.label)
            else:
                screen_events.append(
                    ScreenVisualEvent(
                        kind="point", fraction=event.fraction, point=(global_x, global_y), label=event.label
                    )
                )
        elif event.box is not None:
            left, top = to_screen(capture, (event.box[0], event.box[1]))
            right, bottom = to_screen(capture, (event.box[2], event.box[3]))
            screen_events.append(
                ScreenVisualEvent(kind=event.kind, fraction=event.fraction, box=(left, top, right, bottom))
            )
    return visual_reply.spoken_text, legacy_point, tuple(screen_events)


def visible_reply_text(partial_reply: str) -> str:
    """What the speech bubble shows while streaming: the text without tags, including a half-written last one."""
    return visible_text(partial_reply)


class CompanionController(QObject):
    state_changed = Signal(str)
    audio_level_changed = Signal(float)
    transcript_changed = Signal(str)
    reply_text_changed = Signal(str)
    point_requested = Signal(object)  # PointTarget
    visuals_ready = Signal(object)  # VisualPlan: timed underlines, circles, notes, diagrams, points
    interrupted = Signal()  # the current reply was cut short: drop its pending visuals without showing them
    notice = Signal(str)  # short message shown in the bubble (errors, "didn't catch that")

    # Internal: emitted from the asyncio thread, delivered on the GUI thread.
    _reply_ready = Signal(object)
    _interaction_failed = Signal(int, str)
    _nothing_heard = Signal(int)
    _processing_started = Signal(int)
    _partial_reply = Signal(int, str)
    _partial_transcript = Signal(int, str)

    def __init__(
        self,
        *,
        runner: AsyncRunner,
        services: CompanionServices,
        microphone_factory: Callable[[Callable[[bytes], None]], Microphone],
        capture_screens: Callable[[], list[ScreenCapture]],
        player: SpeechPlayer,
        model: str,
        effort: str,
        history: ConversationHistory | None = None,
    ) -> None:
        super().__init__()
        self._runner = runner
        self._services = services
        self._microphone_factory = microphone_factory
        self._capture_screens = capture_screens
        self._player = player
        self.model = model
        self.effort = effort
        self.history = history or ConversationHistory()

        self.state = CompanionState.IDLE
        self._generation = 0
        self._microphone: Microphone | None = None
        self._audio_queue: asyncio.Queue | None = None
        self._interaction_future: concurrent.futures.Future | None = None

        self._reply_ready.connect(self._on_reply_ready)
        self._interaction_failed.connect(self._on_interaction_failed)
        self._nothing_heard.connect(self._on_nothing_heard)
        self._processing_started.connect(self._on_processing_started)
        self._partial_reply.connect(self._on_partial_reply)
        self._partial_transcript.connect(self._on_partial_transcript)

    # ----- GUI-thread entry points -----

    @Slot()
    def handle_push_to_talk_pressed(self) -> None:
        if self.state is CompanionState.LISTENING:
            return
        # Talking over Clicky interrupts it, like interrupting a person.
        self._abort_current_interaction()
        self._generation += 1
        generation = self._generation
        self._set_state(CompanionState.LISTENING)
        self.transcript_changed.emit("")
        self.reply_text_changed.emit("")

        audio_queue: asyncio.Queue = asyncio.Queue()
        self._audio_queue = audio_queue

        def on_microphone_audio(pcm16_audio: bytes) -> None:
            # Audio thread. Queue it on the loop; it is buffered until the websocket is open.
            self._runner.call_soon(audio_queue.put_nowait, pcm16_audio)
            self.audio_level_changed.emit(compute_audio_level(pcm16_audio))

        try:
            self._microphone = self._microphone_factory(on_microphone_audio)
            self._microphone.start()
        except Exception as microphone_error:
            logger.exception("Microphone failed to start")
            self._microphone = None
            self._audio_queue = None
            self._set_state(CompanionState.IDLE)
            self.notice.emit(str(microphone_error))
            return

        self._interaction_future = self._runner.submit(self._run_interaction(generation, audio_queue))

    @Slot()
    def handle_push_to_talk_released(self) -> None:
        if self.state is not CompanionState.LISTENING or self._audio_queue is None:
            return
        self._stop_microphone()
        # Screenshots are taken on the GUI thread at the moment the user stops talking.
        try:
            screen_captures = tuple(self._capture_screens())
        except Exception:
            logger.exception("Screen capture failed; continuing without screenshots")
            screen_captures = ()
        self._runner.call_soon(self._audio_queue.put_nowait, _ReleaseMarker(screen_captures))
        self._audio_queue = None
        self._set_state(CompanionState.PROCESSING)

    @Slot(str)
    def ask_typed(self, text: str) -> None:
        """Answer a question given as text (a follow-up chip): same pipeline, no microphone or transcription."""
        text = " ".join(text.split())
        if not text:
            return
        self._abort_current_interaction()
        self._generation += 1
        generation = self._generation
        self._set_state(CompanionState.PROCESSING)
        self.transcript_changed.emit(text)
        self.reply_text_changed.emit("")
        try:
            screen_captures = tuple(self._capture_screens())
        except Exception:
            logger.exception("Screen capture failed; continuing without screenshots")
            screen_captures = ()
        self._interaction_future = self._runner.submit(self._run_typed_interaction(generation, text, screen_captures))

    @Slot()
    def handle_push_to_talk_cancelled(self) -> None:
        if self.state is CompanionState.LISTENING:
            self._abort_current_interaction()
            self._set_state(CompanionState.IDLE)

    @Slot()
    def handle_playback_finished(self) -> None:
        if self.state is CompanionState.RESPONDING:
            self._set_state(CompanionState.IDLE)

    def set_model(self, model: str) -> None:
        self.model = model

    def set_effort(self, effort: str) -> None:
        self.effort = effort

    def shutdown(self) -> None:
        self._abort_current_interaction()

    # ----- the interaction coroutine (asyncio thread) -----

    async def _run_interaction(self, generation: int, audio_queue: asyncio.Queue) -> None:
        session: TranscriptionSession | None = None
        try:
            session = await self._services.start_transcription(
                lambda transcript: self._partial_transcript.emit(generation, transcript)
            )
            while True:
                queued_item = await audio_queue.get()
                if isinstance(queued_item, _ReleaseMarker):
                    screen_captures = queued_item.screen_captures
                    break
                await session.send_audio(queued_item)

            self._processing_started.emit(generation)
            transcript = (await session.finish()).strip()
            session = None
            if not transcript:
                self._nothing_heard.emit(generation)
                return
            self._partial_transcript.emit(generation, transcript)

            await self._respond(generation, transcript, screen_captures)
        except asyncio.CancelledError:
            raise
        except Exception as interaction_error:
            logger.exception("Interaction failed")
            self._interaction_failed.emit(generation, str(interaction_error))
        finally:
            if session is not None:
                await asyncio.shield(_cancel_quietly(session))

    async def _respond(self, generation: int, transcript: str, screen_captures: Sequence[ScreenCapture]) -> None:
        """Ask the model, speak and show the answer. Shared by spoken and typed (follow-up chip) questions."""
        build_request_body = build_openai_chat_request_body if is_openai_model(self.model) else build_chat_request_body
        request_body = build_request_body(
            model=self.model,
            effort=self.effort,
            system_prompt=COMPANION_SYSTEM_PROMPT,
            history_messages=self.history.as_messages(),
            screenshots=[(capture.jpeg_bytes, capture.label) for capture in screen_captures],
            user_transcript=transcript,
        )
        reply_text = ""
        stop_reason: str | None = None
        async for stream_event in self._services.stream_reply(request_body):
            if isinstance(stream_event, TextDelta):
                reply_text += stream_event.text
                self._partial_reply.emit(generation, visible_reply_text(reply_text))
            elif isinstance(stream_event, StreamFinished):
                stop_reason = stream_event.stop_reason

        visual_events: tuple[ScreenVisualEvent, ...] = ()
        if stop_reason == "refusal":
            spoken_text, point_target = REFUSAL_SPOKEN_REPLY, None
        else:
            spoken_text, point_target, visual_events = build_visual_plan(reply_text, screen_captures)
            self.history.add(transcript, reply_text)
        if not spoken_text:
            spoken_text = "here you go." if visual_events else "hmm, i don't have anything to say to that."

        speech_audio: bytes | None = None
        speech_error: str | None = None
        try:
            speech_audio = await self._services.fetch_speech(spoken_text)
        except Exception as tts_error:
            logger.warning("Text-to-speech failed: %s", tts_error)
            speech_error = str(tts_error)

        self._reply_ready.emit(
            CompanionReply(generation, spoken_text, point_target, speech_audio, speech_error, visual_events)
        )

    async def _run_typed_interaction(
        self, generation: int, text: str, screen_captures: tuple[ScreenCapture, ...]
    ) -> None:
        try:
            await self._respond(generation, text, screen_captures)
        except asyncio.CancelledError:
            raise
        except Exception as interaction_error:
            logger.exception("Typed interaction failed")
            self._interaction_failed.emit(generation, str(interaction_error))

    # ----- results back on the GUI thread -----

    def _is_current(self, generation: int) -> bool:
        return generation == self._generation

    @Slot(int)
    def _on_processing_started(self, generation: int) -> None:
        if self._is_current(generation) and self.state is CompanionState.LISTENING:
            self._set_state(CompanionState.PROCESSING)

    @Slot(int, str)
    def _on_partial_transcript(self, generation: int, transcript: str) -> None:
        if self._is_current(generation):
            self.transcript_changed.emit(transcript)

    @Slot(int, str)
    def _on_partial_reply(self, generation: int, visible_text: str) -> None:
        if self._is_current(generation):
            self.reply_text_changed.emit(visible_text)

    @Slot(int)
    def _on_nothing_heard(self, generation: int) -> None:
        if self._is_current(generation):
            self._set_state(CompanionState.IDLE)
            self.notice.emit(NOTHING_HEARD_MESSAGE)

    @Slot(int, str)
    def _on_interaction_failed(self, generation: int, message: str) -> None:
        if self._is_current(generation):
            # The failure can happen while the key is still held (e.g. the Worker is unreachable).
            self._stop_microphone()
            self._audio_queue = None
            self._set_state(CompanionState.IDLE)
            self.notice.emit(message)

    @Slot(object)
    def _on_reply_ready(self, reply: CompanionReply) -> None:
        if not self._is_current(reply.generation):
            return
        self.reply_text_changed.emit(reply.spoken_text)
        self.visuals_ready.emit(VisualPlan(reply.spoken_text, reply.visual_events, reply.speech_audio is not None))
        if reply.point_target is not None:
            self.point_requested.emit(reply.point_target)
        if reply.speech_audio is None:
            self._set_state(CompanionState.IDLE)
            # No voice, so show the answer itself (the cursor shows no reply text while Clicky talks).
            if reply.speech_error:
                self.notice.emit(
                    f"couldn't play the voice: {reply.speech_error}. here's my answer: {reply.spoken_text}"
                )
            elif reply.spoken_text:
                self.notice.emit(reply.spoken_text)
            return
        self._set_state(CompanionState.RESPONDING)
        self._player.play(reply.speech_audio)

    # ----- helpers -----

    def _set_state(self, new_state: CompanionState) -> None:
        if new_state is not self.state:
            self.state = new_state
            self.state_changed.emit(new_state.value)

    def _stop_microphone(self) -> None:
        microphone, self._microphone = self._microphone, None
        if microphone is not None:
            try:
                microphone.stop()
            except Exception:
                logger.exception("Microphone failed to stop")

    def _abort_current_interaction(self) -> None:
        # Before player.stop(): stopping reports "finished", which would otherwise flush every pending mark.
        self.interrupted.emit()
        self._stop_microphone()
        self._audio_queue = None
        future, self._interaction_future = self._interaction_future, None
        if future is not None and not future.done():
            future.cancel()
        self._player.stop()
        # Bump the generation so anything still in flight is ignored.
        self._generation += 1


async def _cancel_quietly(session: TranscriptionSession) -> None:
    try:
        await session.cancel()
    except Exception:
        logger.debug("Ignoring error while cancelling transcription", exc_info=True)
