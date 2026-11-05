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
from clicky.conversation import ConversationHistory
from clicky.pointing import parse_point_tag
from clicky.prompts import COMPANION_SYSTEM_PROMPT, REFUSAL_SPOKEN_REPLY
from clicky.screens import ScreenCapture, map_image_point_to_screen

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
class CompanionReply:
    generation: int
    spoken_text: str
    point_target: PointTarget | None
    speech_audio: bytes | None
    speech_error: str | None


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


def visible_reply_text(partial_reply: str) -> str:
    """What the speech bubble shows while streaming: everything before a (possibly half-written) tag."""
    visible_text = partial_reply.split("[POINT", 1)[0]
    last_bracket_index = visible_text.rfind("[")
    if last_bracket_index != -1 and "[POINT".startswith(visible_text[last_bracket_index:]):
        visible_text = visible_text[:last_bracket_index]
    return visible_text.rstrip()


class CompanionController(QObject):
    state_changed = Signal(str)
    audio_level_changed = Signal(float)
    transcript_changed = Signal(str)
    reply_text_changed = Signal(str)
    point_requested = Signal(object)  # PointTarget
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

            request_body = build_chat_request_body(
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

            if stop_reason == "refusal":
                spoken_text, point_target = REFUSAL_SPOKEN_REPLY, None
            else:
                spoken_text, point_target = resolve_point_target(reply_text, screen_captures)
                self.history.add(transcript, reply_text)
            if not spoken_text:
                spoken_text = "hmm, i don't have anything to say to that."

            speech_audio: bytes | None = None
            speech_error: str | None = None
            try:
                speech_audio = await self._services.fetch_speech(spoken_text)
            except Exception as tts_error:
                logger.warning("Text-to-speech failed: %s", tts_error)
                speech_error = str(tts_error)

            self._reply_ready.emit(CompanionReply(generation, spoken_text, point_target, speech_audio, speech_error))
        except asyncio.CancelledError:
            raise
        except Exception as interaction_error:
            logger.exception("Interaction failed")
            self._interaction_failed.emit(generation, str(interaction_error))
        finally:
            if session is not None:
                await asyncio.shield(_cancel_quietly(session))

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
        if reply.point_target is not None:
            self.point_requested.emit(reply.point_target)
        if reply.speech_audio is None:
            self._set_state(CompanionState.IDLE)
            if reply.speech_error:
                self.notice.emit(f"couldn't play the voice: {reply.speech_error}")
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
