from PySide6.QtGui import QFont, QFontInfo


def test_bundled_fonts_load(qt_app):
    from clicky.fonts import load_fonts

    families = load_fonts()
    assert "Inter" in families
    assert "Geist Mono" in families
    assert load_fonts() == families  # idempotent


def test_ui_and_mono_fonts_resolve_to_the_bundled_families(qt_app):
    from clicky.fonts import mono_font, ui_font

    ui = ui_font(18, QFont.Weight.DemiBold)
    mono = mono_font(14)
    assert QFontInfo(ui).family() == "Inter"
    assert ui.pixelSize() == 18
    assert ui.weight() == QFont.Weight.DemiBold
    assert QFontInfo(mono).family() == "Geist Mono"


def test_card_uses_inter_for_text_and_geist_mono_for_formulas(qt_app):
    from clicky.lesson_card import LessonCard

    card = LessonCard()
    try:
        assert QFontInfo(card._fonts["heading"]).family() == "Inter"
        assert QFontInfo(card._fonts["note"]).family() == "Inter"
        assert QFontInfo(card._fonts["formula"]).family() == "Geist Mono"
        assert QFontInfo(card._title_font).family() == "Inter"
    finally:
        card.close()


def test_scene_ticks_are_monospaced_and_labels_inter(qt_app):
    from clicky.scene_painter import ScenePainter

    painter = ScenePainter()
    assert QFontInfo(painter._tick_font).family() == "Geist Mono"
    assert QFontInfo(painter._label_font).family() == "Inter"


def test_no_handwriting_fonts_left_in_the_ui(qt_app):
    import clicky.handwriting as handwriting

    assert not hasattr(handwriting, "handwriting_font")
    assert not hasattr(handwriting, "_handwriting_font")
