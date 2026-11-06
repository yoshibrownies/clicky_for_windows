"""Handwritten-text helpers shared by Clicky's paper surfaces: font choice, word wrap, typing progress."""

from __future__ import annotations

from collections.abc import Callable

from PySide6.QtGui import QFont, QFontDatabase

HANDWRITING_FONTS = ("Ink Free", "Segoe Print", "Comic Sans MS")


def wrap_text(text: str, measure: Callable[[str], float], max_width: float) -> list[str]:
    """Greedy word wrap; words longer than a line are split."""
    lines: list[str] = []
    current = ""
    for word in text.split():
        candidate = f"{current} {word}".strip()
        if measure(candidate) <= max_width:
            current = candidate
            continue
        if current:
            lines.append(current)
        current = ""
        while measure(word) > max_width and len(word) > 1:
            cut = len(word)
            while cut > 1 and measure(word[:cut]) > max_width:
                cut -= 1
            lines.append(word[:cut])
            word = word[cut:]
        current = word
    if current:
        lines.append(current)
    return lines


def typed_characters(elapsed_seconds: float, characters_per_second: float, total_characters: int) -> int:
    if elapsed_seconds <= 0:
        return 0
    return min(total_characters, int(elapsed_seconds * characters_per_second))


def handwriting_font(pixel_size: int) -> QFont:
    available = set(QFontDatabase.families())
    family = next((name for name in HANDWRITING_FONTS if name in available), "Segoe UI")
    font = QFont(family)
    font.setPixelSize(pixel_size)
    return font


# Kept for existing imports.
_handwriting_font = handwriting_font
