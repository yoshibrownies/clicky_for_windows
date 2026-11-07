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


def record_failures(source):
    failures = []
    source.failed.connect(failures.append)
    return failures


def test_a_voice_already_in_an_error_state_fails_at_once(qt_app):
    from PySide6.QtTextToSpeech import QTextToSpeech

    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock")
    events, failures = record(voice), record_failures(voice)
    voice._speech.state = lambda: QTextToSpeech.State.Error  # say() would change nothing, so nothing would report
    voice.speak("hello")
    assert failures and not voice.is_playing and events["finished"] == 1


def test_a_voice_that_never_starts_gives_up_after_the_timeout(qt_app):
    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock", start_timeout_ms=100)
    events, failures = record(voice), record_failures(voice)
    voice._speech.say = lambda text: None  # the engine silently does nothing
    voice.speak("hello")
    wait_until(lambda: failures, timeout=2.0)
    assert events["finished"] == 1 and not voice.is_playing


def test_an_error_while_speaking_fails_then_finishes_once(qt_app):
    from PySide6.QtTextToSpeech import QTextToSpeech

    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock")
    order = []
    voice.failed.connect(lambda message: order.append("failed"))
    voice.finished.connect(lambda: order.append("finished"))
    voice.speak("a sentence long enough to still be speaking")
    voice._on_state_changed(QTextToSpeech.State.Error)
    voice.stop()
    assert order == ["failed", "finished"]


def test_voice_output_forwards_failures(qt_app):
    from clicky.playback import SpeechPlayer
    from clicky.system_voice import SystemVoice, VoiceOutput

    voice = SystemVoice(engine="mock")
    output = VoiceOutput(SpeechPlayer(), voice)
    failures = record_failures(output)
    output.speak_text("   ")  # nothing to say
    assert failures


def test_a_timeout_is_reported_as_a_failure_even_if_stopping_reports_ready(qt_app):
    from PySide6.QtTextToSpeech import QTextToSpeech

    from clicky.system_voice import SystemVoice

    voice = SystemVoice(engine="mock", start_timeout_ms=100)
    failures = record_failures(voice)
    events = record(voice)
    voice._speech.say = lambda text: None
    voice._speech.stop = lambda *args: voice._on_state_changed(QTextToSpeech.State.Ready)  # like winrt
    voice.speak("hello")
    wait_until(lambda: events["finished"], timeout=2.0)
    assert failures and events["finished"] == 1
