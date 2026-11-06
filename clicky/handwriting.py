"""Text helpers shared by the lesson card: word wrap and typing progress (fonts live in fonts.py)."""

from __future__ import annotations

from collections.abc import Callable


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
