"""Download Clicky's free local voice (Kokoro-82M, ~142 MB) once, checking each file against its published SHA-256.

Run from the repo: python scripts/download_kokoro.py
Files go to %LOCALAPPDATA%/Clicky/models. Files already there with the right checksum are skipped.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # so `clicky` imports when run as a script

from clicky.kokoro_voice import MODEL_FILE_NAME, VOICES_FILE_NAME, default_model_dir  # noqa: E402

RELEASE_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.1"
# SHA-256 digests GitHub reports for the release assets (checked 2026-11-08).
MODEL_FILES = {
    MODEL_FILE_NAME: "ae315a79b623f244700e4afb9246c46a26066782e049ba174bf3ba433970ee9c",
    VOICES_FILE_NAME: "bca610b8308e8d99f32e6fe4197e7ec01679264efed0cac9140fe9c29f1fbf7d",
}
CHUNK_SIZE = 1024 * 1024


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        while chunk := file.read(CHUNK_SIZE):
            digest.update(chunk)
    return digest.hexdigest()


def download_file(client: httpx.Client, url: str, destination: Path, expected_sha256: str) -> None:
    """Stream to a .part file, then keep it only if its checksum matches (a bad download is deleted)."""
    part_path = destination.with_name(destination.name + ".part")
    digest = hashlib.sha256()
    try:
        with client.stream("GET", url, follow_redirects=True) as response, part_path.open("wb") as part_file:
            response.raise_for_status()
            for chunk in response.iter_bytes(CHUNK_SIZE):
                digest.update(chunk)
                part_file.write(chunk)
        if digest.hexdigest() != expected_sha256:
            raise ValueError(f"{destination.name} downloaded with the wrong checksum; deleted it, please try again")
        part_path.replace(destination)
    finally:
        part_path.unlink(missing_ok=True)


def main() -> int:
    model_dir = default_model_dir()
    model_dir.mkdir(parents=True, exist_ok=True)
    timeout = httpx.Timeout(30.0, read=120.0)
    with httpx.Client(timeout=timeout, headers={"user-agent": "clicky-windows/0.1"}) as client:
        for file_name, expected_sha256 in MODEL_FILES.items():
            destination = model_dir / file_name
            if destination.is_file() and sha256_of(destination) == expected_sha256:
                print(f"{file_name}: already downloaded")
                continue
            print(f"{file_name}: downloading...")
            try:
                download_file(client, f"{RELEASE_URL}/{file_name}", destination, expected_sha256)
            except (httpx.HTTPError, ValueError) as download_error:
                print(f"{file_name}: failed: {download_error}")
                return 1
            print(f"{file_name}: done, checksum verified")
    print(f"Kokoro voice ready in {model_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
