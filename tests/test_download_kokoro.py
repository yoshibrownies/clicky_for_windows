import hashlib
import importlib.util
from pathlib import Path

import httpx
import pytest

SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "download_kokoro.py"
_spec = importlib.util.spec_from_file_location("download_kokoro", SCRIPT_PATH)
download_kokoro = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(download_kokoro)

CONTENT = b"pretend model bytes" * 1000


def client_serving(content: bytes) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(200, content=content)))


def test_download_keeps_file_with_matching_checksum(tmp_path):
    destination = tmp_path / "model.onnx"
    with client_serving(CONTENT) as client:
        download_kokoro.download_file(
            client, "https://example.test/model.onnx", destination, hashlib.sha256(CONTENT).hexdigest()
        )
    assert destination.read_bytes() == CONTENT
    assert list(tmp_path.iterdir()) == [destination]


def test_download_deletes_file_with_wrong_checksum(tmp_path):
    destination = tmp_path / "model.onnx"
    with client_serving(CONTENT) as client, pytest.raises(ValueError, match="model.onnx"):
        download_kokoro.download_file(client, "https://example.test/model.onnx", destination, "0" * 64)
    assert list(tmp_path.iterdir()) == []


def test_sha256_of_matches_hashlib(tmp_path):
    path = tmp_path / "file.bin"
    path.write_bytes(CONTENT)
    assert download_kokoro.sha256_of(path) == hashlib.sha256(CONTENT).hexdigest()


def test_model_files_pin_the_published_checksums():
    assert download_kokoro.MODEL_FILES == {
        "kokoro-v1.0.int8.onnx": "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
        "voices-v1.0.bin": "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
    }
