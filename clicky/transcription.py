"""AssemblyAI v3 real-time streaming transcription (push-to-talk).

Flow per key press: fetch a short-lived token from the Worker, open the websocket, stream 16 kHz PCM16
mono audio while the key is held, then on release send ForceEndpoint, wait briefly for the final
formatted turn, and Terminate. Turn bookkeeping is ported from the macOS app.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
from collections.abc import Callable, Sequence
from urllib.parse import urlencode

import httpx
import websockets
from websockets.asyncio.client import ClientConnection, connect

from clicky.audio_capture import compute_audio_level

logger = logging.getLogger(__name__)

ASSEMBLYAI_WEBSOCKET_BASE_URL = "wss://streaming.assemblyai.com/v3/ws"
SAMPLE_RATE_HERTZ = 16000
FINAL_TRANSCRIPT_TIMEOUT_SECONDS = 2.5
# After an unformatted end-of-turn arrives, how long to wait for its formatted version.
FORMATTED_TURN_GRACE_SECONDS = 0.6
# compute_audio_level() value above which a chunk counts as speech (about -44 dBFS; room noise sits lower).
SPEECH_LEVEL_THRESHOLD = 0.2


class TranscriptionError(RuntimeError):
    pass


def build_websocket_url(
    temporary_token: str, keyterms: Sequence[str] = (), base_url: str = ASSEMBLYAI_WEBSOCKET_BASE_URL
) -> str:
    query_parameters = {
        "sample_rate": str(SAMPLE_RATE_HERTZ),
        "encoding": "pcm_s16le",
        "format_turns": "true",
        "speech_model": "u3-rt-pro",
    }
    normalized_keyterms = [keyterm.strip() for keyterm in keyterms if keyterm.strip()]
    if normalized_keyterms:
        query_parameters["keyterms_prompt"] = json.dumps(normalized_keyterms)
    query_parameters["token"] = temporary_token
    return f"{base_url}?{urlencode(query_parameters)}"


async def fetch_temporary_token(client: httpx.AsyncClient, token_url: str) -> str:
    try:
        response = await client.post(token_url, timeout=10.0)
    except httpx.HTTPError as network_error:
        raise TranscriptionError(f"Couldn't reach the Clicky Worker: {network_error}") from network_error
    if response.status_code != 200:
        raise TranscriptionError(f"Worker /transcribe-token failed ({response.status_code}): {response.text[:200]}")
    try:
        token = response.json().get("token")
    except ValueError:
        token = None
    if not isinstance(token, str) or not token:
        raise TranscriptionError("Worker /transcribe-token returned no token.")
    return token


class TurnTranscriptTracker:
    """Builds the running transcript from AssemblyAI Turn messages.

    Completed turns are stored by turn_order (a formatted version never gets overwritten by an unformatted
    one); the turn still in progress is appended at the end.
    """

    def __init__(self) -> None:
        self._completed_turns: dict[int, tuple[str, bool]] = {}
        self._active_turn_order: int | None = None
        self._active_turn_text = ""
        self.last_handled_turn_order = -1

    @property
    def active_turn_order(self) -> int | None:
        """turn_order of the turn still in progress, or None when the speaker is between turns."""
        return self._active_turn_order

    @property
    def latest_completed_turn(self) -> tuple[int, bool] | None:
        """(turn_order, is_formatted) of the highest completed turn, if any."""
        if not self._completed_turns:
            return None
        latest_order = max(self._completed_turns)
        return latest_order, self._completed_turns[latest_order][1]

    def handle_turn(self, turn_message: dict) -> bool:
        """Apply one Turn message. Returns True when it completed a turn."""
        transcript_text = (turn_message.get("transcript") or "").strip()
        turn_order = turn_message.get("turn_order")
        if not isinstance(turn_order, int):
            if self._active_turn_order is not None:
                turn_order = self._active_turn_order
            else:
                turn_order = max(self._completed_turns, default=-1) + 1

        self.last_handled_turn_order = turn_order
        is_formatted = turn_message.get("turn_is_formatted") is True
        completed_turn = turn_message.get("end_of_turn") is True or is_formatted
        if completed_turn:
            self._active_turn_order = None
            self._active_turn_text = ""
            existing_turn = self._completed_turns.get(turn_order)
            already_have_formatted = existing_turn is not None and existing_turn[1]
            if transcript_text and not (already_have_formatted and not is_formatted):
                self._completed_turns[turn_order] = (transcript_text, is_formatted)
        else:
            self._active_turn_order = turn_order
            self._active_turn_text = transcript_text
        return completed_turn

    def full_transcript(self) -> str:
        parts = [self._completed_turns[order][0] for order in sorted(self._completed_turns)]
        if self._active_turn_text and self._active_turn_order not in self._completed_turns:
            parts.append(self._active_turn_text)
        return " ".join(parts).strip()


class AssemblyAIStreamingSession:
    """One push-to-talk utterance. Create, open(), send_audio() repeatedly, then finish() or cancel()."""

    def __init__(
        self,
        websocket_url: str,
        on_transcript_update: Callable[[str], None] | None = None,
        open_timeout: float = 10.0,
    ) -> None:
        self._websocket_url = websocket_url
        self._on_transcript_update = on_transcript_update
        self._open_timeout = open_timeout
        self._tracker = TurnTranscriptTracker()
        self._connection: ClientConnection | None = None
        self._receiver_task: asyncio.Task | None = None
        self._session_began: asyncio.Future | None = None
        # After release: only turns with turn_order >= this count as "the final turn" (an earlier turn's
        # late formatted copy must not end the wait early).
        self._final_turn_minimum_order: int | None = None
        self._final_turn_ended = asyncio.Event()
        self._final_turn_formatted = asyncio.Event()
        self._terminated = asyncio.Event()
        self._closing_by_us = False
        self._closed = False
        self._error: str | None = None
        # True when audio went out after the last completed turn. AssemblyAI's partials lag the audio, so "no turn
        # in progress yet" does not mean "nothing left to transcribe".
        self._audio_sent_since_completed_turn = False
        self._any_turn_received = False

    @property
    def latest_transcript(self) -> str:
        return self._tracker.full_transcript()

    async def open(self) -> None:
        self._session_began = asyncio.get_running_loop().create_future()
        try:
            self._connection = await connect(self._websocket_url, open_timeout=self._open_timeout, max_size=None)
        except (OSError, websockets.WebSocketException, TimeoutError) as connect_error:
            raise TranscriptionError(f"Couldn't connect to AssemblyAI: {connect_error}") from connect_error
        self._receiver_task = asyncio.create_task(self._receive_messages())
        try:
            await asyncio.wait_for(asyncio.shield(self._session_began), timeout=self._open_timeout)
        except TimeoutError as timeout_error:
            await self._close(send_terminate=False)
            raise TranscriptionError("AssemblyAI didn't start the session in time.") from timeout_error
        except BaseException:
            # TranscriptionError from the server, or the interaction being cancelled mid-open: either way the
            # socket must not outlive this call, or it keeps an AssemblyAI session (and its billing) open.
            await asyncio.shield(self._close(send_terminate=False))
            raise

    async def send_audio(self, pcm16_audio: bytes) -> None:
        if self._closed or self._connection is None or not pcm16_audio:
            return
        try:
            await self._connection.send(pcm16_audio)
            # The mic streams silence too while the key is held; only audible audio can still become words.
            # Before any words have come back, any audio counts: a quiet mic must not lose a short question.
            if not self._any_turn_received or compute_audio_level(pcm16_audio) >= SPEECH_LEVEL_THRESHOLD:
                self._audio_sent_since_completed_turn = True
        except websockets.ConnectionClosed as closed_error:
            self._record_unexpected_close(closed_error)
            self._closed = True

    async def finish(self, timeout: float = FINAL_TRANSCRIPT_TIMEOUT_SECONDS) -> str:
        """Ask AssemblyAI to close the current turn and return the best transcript available."""
        if self._connection is not None and not self._closed:
            active_turn_order = self._tracker.active_turn_order
            latest_completed_turn = self._tracker.latest_completed_turn
            if active_turn_order is not None or self._audio_sent_since_completed_turn:
                # Mid-sentence, or speech not transcribed yet: force the turn to end and wait for it.
                if active_turn_order is not None:
                    self._final_turn_minimum_order = active_turn_order
                else:
                    self._final_turn_minimum_order = latest_completed_turn[0] + 1 if latest_completed_turn else 0
                await self._send_control_message("ForceEndpoint")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._final_turn_ended.wait(), timeout=timeout)
                if self._final_turn_ended.is_set() and not self._final_turn_formatted.is_set():
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(self._final_turn_formatted.wait(), timeout=FORMATTED_TURN_GRACE_SECONDS)
            elif latest_completed_turn is not None and not latest_completed_turn[1]:
                # Between turns but the last one isn't formatted yet: wait briefly for its formatted copy.
                self._final_turn_minimum_order = latest_completed_turn[0]
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._final_turn_formatted.wait(), timeout=FORMATTED_TURN_GRACE_SECONDS)
            # Otherwise nothing is pending: no wait at all.
        transcript = self._tracker.full_transcript()
        await self._close(send_terminate=True)
        if not transcript and self._error:
            raise TranscriptionError(self._error)
        if self._error:
            logger.warning("Returning partial transcript after AssemblyAI error: %s", self._error)
        return transcript

    async def cancel(self) -> None:
        await self._close(send_terminate=True)

    async def _send_control_message(self, message_type: str) -> None:
        if self._connection is None or self._closed:
            return
        try:
            await self._connection.send(json.dumps({"type": message_type}))
        except websockets.ConnectionClosed as closed_error:
            self._record_unexpected_close(closed_error)
            self._closed = True

    async def _close(self, send_terminate: bool) -> None:
        if self._closed and self._connection is None and self._receiver_task is None:
            return
        self._closing_by_us = True
        connection = self._connection
        if connection is not None:
            if send_terminate and not self._closed:
                await self._send_control_message("Terminate")
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._terminated.wait(), timeout=1.0)
            with contextlib.suppress(Exception):
                await connection.close()
        self._closed = True
        self._connection = None
        if self._receiver_task is not None:
            self._receiver_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._receiver_task
            self._receiver_task = None

    def _record_unexpected_close(self, closed_error: websockets.ConnectionClosed) -> None:
        """AssemblyAI reports most failures (limits, bad audio, expired session) by closing with a code."""
        if self._closing_by_us or self._error:
            return
        close_frame = closed_error.rcvd
        if close_frame is not None and close_frame.code == 1000:
            return
        if close_frame is None:
            self._error = "Lost the connection to AssemblyAI."
        else:
            self._error = (
                f"AssemblyAI ended the session ({close_frame.code}): {close_frame.reason or 'no reason given'}"
            )
        logger.warning("%s", self._error)

    def _fail(self, message: str) -> None:
        self._error = message
        logger.warning("AssemblyAI error: %s", message)
        if self._session_began is not None and not self._session_began.done():
            self._session_began.set_exception(TranscriptionError(message))
        self._final_turn_ended.set()
        self._final_turn_formatted.set()

    def _handle_turn_message(self, message: dict) -> None:
        completed_turn = self._tracker.handle_turn(message)
        self._any_turn_received = True
        if completed_turn:
            self._audio_sent_since_completed_turn = False
        full_transcript = self._tracker.full_transcript()
        if full_transcript and self._on_transcript_update is not None:
            self._on_transcript_update(full_transcript)
        minimum_order = self._final_turn_minimum_order
        if completed_turn and minimum_order is not None and self._tracker.last_handled_turn_order >= minimum_order:
            self._final_turn_ended.set()
            if message.get("turn_is_formatted") is True:
                self._final_turn_formatted.set()

    async def _receive_messages(self) -> None:
        assert self._connection is not None
        try:
            async for raw_message in self._connection:
                text = raw_message.decode("utf-8", errors="replace") if isinstance(raw_message, bytes) else raw_message
                try:
                    message = json.loads(text)
                except ValueError:
                    continue
                if not isinstance(message, dict):
                    continue
                message_type = str(message.get("type", "")).lower()
                if message_type == "begin":
                    if self._session_began is not None and not self._session_began.done():
                        self._session_began.set_result(None)
                elif message_type == "turn":
                    self._handle_turn_message(message)
                elif message_type == "termination":
                    self._terminated.set()
                    self._final_turn_ended.set()
                    self._final_turn_formatted.set()
                elif message_type == "error" or "error" in message:
                    self._fail(str(message.get("error") or message.get("message") or "AssemblyAI error"))
        except websockets.ConnectionClosed as closed_error:
            self._record_unexpected_close(closed_error)
        finally:
            self._terminated.set()
            self._final_turn_ended.set()
            self._final_turn_formatted.set()
            if self._session_began is not None and not self._session_began.done():
                self._fail(self._error or "AssemblyAI closed the connection before the session began.")
