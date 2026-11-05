"""Global push-to-talk hotkey for Windows.

Why polling instead of a keyboard hook: GetAsyncKeyState needs no admin rights, can't swallow or delay
keystrokes for other apps, and avoids depending on the unmaintained `keyboard` package. A poll every
15 ms is far below human reaction time.

Typing safety: the combo must be held for a short moment with no other key down before recording starts,
and pressing any other key while it is held cancels. So shortcuts like Ctrl+Alt+Del or Ctrl+Alt+T, and
AltGr characters (Windows reports AltGr as Ctrl+Right Alt), don't trigger Clicky.
"""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum, auto

logger = logging.getLogger(__name__)

VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2 = 0x01, 0x02, 0x04, 0x05, 0x06
VK_SHIFT, VK_CONTROL, VK_MENU = 0x10, 0x11, 0x12
VK_LSHIFT, VK_RSHIFT, VK_LCONTROL, VK_RCONTROL, VK_LMENU, VK_RMENU = 0xA0, 0xA1, 0xA2, 0xA3, 0xA4, 0xA5
VK_LWIN, VK_RWIN = 0x5B, 0x5C
VK_F13 = 0x7C

# Mouse buttons, plus codes some keyboards/drivers report spuriously.
IGNORED_VIRTUAL_KEYS = frozenset({VK_LBUTTON, VK_RBUTTON, VK_MBUTTON, VK_XBUTTON1, VK_XBUTTON2, 0x07, 0xE7, 0xFF})

# name -> (keys that satisfy it, extra keys Windows also reports down at the same time)
KEY_NAMES: dict[str, tuple[frozenset[int], frozenset[int]]] = {
    "ctrl": (frozenset({VK_CONTROL, VK_LCONTROL, VK_RCONTROL}), frozenset()),
    "left_ctrl": (frozenset({VK_LCONTROL}), frozenset({VK_CONTROL})),
    "right_ctrl": (frozenset({VK_RCONTROL}), frozenset({VK_CONTROL})),
    "alt": (frozenset({VK_MENU, VK_LMENU, VK_RMENU}), frozenset()),
    "left_alt": (frozenset({VK_LMENU}), frozenset({VK_MENU})),
    "right_alt": (frozenset({VK_RMENU}), frozenset({VK_MENU})),
    "shift": (frozenset({VK_SHIFT, VK_LSHIFT, VK_RSHIFT}), frozenset()),
    "left_shift": (frozenset({VK_LSHIFT}), frozenset({VK_SHIFT})),
    "right_shift": (frozenset({VK_RSHIFT}), frozenset({VK_SHIFT})),
    "win": (frozenset({VK_LWIN, VK_RWIN}), frozenset()),
    **{f"f{number}": (frozenset({VK_F13 + number - 13}), frozenset()) for number in range(13, 25)},
}
KEY_NAME_ALIASES = {"control": "ctrl", "menu": "alt", "windows": "win", "super": "win"}


class HotkeyParseError(ValueError):
    pass


@dataclass(frozen=True)
class ParsedHotkey:
    text: str
    required_key_groups: tuple[frozenset[int], ...]
    """Every group needs at least one of its keys held."""
    allowed_keys: frozenset[int]
    """Keys that may be down without counting as 'some other key'."""

    @property
    def watched_keys(self) -> frozenset[int]:
        return self.allowed_keys


def parse_hotkey(hotkey_text: str) -> ParsedHotkey:
    names = [part.strip().lower() for part in hotkey_text.split("+")]
    if not names or any(not name for name in names):
        raise HotkeyParseError(f"Invalid hotkey {hotkey_text!r}. Use names joined with '+', e.g. ctrl+alt")
    groups: list[frozenset[int]] = []
    allowed: set[int] = set()
    seen_names: set[str] = set()
    for raw_name in names:
        name = KEY_NAME_ALIASES.get(raw_name, raw_name)
        if name not in KEY_NAMES:
            raise HotkeyParseError(f"Unknown key {raw_name!r} in hotkey. Known keys: {', '.join(sorted(KEY_NAMES))}")
        if name in seen_names:
            raise HotkeyParseError(f"Key {raw_name!r} appears twice in hotkey {hotkey_text!r}")
        seen_names.add(name)
        satisfying_keys, companion_keys = KEY_NAMES[name]
        groups.append(satisfying_keys)
        allowed |= satisfying_keys | companion_keys
    return ParsedHotkey(text=hotkey_text, required_key_groups=tuple(groups), allowed_keys=frozenset(allowed))


