"""PaddleVlSettingsForm / PaddleVlSettingsPage / 主窗口动态设置页 测试"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QSignalSpy
from PyQt6.QtTest import QTest

import app.ui.windows.base_window as base_window_module
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.paddle_vl_settings_page import (
    PaddleVlSettingsForm, PaddleVlSettingsPage,
)
from app.ui.widgets.gguf_settings_page import GgufSettingsPage
from app.ui.windows.gguf_main_window import GgufMainWindow


class FakeEngine:
    engine_name = "paddle_vl"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True

    def unload(self):
        pass


def _make_config() -> dict:
    return {
        "app": {"name": "PDFOCR", "window_size": [1400, 900], "theme": "dark"},
        "appearance": {"theme": "dark", "animations_enabled": True},
        "ocr": {
            "engine": "paddle_vl",
            "paddle_vl": {
                "block_spotting": 1,
                "max_new_tokens": 5120,
                "repetition_penalty": 1.2,
                "vision_sdpa": 1,
                "spotting_max_pixels": 1048576,
            },
        },
    }


def _destroy(w):
    w.deleteLater()
    import time
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)


class TestPaddleVlSettingsForm:
    def test_load_patch_roundtrip(self, qapp):
        """表单加载配置 → get_config_patch 还原全部受管键"""
        form = PaddleVlSettingsForm(_make_config())
        patch = form.get_config_patch()
        patch_vl = patch["ocr"]["paddle_vl"]
        expected = _make_config()["ocr"]["paddle_vl"]
        for key, value in expected.items():
            assert patch_vl[key] == value, key
        _destroy(form)

    def test_defaults_when_config_missing(self, qapp):
        """config 无 paddle_vl 段 → 默认值（开关关、4096/1.1/1/1048576）"""
        form = PaddleVlSettingsForm({"ocr": {"engine": "paddle_vl"}})
        patch = form.get_config_patch()["ocr"]["paddle_vl"]
        assert patch["block_spotting"] == 0
        assert patch["max_new_tokens"] == 4096
        assert patch["repetition_penalty"] == 1.1
        assert patch["vision_sdpa"] == 1
        assert patch["spotting_max_pixels"] == 1048576
        _destroy(form)

    def test_toggle_and_edit_reflected(self, qapp):
        form = PaddleVlSettingsForm(_make_config())
        form.sw_block_spotting.setChecked(False)
        form.ed_max_tokens.setText("2048")
        form.ed_repetition_penalty.setText("0")
        form.sw_vision_sdpa.setChecked(False)
        patch = form.get_config_patch()["ocr"]["paddle_vl"]
        assert patch["block_spotting"] == 0
        assert patch["max_new_tokens"] == 2048
        assert patch["repetition_penalty"] == 0.0
        assert patch["vision_sdpa"] == 0
        _destroy(form)

    def test_invalid_input_falls_back(self, qapp):
        form = PaddleVlSettingsForm(_make_config())
        form.ed_max_tokens.setText("abc")
        form.ed_repetition_penalty.setText("xyz")
        patch = form.get_config_patch()["ocr"]["paddle_vl"]
        assert patch["max_new_tokens"] == 4096  # 兜底默认
        assert patch["repetition_penalty"] == 1.1
        _destroy(form)

    def test_reset_defaults(self, qapp):
        form = PaddleVlSettingsForm(_make_config())
        form._on_default()
        patch = form.get_config_patch()["ocr"]["paddle_vl"]
        assert patch["block_spotting"] == 0
        assert patch["max_new_tokens"] == 4096
        assert patch["repetition_penalty"] == 1.1
        assert patch["vision_sdpa"] == 1
        assert patch["spotting_max_pixels"] == 1048576
        _destroy(form)


class TestPaddleVlSettingsPage:
    def test_signals_emit_patch(self, qapp):
        page = PaddleVlSettingsPage(_make_config())
        spy_save = QSignalSpy(page.save_requested)
        spy_restart = QSignalSpy(page.restart_requested)
        page.btn_save.click()
        page.btn_restart.click()
        assert len(spy_save) == 1
        assert len(spy_restart) == 1
        patch = spy_save[0][0]
        assert "paddle_vl" in patch["ocr"]
        _destroy(page)

    def test_reset_button_restores_defaults(self, qapp):
        page = PaddleVlSettingsPage(_make_config())
        page.btn_reset.click()
        patch = page.get_config_patch()["ocr"]["paddle_vl"]
        assert patch["block_spotting"] == 0
        assert patch["max_new_tokens"] == 4096
        _destroy(page)


@pytest.fixture
def engine_window(qapp, monkeypatch):
    monkeypatch.setattr(base_window_module, "get_ocr_engine",
                        lambda config: FakeEngine())
    from app.ui.widgets.cancel_result_dialog import CancelResultDialog
    monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
    w = GgufMainWindow(_make_config())
    yield w
    _destroy(w)
    ThemeManager.set_design('default')
    ThemeManager.set_theme('dark')


class TestDynamicSettingsPage:
    def test_paddle_vl_session_uses_paddle_settings(self, engine_window):
        """paddle_vl 会话：模型设置页为 PaddleVlSettingsPage"""
        w = engine_window
        assert w.engine_type == "paddle_vl"
        assert isinstance(w.settings_page, PaddleVlSettingsPage)

    def test_gguf_session_uses_gguf_settings(self, qapp, monkeypatch):
        """gguf 会话：模型设置页仍为 GgufSettingsPage（现状不变）"""
        cfg = _make_config()
        cfg["ocr"]["engine"] = "gguf"
        monkeypatch.setattr(base_window_module, "get_ocr_engine",
                            lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        w = GgufMainWindow(cfg)
        assert w.engine_type == "gguf"
        assert isinstance(w.settings_page, GgufSettingsPage)
        _destroy(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')
