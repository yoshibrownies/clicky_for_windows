import asyncio
import json
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import websockets

from clicky.transcription import (
    AssemblyAIStreamingSession,
    TranscriptionError,
    TurnTranscriptTracker,
    build_websocket_url,
    fetch_temporary_token,
)

# ---------- URL ----------


def test_websocket_url_has_required_query_parameters():
    url = build_websocket_url("tok123", keyterms=["Clicky", "  ", "PySide"])
    parsed = urlparse(url)
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == "wss://streaming.assemblyai.com/v3/ws"
    query = parse_qs(parsed.query)
    assert query["sample_rate"] == ["16000"]
    assert query["encoding"] == ["pcm_s16le"]
    assert query["format_turns"] == ["true"]
    assert query["speech_model"] == ["u3-rt-pro"]
    assert query["token"] == ["tok123"]
    assert json.loads(query["keyterms_prompt"][0]) == ["Clicky", "PySide"]


def test_websocket_url_omits_empty_keyterms():
    query = parse_qs(urlparse(build_websocket_url("t", keyterms=[])).query)
    assert "keyterms_prompt" not in query


# ---------- turn tracker ----------


def test_tracker_combines_completed_turns_and_active_partial():
    tracker = TurnTranscriptTracker()
    tracker.handle_turn({"turn_order": 0, "transcript": "hello", "end_of_turn": False})
    assert tracker.full_transcript() == "hello"
    tracker.handle_turn({"turn_order": 0, "transcript": "hello there", "end_of_turn": True})
    tracker.handle_turn({"turn_order": 1, "transcript": "how do i", "end_of_turn": False})
    assert tracker.full_transcript() == "hello there how do i"


def test_tracker_formatted_turn_wins_over_unformatted():
    tracker = TurnTranscriptTracker()
    tracker.handle_turn({"turn_order": 0, "transcript": "Hello there.", "end_of_turn": True, "turn_is_formatted": True})
    tracker.handle_turn({"turn_order": 0, "transcript": "hello there", "end_of_turn": True, "turn_is_formatted": False})
    assert tracker.full_transcript() == "Hello there."


def test_tracker_orders_turns_by_turn_order():
    tracker = TurnTranscriptTracker()
    tracker.handle_turn({"turn_order": 1, "transcript": "second", "end_of_turn": True})
    tracker.handle_turn({"turn_order": 0, "transcript": "first", "end_of_turn": True})
    assert tracker.full_transcript() == "first second"


def test_tracker_reports_whether_message_completed_a_turn():
    tracker = TurnTranscriptTracker()
    assert tracker.handle_turn({"turn_order": 0, "transcript": "a", "end_of_turn": False}) is False
    assert tracker.handle_turn({"turn_order": 0, "transcript": "a", "end_of_turn": True}) is True


# ---------- token ----------


async def test_fetch_temporary_token_posts_and_reads_token():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        return httpx.Response(200, json={"token": "abc", "expires_in_seconds": 480})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        assert await fetch_temporary_token(client, "https://w.test/transcribe-token") == "abc"


@pytest.mark.parametrize("response", [httpx.Response(401, text="nope"), httpx.Response(200, json={"x": 1})])
async def test_fetch_temporary_token_raises_on_bad_response(response):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda request: response)) as client:
        with pytest.raises(TranscriptionError):
            await fetch_temporary_token(client, "https://w.test/transcribe-token")


# ---------- session against a fake AssemblyAI server ----------


class FakeAssemblyAI:
    """Speaks the v3 protocol: Begin on connect, a partial per audio frame, a final turn on ForceEndpoint."""

    def __init__(self, respond_to_force_endpoint: bool = True) -> None:
        self.respond_to_force_endpoint = respond_to_force_endpoint
        self.received_audio_bytes = 0
        self.received_control_messages: list[str] = []
        self.request_path = ""

    async def handler(self, connection) -> None:
        self.request_path = connection.request.path
        await connection.send(json.dumps({"type": "Begin", "id": "session-1"}))
        try:
            async for message in connection:
                if isinstance(message, bytes):
                    self.received_audio_bytes += len(message)
                    await connection.send(
                        json.dumps({"type": "Turn", "turn_order": 0, "transcript": "where is", "end_of_turn": False})
                    )
                    continue
                message_type = json.loads(message)["type"]
                self.received_control_messages.append(message_type)
                if message_type == "ForceEndpoint" and self.respond_to_force_endpoint:
                    await connection.send(
                        json.dumps(
                            {
                                "type": "Turn",
                                "turn_order": 0,
                                "transcript": "Where is the save button?",
                                "end_of_turn": True,
                                "turn_is_formatted": True,
                            }
                        )
                    )
                elif message_type == "Terminate":
                    await connection.send(json.dumps({"type": "Termination"}))
                    await connection.close()
                    return
        except websockets.ConnectionClosed:
            return


