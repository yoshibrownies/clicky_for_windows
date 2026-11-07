import time

from PySide6.QtCore import QCoreApplication


def wait_until(condition, timeout: float = 5.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        if condition():
            return
        time.sleep(0.005)
    raise AssertionError("condition not met in time")


def record(source):
    events = {"started": 0, "progress": [], "finished": 0}
    source.started.connect(lambda: events.__setitem__("started", events["started"] + 1))
    source.progress.connect(events["progress"].append)
    source.finished.connect(lambda: events.__setitem__("finished", events["finished"] + 1))
    return events


def test_system_voice_speaks_and_reports_progress_to_the_end(qt_app):
    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock")
    events = record(voice)
    voice.speak("one two three")
    wait_until(lambda: events["finished"])
    QCoreApplication.processEvents()
    assert events["started"] == 1 and events["finished"] == 1
    assert events["progress"] == sorted(events["progress"]) and events["progress"][-1] == 1.0
    assert not voice.is_playing


def test_stopping_the_system_voice_finishes_once(qt_app):
    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock")
    events = record(voice)
    voice.speak("a fairly long sentence that takes a moment to say out loud")
    voice.stop()
    wait_until(lambda: True)
    time.sleep(0.2)
    QCoreApplication.processEvents()
    assert events["finished"] == 1 and not voice.is_playing


def test_stop_without_speaking_is_safe(qt_app):
    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock")
    events = record(voice)
    voice.stop()
    assert events["finished"] == 0


def test_voice_output_routes_text_to_the_system_voice_and_stops_it(qt_app):
    from clicky.playback import SpeechPlayer
    from clicky.system_voice import SystemVoice, VoiceOutput

    output = VoiceOutput(SpeechPlayer(), SystemVoice(engine="mock"))
    events = record(output)
    output.speak_text("hello there")
    assert output.is_playing
    output.stop()
    QCoreApplication.processEvents()
    assert events["finished"] == 1 and not output.is_playing
