"""Task P5 测试：GgufSettingsForm / GgufSettingsPage / check_llama_health / 窗口处理器"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest

import app.ui.windows.base_window as base_window_module
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.gguf_settings_page import (
    GgufSettingsForm, GgufSettingsPage, check_llama_health,
)
from app.ui.windows.gguf_main_window import GgufMainWindow


class FakeEngine:
    engine_name = "gguf"
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
            "engine": "gguf",
            "gguf": {
                "server_path": r"C:\\llama\\llama-server.exe",
                "model_path": r"C:\\models\\ocr.gguf",
                "mmproj_path": r"C:\\models\\mmproj.gguf",
                "host": "127.0.0.1",
                "port": 8080,
                "device": "gpu",
                "n_gpu_layers": 99,
                "mmproj_offload": False,
                "max_tokens": 512,
                "temperature": 0.2,
                "idle_unload_seconds": 300,
                "auxiliary_parsing": {
                    "header": True, "footer": False, "page_number": True,
                    "footnote": False, "margin_text": False,
                    "header_image": False, "footer_image": False,
                },
                "model_params": {
                    "orientation_correction": False,
                    "distortion_correction": False,
                    "layout_analysis": True,
                    "chart_recognition": True,
                    "seal_recognition": True,
                    "image_text_recognition": True,
                    "cross_page_table_merge": True,
                    "heading_level_recognition": True,
                },
                "layout_geometry": "auto",
                "prompt_type": "table",
                "repetition_penalty": 1.0,
                "stability": 0.0,
                "confidence_threshold": 0.8,
                "min_pixels": 146432,
                "max_pixels": 2822144,
                "nms_postprocess": True,
            },
        },
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
    }


def _destroy(w):
    QTest.qWait(200)
    w.deleteLater()
    import time
    deadline = time.monotonic() + 1.5
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)


class TestGgufSettingsForm:
    def test_load_patch_roundtrip(self, qapp):
        """表单加载配置 → get_config_patch 还原全部受管键"""
        form = GgufSettingsForm(_make_config(), show_theme_options=False)
        patch_gguf = form.get_config_patch()["ocr"]["gguf"]
        expected = _make_config()["ocr"]["gguf"]
        for key, value in expected.items():
            assert patch_gguf[key] == value, key
        _destroy(form)

    def test_toggle_and_edit_reflected(self, qapp):
        form = GgufSettingsForm(_make_config(), show_theme_options=False)
        form.sw_nms.setChecked(False)
        form.slider_confidence["slider"].setValue(50)  # 0.5
        form.ed_port.setText("9999")
        form.rb_device_cpu.setChecked(True)
        form.sw_layout["switch"].setChecked(False)
        patch = form.get_config_patch()["ocr"]["gguf"]
        assert patch["nms_postprocess"] is False
        assert patch["confidence_threshold"] == pytest.approx(0.5)
        assert patch["port"] == 9999
        assert patch["device"] == "cpu"
        assert patch["model_params"]["layout_analysis"] is False
        _destroy(form)

    def test_hide_theme_options(self, qapp):
        """GGUF 页：无主题三单选，patch 不含 theme"""
        form = GgufSettingsForm(_make_config(), show_theme_options=False)
        assert not hasattr(form, 'rb_theme_light')
        assert not hasattr(form, 'bg_theme')
        patch = form.get_config_patch()
        assert 'theme' not in patch["appearance"]
        assert "animations_enabled" in patch["appearance"]
        _destroy(form)

    def test_theme_options_kept_for_wrapper(self, qapp):
        """旧对话框兼容：默认保留主题三单选"""
        form = GgufSettingsForm(_make_config(), show_theme_options=True)
        assert hasattr(form, 'rb_theme_dark')
        assert form.rb_theme_dark.isChecked()
        assert form.get_config_patch()["appearance"]["theme"] == "dark"
        _destroy(form)

    def test_default_resets_service_fields(self, qapp):
        form = GgufSettingsForm(_make_config(), show_theme_options=False)
        form.ed_port.setText("1")
        form.rb_device_cpu.setChecked(True)
        form._on_default()
        assert form.ed_port.text() == "8080"
        assert form.rb_device_gpu.isChecked()
        _destroy(form)


class TestGgufSettingsPage:
    def test_page_builds_and_exposes_form(self, qapp):
        page = GgufSettingsPage(_make_config())
        assert page.form is not None
        assert page.btn_save is not None
        assert page.btn_restart is not None
        assert page.btn_test is not None
        _destroy(page)

    def test_page_signals_emit_patch(self, qapp):
        page = GgufSettingsPage(_make_config())
        saved = []
        restarted = []
        tested = []
        page.save_requested.connect(saved.append)
        page.restart_requested.connect(restarted.append)
        page.test_connection_requested.connect(lambda: tested.append(True))

        page.btn_save.click()
        page.btn_restart.click()
        page.btn_test.click()

        assert len(saved) == 1 and "ocr" in saved[0]
        assert len(restarted) == 1 and "ocr" in restarted[0]
        assert tested == [True]
        _destroy(page)


class TestHealthCheck:
    def test_ok(self):
        class Resp:
            status_code = 200

        def fake_get(url, timeout=5):
            assert "127.0.0.1:8080" in url
            return Resp()

        ok, msg = check_llama_health("127.0.0.1", 8080, getter=fake_get)
        assert ok is True
        assert "正常" in msg

    def test_http_error(self):
        class Resp:
            status_code = 503

        ok, msg = check_llama_health("127.0.0.1", 8080,
                                     getter=lambda *a, **k: Resp())
        assert ok is False
        assert "503" in msg

    def test_connection_error(self):
        def boom(*a, **k):
            raise ConnectionRefusedError("refused")

        ok, msg = check_llama_health("127.0.0.1", 8080, getter=boom)
        assert ok is False
        assert "refused" in msg


class TestWindowHandlers:
    @pytest.fixture
    def window(self, qapp, monkeypatch):
        monkeypatch.setattr(base_window_module, "get_ocr_engine",
                            lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        # 关键隔离：绝不把测试 fixture 配置写回真实 app/config.yaml
        # （此前 _on_settings_restart 未打桩 save_config，导致全量测试
        #   每次把 C:\llama 旧路径回写进开发配置）
        monkeypatch.setattr("app.utils.config_loader.save_config",
                            lambda config: None)
        w = GgufMainWindow(_make_config())
        yield w
        _destroy(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')

    def test_save_handler_merges_and_saves(self, window, monkeypatch):
        calls = []
        monkeypatch.setattr(
            "app.utils.config_loader.save_config",
            lambda config: calls.append(dict(config)))
        window._on_settings_save({"ocr": {"gguf": {"port": 9999}}})
        assert window.config["ocr"]["gguf"]["port"] == 9999
        assert len(calls) == 1

    def test_restart_device_change_uses_program_restart(self, window, monkeypatch):
        restarts = []
        monkeypatch.setattr(window, "_restart_with_engine",
                            lambda engine, device: restarts.append((engine, device)))
        window._on_settings_restart({"ocr": {"gguf": {"device": "cpu"}}})
        assert restarts == [("gguf", "cpu")]
        assert window.config["ocr"]["gguf"]["device"] == "cpu"

    def test_restart_same_device_reinits_in_process(self, window, monkeypatch):
        reinits = []
        monkeypatch.setattr(window, "_reinit_engine_in_process",
                            lambda: reinits.append(True))
        window._on_settings_restart({"ocr": {"gguf": {"port": 9999}}})
        assert reinits == [True]

    def test_test_connection_smoke(self, window, monkeypatch, qapp):
        monkeypatch.setattr(
            "app.ui.widgets.gguf_settings_page.check_llama_health",
            lambda host, port: (True, "ok"))
        window._on_settings_test_connection()
        QTest.qWait(300)  # 后台线程 + 定时回调，不崩即可