class PushToTalkEvent(Enum):
    PRESSED = auto()
    RELEASED = auto()
    CANCELLED = auto()


class _State(Enum):
    IDLE = auto()
    ARMING = auto()
    ACTIVE = auto()
    BLOCKED = auto()


class PushToTalkStateMachine:
    """Pure logic: feed it the set of keys currently down and the time; it says what happened."""

    def __init__(self, hotkey: ParsedHotkey, activation_delay_seconds: float = 0.15) -> None:
        self._hotkey = hotkey
        self._activation_delay_seconds = activation_delay_seconds
        self._state = _State.IDLE
        self._arming_started_at = 0.0

    @property
    def is_active(self) -> bool:
        return self._state is _State.ACTIVE

    def reset(self) -> None:
        """Forget the current hold; nothing fires again until the hotkey is fully released."""
        self._state = _State.BLOCKED

    def update(self, pressed_keys: frozenset[int], now: float) -> PushToTalkEvent | None:
        relevant_keys = pressed_keys - IGNORED_VIRTUAL_KEYS
        combo_down = all(group & relevant_keys for group in self._hotkey.required_key_groups)
        has_extra_key = bool(relevant_keys - self._hotkey.allowed_keys)
        any_hotkey_key_down = bool(relevant_keys & self._hotkey.allowed_keys)

        if self._state is _State.IDLE:
            if combo_down and has_extra_key:
                self._state = _State.BLOCKED
            elif combo_down:
                self._state = _State.ARMING
                self._arming_started_at = now
                return self._activate_if_held_long_enough(now)
            return None

        if self._state is _State.ARMING:
            if not combo_down:
                self._state = _State.IDLE
                return None
            if has_extra_key:
                self._state = _State.BLOCKED
                return None
            return self._activate_if_held_long_enough(now)

        if self._state is _State.ACTIVE:
            if has_extra_key:
                self._state = _State.BLOCKED
                return PushToTalkEvent.CANCELLED
            if not combo_down:
                self._state = _State.IDLE
                return PushToTalkEvent.RELEASED
            return None

        # BLOCKED: wait until every hotkey key is up.
        if not any_hotkey_key_down:
            self._state = _State.IDLE
        return None

    def _activate_if_held_long_enough(self, now: float) -> PushToTalkEvent | None:
        if now - self._arming_started_at >= self._activation_delay_seconds:
            self._state = _State.ACTIVE
            return PushToTalkEvent.PRESSED
        return None


class HotkeyPoller:
    """Background thread polling GetAsyncKeyState and reporting push-to-talk events via a callback.

    Cheap path: while no hotkey key is down only the hotkey's own keys are polled. A full keyboard scan
    (to spot 'some other key') happens only while part of the combo is held.
    """

    POLL_INTERVAL_SECONDS = 0.015

    def __init__(
        self,
        hotkey: ParsedHotkey,
        on_event: Callable[[PushToTalkEvent], None],
        activation_delay_seconds: float = 0.15,
    ) -> None:
        import ctypes

        self._get_async_key_state = ctypes.windll.user32.GetAsyncKeyState
        self._get_async_key_state.restype = ctypes.c_short
        self._get_async_key_state.argtypes = [ctypes.c_int]
        self._hotkey = hotkey
        self._on_event = on_event
        self._state_machine = PushToTalkStateMachine(hotkey, activation_delay_seconds)
        self._stop_requested = threading.Event()
        self._thread = threading.Thread(target=self._run, name="clicky-hotkey", daemon=True)

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop_requested.set()
        if self._thread.is_alive():
            self._thread.join(timeout=1.0)

    def _is_down(self, virtual_key: int) -> bool:
        return bool(self._get_async_key_state(virtual_key) & 0x8000)

    def _read_pressed_keys(self) -> frozenset[int]:
        hotkey_keys_down = {key for key in self._hotkey.watched_keys if self._is_down(key)}
        if not hotkey_keys_down:
            return frozenset()
        return frozenset(key for key in range(1, 255) if self._is_down(key))

    def _run(self) -> None:
        while not self._stop_requested.is_set():
            try:
                event = self._state_machine.update(self._read_pressed_keys(), time.monotonic())
                if event is not None:
                    self._on_event(event)
            except Exception:
                logger.exception("Hotkey polling failed")
            self._stop_requested.wait(self.POLL_INTERVAL_SECONDS)
