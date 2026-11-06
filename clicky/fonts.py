"""Clicky's typefaces: Inter for headlines and body text, Geist Mono for technical text (formulas, numbers, code).

Both are bundled in clicky/fonts/ (SIL Open Font License, see the *-OFL.txt files there) and registered with Qt on
first use, so they work on any PC without installing anything. If loading ever fails, Segoe UI / Consolas stand in.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtGui import QFont, QFontDatabase

logger = logging.getLogger(__name__)

FONT_DIRECTORY = Path(__file__).parent / "fonts"
FONT_FILES = ("Inter[opsz,wght].ttf", "GeistMono[wght].ttf")
UI_FAMILY = "Inter"
MONO_FAMILY = "Geist Mono"
UI_FALLBACK = "Segoe UI"
MONO_FALLBACK = "Consolas"

_loaded_families: tuple[str, ...] | None = None


def load_fonts() -> tuple[str, ...]:
    """Register the bundled fonts once (needs a QGuiApplication). Returns the family names that loaded."""
    global _loaded_families
    if _loaded_families is not None:
        return _loaded_families
    families: list[str] = []
    for file_name in FONT_FILES:
        font_id = QFontDatabase.addApplicationFont(str(FONT_DIRECTORY / file_name))
        if font_id < 0:
            logger.warning("Couldn't load the bundled font %s; using a system font instead", file_name)
            continue
        families.extend(QFontDatabase.applicationFontFamilies(font_id))
    _loaded_families = tuple(families)
    return _loaded_families


def _font(family: str, fallback: str, pixel_size: int, weight: QFont.Weight) -> QFont:
    font = QFont(family if family in load_fonts() else fallback)
    font.setPixelSize(max(1, int(pixel_size)))
    font.setWeight(weight)
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def ui_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Inter: headlines, notes, buttons, labels."""
    return _font(UI_FAMILY, UI_FALLBACK, pixel_size, weight)


def mono_font(pixel_size: int, weight: QFont.Weight = QFont.Weight.Normal) -> QFont:
    """Geist Mono: formulas, axis numbers, code."""
    return _font(MONO_FAMILY, MONO_FALLBACK, pixel_size, weight)
