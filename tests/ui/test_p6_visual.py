"""Task P6 测试：视觉精修（呼吸光带 / 荧光笔框选 / 卡片阴影 / 等宽数字 / token 修正）"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest

import app.ui.windows.base_window as base_window_module
from app.ui.animation_manager import AnimationManager
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.engine_status_band import EngineStatusBand
from app.ui.widgets.pdf_canvas import PdfCanvas


class FakeEngine:
    engine_name = "gguf"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True

    def unload(self):
        pass


def _make_config(engine="gguf") -> dict:
    return {
        "app": {"name": "PDFOCR", "window_size": [1400, 900], "theme": "dark"},
        "ocr": {"engine": engine, "gguf": {"device": "gpu"}},
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
    }


def _destroy(w):
    QTest.qWait(600)
    w.deleteLater()
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)


class TestEngineStatusBandBreathing:
    @pytest.fixture(autouse=True)
    def _restore_animations(self):
        before = AnimationManager.is_enabled()
        yield
        AnimationManager.set_enabled(before)

    def test_breathes_while_initializing(self, qapp):
        AnimationManager.set_enabled(True)
        band = EngineStatusBand()
        assert band._breath_timer.isActive()
        phase0 = band._phase
        QTest.qWait(200)
        assert band._phase != phase0
        band.set_status('ready')
        assert not band._breath_timer.isActive()
        band.set_status('error')
        assert not band._breath_timer.isActive()
        _destroy(band)

    def test_static_when_animations_disabled(self, qapp):
        AnimationManager.set_enabled(False)
        band = EngineStatusBand()
        assert not band._breath_timer.isActive()
        QTest.qWait(200)
        assert band._phase == 0.0
        _destroy(band)

    def test_initializing_still_static_after_disabled_toggle(self, qapp):
        AnimationManager.set_enabled(True)
        band = EngineStatusBand()
        assert band._breath_timer.isActive()
        AnimationManager.set_enabled(False)
        QTest.qWait(200)  # 下一个 tick 检测到禁用 → 停止
        assert not band._breath_timer.isActive()
        _destroy(band)


class TestRapidHighlighter:
    def test_rapid_region_uses_highlighter_style(self, qapp):
        from PIL import Image
        from app.models.region import Region
        ThemeManager.set_design('rapid')
        try:
            canvas = PdfCanvas()
            canvas.load_image(Image.new("RGB", (120, 80), (255, 255, 255)))
            region = Region(id="r1", field_name="f", x=0.1, y=0.2, w=0.3, h=0.4)
            canvas.update_regions([region])
            item = canvas.region_items["r1"]
            assert item.pen().color().name() == "#f5c518"
            brush = item.brush().color()
            assert brush.alpha() == 45
            assert (brush.red(), brush.green()) == (255, 213)
            _destroy(canvas)
        finally:
            ThemeManager.set_design('default')

    def test_default_design_keeps_region_color(self, qapp):
        from PIL import Image
        from app.models.region import Region
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
        canvas = PdfCanvas()
        canvas.load_image(Image.new("RGB", (120, 80), (255, 255, 255)))
        region = Region(id="r1", field_name="f", x=0.1, y=0.2, w=0.3, h=0.4)
        canvas.update_regions([region])
        item = canvas.region_items["r1"]
        assert item.pen().color().name() == "#ff5733"  # Region 默认色
        _destroy(canvas)


class TestRapidCardShadow:
    def test_panels_have_shadow(self, qapp, monkeypatch):
        monkeypatch.setattr(base_window_module, "get_ocr_engine",
                            lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        from app.ui.windows.rapid_main_window import RapidMainWindow
        w = RapidMainWindow(_make_config(engine="rapidocr"))
        assert w.left_panel.graphicsEffect() is not None
        assert w.right_panel.graphicsEffect() is not None
        _destroy(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')


class TestMonoDigits:
    def test_gguf_stats_use_mono_font(self, qapp, monkeypatch):
        monkeypatch.setattr(base_window_module, "get_ocr_engine",
                            lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        from app.ui.windows.gguf_main_window import GgufMainWindow
        w = GgufMainWindow(_make_config())
        family = w.stat_total.font().family()
        assert "Consolas" in family or "Courier" in family
        kfamily = w.keyword_page.stats_label.font().family()
        assert "Consolas" in kfamily or "Courier" in kfamily
        _destroy(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')

    def test_rapid_stats_keep_default_font(self, qapp, monkeypatch):
        monkeypatch.setattr(base_window_module, "get_ocr_engine",
                            lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        from app.ui.windows.rapid_main_window import RapidMainWindow
        w = RapidMainWindow(_make_config(engine="rapidocr"))
        family = w.stat_total.font().family()
        assert "Consolas" not in family and "Courier" not in family
        _destroy(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')


class TestTokenFix:
    def test_rapid_accent_alt_readable_on_light(self, qapp):
        ThemeManager.set_design('rapid')
        try:
            assert ThemeManager.get_color('accent_alt') == '#14B8A6'
        finally:
            ThemeManager.set_design('default')
