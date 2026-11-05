"""Screenshot sizing, labelling and coordinate mapping.

The pure helpers at the top are what the tests cover. `capture_all_screens` at the bottom needs a running
QGuiApplication and must be called on the GUI thread.

Coordinate model: Claude answers in the pixel space of the (downscaled) screenshot it was sent. Qt places
windows in *logical* coordinates (physical pixels divided by the monitor's scale factor). Mapping by
proportion, x / image_width * logical_width, is correct at any DPI scale and needs no physical sizes.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from PySide6.QtGui import QScreen

MAX_SCREENSHOT_LONG_EDGE = 1600
JPEG_QUALITY = 80


@dataclass(frozen=True)
class ScreenGeometry:
    """A monitor's rectangle in Qt logical (global) coordinates."""

    x: int
    y: int
    width: int
    height: int

    def contains(self, point_x: int, point_y: int) -> bool:
        return self.x <= point_x < self.x + self.width and self.y <= point_y < self.y + self.height


@dataclass(frozen=True)
class ScreenCapture:
    jpeg_bytes: bytes
    label: str
    image_width: int
    image_height: int
    geometry: ScreenGeometry
    is_cursor_screen: bool


def fit_within(width: int, height: int, max_long_edge: int) -> tuple[int, int]:
    """Scale (width, height) down so the long edge is at most max_long_edge. Never scales up."""
    long_edge = max(width, height)
    if long_edge <= max_long_edge:
        return width, height
    scale = max_long_edge / long_edge
    return max(1, round(width * scale)), max(1, round(height * scale))


def order_screens_cursor_first[ItemType](screens: Sequence[ItemType], cursor_index: int) -> list[ItemType]:
    """Put the screen with the mouse cursor first, keeping the others in their original order."""
    ordered = list(screens)
    cursor_screen = ordered.pop(cursor_index)
    return [cursor_screen, *ordered]


def build_screen_label(index: int, count: int, is_cursor_screen: bool, width: int, height: int) -> str:
    """Text placed after each screenshot, worded like the macOS app's labels so the prompt still applies."""
    if count == 1:
        description = "user's screen (cursor is here)"
    elif is_cursor_screen:
        description = f"screen {index + 1} of {count} — cursor is on this screen (primary focus)"
    else:
        description = f"screen {index + 1} of {count} — secondary screen"
    return f"{description} (image dimensions: {width}x{height} pixels)"


def map_image_point_to_screen(
    image_point: tuple[int, int], image_size: tuple[int, int], geometry: ScreenGeometry
) -> tuple[int, int]:
    """Convert a pixel in a screenshot to a global logical point on the monitor it was taken from."""
    image_width, image_height = image_size
    if image_width <= 0 or image_height <= 0:
        raise ValueError(f"image size must be positive, got {image_size}")

    point_x, point_y = image_point
    local_x = round(point_x / image_width * geometry.width)
    local_y = round(point_y / image_height * geometry.height)
    local_x = min(max(local_x, 0), geometry.width - 1)
    local_y = min(max(local_y, 0), geometry.height - 1)
    return geometry.x + local_x, geometry.y + local_y


def geometry_of(screen: QScreen) -> ScreenGeometry:
    rect = screen.geometry()
    return ScreenGeometry(x=rect.x(), y=rect.y(), width=rect.width(), height=rect.height())


def capture_all_screens() -> list[ScreenCapture]:
    """Grab every monitor as a labelled JPEG, cursor screen first. GUI thread only."""
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice, Qt
    from PySide6.QtGui import QCursor, QGuiApplication

    screens = QGuiApplication.screens()
    if not screens:
        return []

    cursor_position = QCursor.pos()
    cursor_index = 0
    for screen_index, screen in enumerate(screens):
        if screen.geometry().contains(cursor_position):
            cursor_index = screen_index
            break

    ordered_screens = order_screens_cursor_first(screens, cursor_index)
    captures: list[ScreenCapture] = []
    for display_index, screen in enumerate(ordered_screens):
        # grabWindow(0) grabs the whole monitor at physical resolution. Our overlay windows are excluded
        # from capture (see overlay.py), so the buddy never shows up in what Claude sees.
        pixmap = screen.grabWindow(0)
        if pixmap.isNull():
            continue
        target_width, target_height = fit_within(pixmap.width(), pixmap.height(), MAX_SCREENSHOT_LONG_EDGE)
        if (target_width, target_height) != (pixmap.width(), pixmap.height()):
            pixmap = pixmap.scaled(
                target_width,
                target_height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )

        jpeg_byte_array = QByteArray()
        buffer = QBuffer(jpeg_byte_array)
        buffer.open(QIODevice.OpenModeFlag.WriteOnly)
        pixmap.save(buffer, "JPEG", JPEG_QUALITY)
        buffer.close()

        is_cursor_screen = display_index == 0
        captures.append(
            ScreenCapture(
                jpeg_bytes=bytes(jpeg_byte_array.data()),
                label=build_screen_label(
                    display_index, len(ordered_screens), is_cursor_screen, pixmap.width(), pixmap.height()
                ),
                image_width=pixmap.width(),
                image_height=pixmap.height(),
                geometry=geometry_of(screen),
                is_cursor_screen=is_cursor_screen,
            )
        )
    return captures
