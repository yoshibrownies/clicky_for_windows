import logging
import sys
import threading

from clicky.app import install_exception_logging, mask_worker_url


def test_mask_worker_url_hides_the_spendable_host():
    masked = mask_worker_url("https://clicky-proxy.yoshi-secret.workers.dev")
    assert "yoshi-secret" not in masked
    assert masked.startswith("https://")
    assert mask_worker_url("http://127.0.0.1:8787") == "http://127.0.0.1:8787"  # local dev stays readable


def test_uncaught_exceptions_reach_the_log(caplog):
    previous_hooks = (sys.excepthook, threading.excepthook)
    try:
        install_exception_logging()
        with caplog.at_level(logging.CRITICAL, logger="clicky"):
            try:
                raise ValueError("boom in a Qt slot")
            except ValueError:
                sys.excepthook(*sys.exc_info())

            def crash_in_thread() -> None:
                raise RuntimeError("boom in a thread")

            worker = threading.Thread(target=crash_in_thread)
            worker.start()
            worker.join()
        messages = " ".join(record.getMessage() + str(record.exc_info) for record in caplog.records)
        assert "boom in a Qt slot" in messages
        assert "boom in a thread" in messages
    finally:
        sys.excepthook, threading.excepthook = previous_hooks


def test_escape_stops_speech_and_clears_the_screen():
    from clicky.app import build_escape_handler

    calls = []

    class FakeController:
        def stop_speaking(self) -> bool:
            calls.append("stop")
            return True

    visible = {"value": False}
    handle_escape = build_escape_handler(FakeController(), lambda: calls.append("clear"), lambda: visible["value"])
    handle_escape()
    assert calls == ["stop"]  # nothing on screen, but the voice still stops
    visible["value"] = True
    handle_escape()
    assert calls == ["stop", "stop", "clear"]
