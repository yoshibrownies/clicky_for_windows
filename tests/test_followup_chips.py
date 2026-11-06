from PySide6.QtCore import QRect, Qt

from clicky.followup_chips import FollowUpChips


def test_chips_show_options_and_emit_the_clicked_one(qt_app):
    chips = FollowUpChips()
    chips.show = lambda: None
    chosen = []
    chips.chosen.connect(chosen.append)
    try:
        chips.show_options(
            ["Explain terminal speed", "Try a calculation", "", "x" * 80], below=QRect(1000, 100, 420, 500)
        )
        assert chips.options() == ["Explain terminal speed", "Try a calculation", "x" * 40]  # long text is cut to 40
        chips.click_option(1)
        assert chosen == ["Try a calculation"]
        assert chips.options() == []
    finally:
        chips.close()


def test_chips_never_take_keyboard_focus_and_hide(qt_app):
    chips = FollowUpChips()
    try:
        flags = chips.windowFlags()
        assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
        assert chips.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        assert not flags & Qt.WindowType.WindowTransparentForInput  # the one clickable part of Clicky
        chips.show_options(["Go deeper"], below=QRect(0, 0, 400, 300))
        assert chips.isVisible()
        chips.hide_options()
        assert not chips.isVisible()
        chips.show_options([], below=QRect(0, 0, 400, 300))
        assert not chips.isVisible()
    finally:
        chips.close()
