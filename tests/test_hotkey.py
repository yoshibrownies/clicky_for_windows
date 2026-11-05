import pytest

from clicky.hotkey import (
    VK_CONTROL,
    VK_LBUTTON,
    VK_LCONTROL,
    VK_LMENU,
    VK_MENU,
    VK_RCONTROL,
    VK_RMENU,
    HotkeyParseError,
    PushToTalkEvent,
    PushToTalkStateMachine,
    parse_hotkey,
)

LEFT_CTRL_DOWN = {VK_CONTROL, VK_LCONTROL}
LEFT_ALT_DOWN = {VK_MENU, VK_LMENU}
CTRL_ALT_DOWN = frozenset(LEFT_CTRL_DOWN | LEFT_ALT_DOWN)
KEY_T = 0x54
KEY_E = 0x45


def make_machine(hotkey: str = "ctrl+alt", delay: float = 0.15) -> PushToTalkStateMachine:
    return PushToTalkStateMachine(parse_hotkey(hotkey), activation_delay_seconds=delay)


def run(machine: PushToTalkStateMachine, steps: list[tuple[float, set[int] | frozenset[int]]]) -> list:
    events = []
    for timestamp, pressed_keys in steps:
        event = machine.update(frozenset(pressed_keys), timestamp)
        if event is not None:
            events.append((timestamp, event))
    return events


def test_parse_hotkey_groups():
    parsed = parse_hotkey(" Ctrl + ALT ")
    assert len(parsed.required_key_groups) == 2
    assert VK_LCONTROL in parsed.required_key_groups[0]
    assert VK_RMENU in parsed.required_key_groups[1]


@pytest.mark.parametrize("bad", ["", "ctrl+", "ctrl+banana", "ctrl+ctrl", "+"])
def test_parse_hotkey_rejects_bad_input(bad):
    with pytest.raises(HotkeyParseError):
        parse_hotkey(bad)


def test_press_after_hold_delay_then_release():
    events = run(
        make_machine(),
        [
            (0.00, LEFT_CTRL_DOWN),
            (0.02, CTRL_ALT_DOWN),
            (0.10, CTRL_ALT_DOWN),
            (0.17, CTRL_ALT_DOWN),
            (0.50, CTRL_ALT_DOWN),
            (0.60, LEFT_CTRL_DOWN),
            (0.70, set()),
        ],
    )
    assert events == [(0.17, PushToTalkEvent.PRESSED), (0.60, PushToTalkEvent.RELEASED)]


def test_quick_tap_does_nothing():
    events = run(make_machine(), [(0.0, CTRL_ALT_DOWN), (0.05, CTRL_ALT_DOWN), (0.08, set())])
    assert events == []


def test_shortcut_with_extra_key_before_activation_never_fires():
    events = run(
        make_machine(),
        [
            (0.00, CTRL_ALT_DOWN),
            (0.05, CTRL_ALT_DOWN | {KEY_T}),
            (0.30, CTRL_ALT_DOWN),  # T released, ctrl+alt still held: stays blocked
            (0.60, CTRL_ALT_DOWN),
            (0.70, set()),
        ],
    )
    assert events == []


def test_extra_key_while_active_cancels_and_blocks_until_release():
    machine = make_machine()
    events = run(
        machine,
        [
            (0.00, CTRL_ALT_DOWN),
            (0.20, CTRL_ALT_DOWN),
            (0.40, CTRL_ALT_DOWN | {KEY_T}),
            (0.50, CTRL_ALT_DOWN),
            (0.90, CTRL_ALT_DOWN),
            (1.00, set()),
            (1.10, CTRL_ALT_DOWN),
            (1.30, CTRL_ALT_DOWN),
        ],
    )
    assert events == [
        (0.20, PushToTalkEvent.PRESSED),
        (0.40, PushToTalkEvent.CANCELLED),
        (1.30, PushToTalkEvent.PRESSED),
    ]


def test_mouse_buttons_are_ignored():
    events = run(make_machine(), [(0.0, CTRL_ALT_DOWN | {VK_LBUTTON}), (0.2, CTRL_ALT_DOWN | {VK_LBUTTON})])
    assert events == [(0.2, PushToTalkEvent.PRESSED)]


def test_right_side_modifiers_also_count_for_generic_names():
    right_side = frozenset({VK_CONTROL, VK_RCONTROL, VK_MENU, VK_RMENU})
    events = run(make_machine(), [(0.0, right_side), (0.2, right_side), (0.3, set())])
    assert [event for _, event in events] == [PushToTalkEvent.PRESSED, PushToTalkEvent.RELEASED]


def test_altgr_typing_does_not_start_recording():
    # AltGr arrives as Left Ctrl + Right Alt; typing AltGr+E (e.g. the euro sign) adds a letter quickly.
    altgr_down = frozenset({VK_CONTROL, VK_LCONTROL, VK_MENU, VK_RMENU})
    events = run(make_machine(), [(0.00, altgr_down), (0.06, altgr_down | {KEY_E}), (0.12, set())])
    assert events == []


def test_side_specific_hotkey_treats_other_side_as_extra_key():
    machine = make_machine("right_ctrl")
    events = run(
        machine,
        [
            (0.0, {VK_CONTROL, VK_RCONTROL}),
            (0.2, {VK_CONTROL, VK_RCONTROL}),
            (0.3, {VK_CONTROL, VK_RCONTROL, VK_LCONTROL}),
        ],
    )
    assert [event for _, event in events] == [PushToTalkEvent.PRESSED, PushToTalkEvent.CANCELLED]


def test_zero_delay_fires_immediately():
    events = run(make_machine(delay=0.0), [(0.0, CTRL_ALT_DOWN)])
    assert events == [(0.0, PushToTalkEvent.PRESSED)]


def test_force_release_returns_machine_to_blocked_state():
    machine = make_machine()
    run(machine, [(0.0, CTRL_ALT_DOWN), (0.2, CTRL_ALT_DOWN)])
    machine.reset()
    assert run(machine, [(0.3, CTRL_ALT_DOWN), (0.6, CTRL_ALT_DOWN)]) == []
    assert run(machine, [(0.7, set()), (0.8, CTRL_ALT_DOWN), (1.0, CTRL_ALT_DOWN)]) == [
        (1.0, PushToTalkEvent.PRESSED)
    ]
