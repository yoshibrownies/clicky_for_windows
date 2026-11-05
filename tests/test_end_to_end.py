"""End to end through the real network code: WorkerServices + httpx + websockets against a local fake Worker
(same three routes as worker/src/index.ts) and a local fake AssemblyAI. Only the mic, screens and speaker
are faked."""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
import websockets

from clicky.async_runner import AsyncRunner
from clicky.config import load_settings
from clicky.controller import CompanionController, CompanionState
from clicky.services import WorkerServices
from tests.test_controller import PRIMARY, SECONDARY, FakeMicrophone, FakePlayer, wait_until
from tests.test_transcription import FakeAssemblyAI


class FakeWorker(BaseHTTPRequestHandler):
    chat_bodies: list[dict] = []
    tts_bodies: list[dict] = []
    token_requests = 0

    def log_message(self, *arguments) -> None:  # keep test output quiet
        pass

    def do_POST(self) -> None:  # noqa: N802 (http.server naming)
        body = self.rfile.read(int(self.headers.get("content-length") or 0))
        if self.path == "/transcribe-token":
            FakeWorker.token_requests += 1
            self._send(200, "application/json", json.dumps({"token": "fake-token", "expires_in_seconds": 480}))
        elif self.path == "/chat":
            FakeWorker.chat_bodies.append(json.loads(body))
            events = [
                {"type": "message_start", "message": {}},
                {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "it's the "}},
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "floppy icon. [POINT:40,30:save:screen2]"},
                },
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
                {"type": "message_stop"},
            ]
            stream = "".join(f"event: {event['type']}\ndata: {json.dumps(event)}\n\n" for event in events)
            self._send(200, "text/event-stream", stream)
        elif self.path == "/tts":
            FakeWorker.tts_bodies.append(json.loads(body))
            self._send(200, "audio/mpeg", b"ID3-fake-mp3")
        else:
            self._send(404, "text/plain", "Not found")

    def _send(self, status: int, content_type: str, payload: str | bytes) -> None:
        data = payload.encode() if isinstance(payload, str) else payload
        self.send_response(status)
        self.send_header("content-type", content_type)
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


@pytest.fixture
def fake_worker_url():
    FakeWorker.chat_bodies, FakeWorker.tts_bodies, FakeWorker.token_requests = [], [], 0
    server = ThreadingHTTPServer(("127.0.0.1", 0), FakeWorker)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


def test_full_interaction_over_real_network_code(qt_app, fake_worker_url):
    runner = AsyncRunner()
    fake_assemblyai = FakeAssemblyAI()

    async def start_fake_assemblyai():
        return await websockets.serve(fake_assemblyai.handler, "127.0.0.1", 0)

    websocket_server = runner.run(start_fake_assemblyai(), timeout=5)
    try:
        websocket_port = websocket_server.sockets[0].getsockname()[1]
        settings = load_settings({"CLICKY_WORKER_URL": fake_worker_url + "/"})
        services = WorkerServices(settings, assemblyai_websocket_base_url=f"ws://127.0.0.1:{websocket_port}/v3/ws")
        player = FakePlayer()
        controller = CompanionController(
            runner=runner,
            services=services,
            microphone_factory=FakeMicrophone,
            capture_screens=lambda: [PRIMARY, SECONDARY],
            player=player,
            model=settings.model,
            effort=settings.effort,
        )
        points = []
        controller.point_requested.connect(points.append)

        controller.handle_push_to_talk_pressed()
        wait_until(lambda: fake_assemblyai.received_audio_bytes > 0)
        controller.handle_push_to_talk_released()
        wait_until(lambda: controller.state is CompanionState.RESPONDING, timeout=8)

        assert FakeWorker.token_requests == 1
        assert "token=fake-token" in fake_assemblyai.request_path
        assert "sample_rate=16000" in fake_assemblyai.request_path
        assert fake_assemblyai.received_control_messages == ["ForceEndpoint", "Terminate"]

        chat_body = FakeWorker.chat_bodies[0]
        assert chat_body["model"] == "claude-opus-5-5"
        assert chat_body["messages"][-1]["content"][-1]["text"] == "Where is the save button?"
        assert FakeWorker.tts_bodies[0]["text"] == "it's the floppy icon."
        assert player.played == [b"ID3-fake-mp3"]
        # screen2 → SECONDARY (origin 2560,0, 1920x1080 logical, image 1600x900): 40/1600*1920 = 48, 30/900*1080 = 36
        assert (points[0].global_x, points[0].global_y, points[0].label) == (2560 + 48, 36, "save")

        controller.handle_playback_finished()
        assert controller.state is CompanionState.IDLE
        runner.run(services.aclose(), timeout=5)
    finally:

        async def stop_fake_assemblyai():
            websocket_server.close()
            await websocket_server.wait_closed()

        runner.run(stop_fake_assemblyai(), timeout=5)
        runner.stop()


def test_worker_down_reports_a_readable_notice(qt_app):
    runner = AsyncRunner()
    try:
        settings = load_settings({"CLICKY_WORKER_URL": "http://127.0.0.1:9"})  # nothing listens on port 9
        services = WorkerServices(settings)
        controller = CompanionController(
            runner=runner,
            services=services,
            microphone_factory=FakeMicrophone,
            capture_screens=list,
            player=FakePlayer(),
            model=settings.model,
            effort=settings.effort,
        )
        notices = []
        controller.notice.connect(notices.append)
        controller.handle_push_to_talk_pressed()
        wait_until(lambda: notices, timeout=8)
        assert controller.state is CompanionState.IDLE
        assert "Couldn't reach the Clicky Worker" in notices[0]
        runner.run(services.aclose(), timeout=5)
    finally:
        runner.stop()