async def run_session(fake: FakeAssemblyAI, finish_timeout: float = 2.5) -> tuple[str, list[str]]:
    updates: list[str] = []
    async with websockets.serve(fake.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(
            websocket_url=f"ws://127.0.0.1:{port}/v3/ws?token=t", on_transcript_update=updates.append
        )
        await session.open()
        for _ in range(3):
            await session.send_audio(b"\x00\x01" * 1600)
        await asyncio.sleep(0.2)
        transcript = await session.finish(timeout=finish_timeout)
    return transcript, updates


async def test_session_returns_final_formatted_transcript():
    fake = FakeAssemblyAI()
    transcript, updates = await run_session(fake)
    assert transcript == "Where is the save button?"
    assert "where is" in updates
    assert fake.received_audio_bytes == 3 * 3200
    assert fake.received_control_messages == ["ForceEndpoint", "Terminate"]
    assert "token=t" in fake.request_path


async def test_session_falls_back_to_partial_transcript_after_timeout():
    fake = FakeAssemblyAI(respond_to_force_endpoint=False)
    transcript, _ = await run_session(fake, finish_timeout=0.3)
    assert transcript == "where is"


async def test_session_open_raises_on_error_message():
    async def error_handler(connection) -> None:
        await connection.send(json.dumps({"type": "Error", "error": "Invalid token"}))
        await connection.close()

    async with websockets.serve(error_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws")
        with pytest.raises(TranscriptionError, match="Invalid token"):
            await session.open()


async def test_cancel_closes_without_error():
    fake = FakeAssemblyAI()
    async with websockets.serve(fake.handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws")
        await session.open()
        await session.cancel()
        await session.cancel()  # idempotent
        await session.send_audio(b"\x00\x00")  # ignored after cancel


# ---------- review fixes: cancellation, server close errors, late formatted turns ----------


async def test_cancel_while_waiting_for_begin_closes_the_connection():
    server_saw_close = asyncio.Event()

    async def silent_handler(connection) -> None:  # never sends Begin
        await connection.wait_closed()
        server_saw_close.set()

    async with websockets.serve(silent_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws", open_timeout=10)
        open_task = asyncio.create_task(session.open())
        await asyncio.sleep(0.3)
        open_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await open_task
        await asyncio.wait_for(server_saw_close.wait(), timeout=2)


async def test_server_close_after_begin_is_reported_not_swallowed():
    async def closing_handler(connection) -> None:
        await connection.send(json.dumps({"type": "Begin"}))
        await connection.recv()  # first audio frame
        await connection.close(code=3005, reason="Too many concurrent sessions")

    async with websockets.serve(closing_handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws")
        await session.open()
        await session.send_audio(b"\x00\x00" * 800)
        await asyncio.sleep(0.2)
        await session.send_audio(b"\x00\x00" * 800)
        with pytest.raises(TranscriptionError, match="Too many concurrent sessions"):
            await session.finish(timeout=0.5)


async def test_error_key_without_type_is_treated_as_error():
    async def handler(connection) -> None:
        await connection.send(json.dumps({"error": "Invalid token"}))
        await connection.wait_closed()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws", open_timeout=2)
        with pytest.raises(TranscriptionError, match="Invalid token"):
            await session.open()


async def test_late_formatted_earlier_turn_does_not_cut_off_the_last_turn():
    async def handler(connection) -> None:
        await connection.send(json.dumps({"type": "Begin"}))
        async for message in connection:
            if isinstance(message, bytes):
                await connection.send(
                    json.dumps({"type": "Turn", "turn_order": 0, "transcript": "first sentence", "end_of_turn": True})
                )
                await connection.send(
                    json.dumps({"type": "Turn", "turn_order": 1, "transcript": "second part", "end_of_turn": False})
                )
                continue
            message_type = json.loads(message)["type"]
            if message_type == "ForceEndpoint":
                await connection.send(
                    json.dumps(
                        {
                            "type": "Turn",
                            "turn_order": 0,
                            "transcript": "First sentence.",
                            "end_of_turn": True,
                            "turn_is_formatted": True,
                        }
                    )
                )
                await asyncio.sleep(0.15)
                await connection.send(
                    json.dumps(
                        {
                            "type": "Turn",
                            "turn_order": 1,
                            "transcript": "Second part?",
                            "end_of_turn": True,
                            "turn_is_formatted": True,
                        }
                    )
                )
            elif message_type == "Terminate":
                await connection.send(json.dumps({"type": "Termination"}))
                return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws")
        await session.open()
        await session.send_audio(b"\x00\x00" * 800)
        await asyncio.sleep(0.2)
        assert await session.finish() == "First sentence. Second part?"


async def test_finish_returns_quickly_when_no_turn_is_in_progress():
    async def handler(connection) -> None:
        await connection.send(json.dumps({"type": "Begin"}))
        async for message in connection:
            if isinstance(message, bytes):
                await connection.send(
                    json.dumps(
                        {
                            "type": "Turn",
                            "turn_order": 0,
                            "transcript": "Hello there.",
                            "end_of_turn": True,
                            "turn_is_formatted": True,
                        }
                    )
                )
            elif json.loads(message)["type"] == "Terminate":
                await connection.send(json.dumps({"type": "Termination"}))
                return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        session = AssemblyAIStreamingSession(websocket_url=f"ws://127.0.0.1:{port}/v3/ws")
        await session.open()
        await session.send_audio(b"\x00\x00" * 800)
        await asyncio.sleep(0.2)
        started = asyncio.get_running_loop().time()
        assert await session.finish(timeout=2.5) == "Hello there."
        assert asyncio.get_running_loop().time() - started < 1.0
