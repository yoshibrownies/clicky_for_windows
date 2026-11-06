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


def test_chips_place_themselves_using_the_screen_under_the_card(qt_app, monkeypatch):
    from clicky import followup_chips

    class TallScreen:
        def availableGeometry(self):  # noqa: N802 (mirrors Qt)
            return QRect(2000, 0, 1000, 2000)

    monkeypatch.setattr(followup_chips, "_screen_for", lambda rect: TallScreen(), raising=False)
    chips = FollowUpChips()
    chips.show = lambda: None
    try:
        below = QRect(2500, 56, 420, 700)  # on the 800 px test screen the chips would not fit below
        chips.show_options(["Go deeper", "Try one"], below=below)
        assert chips.y() == below.bottom() + 8  # plenty of room under the card on that screen
    finally:
        chips.close()


def test_chips_can_hide_themselves_after_a_while(qt_app):
    import time

    from PySide6.QtWidgets import QApplication

    chips = FollowUpChips()
    try:
        chips.show_options(["Go deeper"], below=QRect(0, 0, 400, 300), hide_after=0.1)
        assert chips.isVisible()
        deadline = time.monotonic() + 0.5
        while time.monotonic() < deadline:
            QApplication.processEvents()
            time.sleep(0.005)
        assert not chips.isVisible()
    finally:
        chips.close()
