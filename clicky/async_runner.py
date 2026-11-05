"""Runs an asyncio event loop on a background thread so network work never blocks the Qt GUI thread."""

from __future__ import annotations

import asyncio
import concurrent.futures
import contextlib
import threading
from collections.abc import Callable, Coroutine
from typing import Any


class AsyncRunner:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        # asyncio only keeps weak references to tasks. A task waiting on something nobody else references
        # (e.g. an audio queue) can be garbage-collected mid-flight, so hold every submitted one until done.
        self._in_flight: set[concurrent.futures.Future] = set()
        self._in_flight_lock = threading.Lock()
        self._thread = threading.Thread(target=self._run_loop, name="clicky-asyncio", daemon=True)
        self._thread.start()

    def _run_loop(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def submit(self, coroutine: Coroutine[Any, Any, Any]) -> concurrent.futures.Future:
        """Schedule a coroutine from any thread. Cancelling the returned future cancels the task."""
        future = asyncio.run_coroutine_threadsafe(coroutine, self.loop)
        with self._in_flight_lock:
            self._in_flight.add(future)
        future.add_done_callback(self._forget)
        return future

    @property
    def in_flight_count(self) -> int:
        with self._in_flight_lock:
            return len(self._in_flight)

    def _forget(self, future: concurrent.futures.Future) -> None:
        with self._in_flight_lock:
            self._in_flight.discard(future)

    def call_soon(self, callback: Callable[..., Any], *arguments: Any) -> None:
        """Run a plain callback on the loop thread (thread-safe)."""
        self.loop.call_soon_threadsafe(callback, *arguments)

    def run(self, coroutine: Coroutine[Any, Any, Any], timeout: float | None = None) -> Any:
        """Submit and block until done. Only call this from a thread other than the loop's."""
        return self.submit(coroutine).result(timeout=timeout)

    def stop(self) -> None:
        if not self.loop.is_running():
            return

        async def cancel_remaining_tasks() -> None:
            current_task = asyncio.current_task()
            remaining_tasks = [task for task in asyncio.all_tasks() if task is not current_task]
            for task in remaining_tasks:
                task.cancel()
            await asyncio.gather(*remaining_tasks, return_exceptions=True)

        with contextlib.suppress(concurrent.futures.TimeoutError, RuntimeError):
            self.run(cancel_remaining_tasks(), timeout=3.0)
        self.loop.call_soon_threadsafe(self.loop.stop)
        self._thread.join(timeout=3.0)
        if not self.loop.is_running():
            self.loop.close()
