import asyncio
import gc
import time

from clicky.async_runner import AsyncRunner


def test_submitted_task_survives_garbage_collection_when_caller_drops_everything():
    runner = AsyncRunner()
    finished = []
    try:

        async def wait_on_private_queue(queue: asyncio.Queue) -> None:
            await queue.get()
            finished.append(True)

        holder = {"queue": asyncio.Queue()}
        runner.submit(wait_on_private_queue(holder["queue"]))  # returned future deliberately dropped
        time.sleep(0.05)
        queue = holder.pop("queue")
        runner.call_soon(queue.put_nowait, "go")
        del queue
        gc.collect()
        deadline = time.monotonic() + 2
        while not finished and time.monotonic() < deadline:
            time.sleep(0.01)
        assert finished == [True]
        assert runner.in_flight_count == 0
    finally:
        runner.stop()


def test_pending_task_is_held_while_waiting():
    runner = AsyncRunner()
    try:

        async def wait_forever() -> None:
            await asyncio.Queue().get()

        runner.submit(wait_forever())
        time.sleep(0.05)
        gc.collect()
        assert runner.in_flight_count == 1
    finally:
        runner.stop()
    assert runner.in_flight_count == 0


def test_run_returns_result_and_cancel_propagates():
    runner = AsyncRunner()
    try:

        async def add(left: int, right: int) -> int:
            return left + right

        assert runner.run(add(2, 3), timeout=2) == 5

        async def sleep_long() -> None:
            await asyncio.sleep(30)

        future = runner.submit(sleep_long())
        future.cancel()
        deadline = time.monotonic() + 2
        while runner.in_flight_count and time.monotonic() < deadline:
            time.sleep(0.01)
        assert runner.in_flight_count == 0
    finally:
        runner.stop()
