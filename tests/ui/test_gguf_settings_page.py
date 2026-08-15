"""Task P5 测试：GgufSettingsForm / GgufSettingsPage / check_llama_health / 窗口处理器"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMessageBox

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
                "timeout_seconds": 120,
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
                "match_iou_threshold": 0.5,
                "match_neighbor_radius": 50,
            },
        },
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2, "retry_times": 2},
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
        form = GgufSettingsForm(_make_config())
        patch = form.get_config_patch()
        patch_gguf = patch["ocr"]["gguf"]
        expected = _make_config()["ocr"]["gguf"]
        # 字段匹配滑块已移除（仅模板批量 FieldMatcher 消费，GGUF 流程无此概念），
        # config 键保留兼容但不进 patch
        expected.pop("match_iou_threshold", None)
        expected.pop("match_neighbor_radius", None)
        for key, value in expected.items():
            assert patch_gguf[key] == value, key
        assert "match_iou_threshold" not in patch_gguf
        assert "match_neighbor_radius" not in patch_gguf
        assert patch["pdf"]["render_dpi"] == 200
        assert patch["batch"]["max_workers"] == 2
        assert patch["batch"]["retry_times"] == 2
        assert patch["export"]["include_confidence"] is True
        _destroy(form)

    def test_toggle_and_edit_reflected(self, qapp):
        form = GgufSettingsForm(_make_config())
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

    def test_no_theme_options(self, qapp):
        """设置表单已移除主题三单选，patch 不含 theme"""
        form = GgufSettingsForm(_make_config())
        assert not hasattr(form, 'rb_theme_light')
        assert not hasattr(form, 'bg_theme')
        patch = form.get_config_patch()
        assert 'theme' not in patch["appearance"]
        assert "animations_enabled" in patch["appearance"]
        _destroy(form)

    def test_no_idle_unload_field(self, qapp):
        """空闲卸载秒数已移除（引擎不消费的死键），行序回归：timeout 在 mmproj 之前"""
        form = GgufSettingsForm(_make_config())
        assert not hasattr(form, 'ed_idle_unload')
        patch = form.get_config_patch()["ocr"]["gguf"]
        assert "idle_unload_seconds" not in patch
        assert patch["timeout_seconds"] == 120
        _destroy(form)

    def test_matcher_sliders_removed(self, qapp):
        """字段匹配滑块已移除（仅模板批量 FieldMatcher 消费，GGUF 流程无此概念）"""
        form = GgufSettingsForm(_make_config())
        assert not hasattr(form, 'slider_iou')
        assert not hasattr(form, 'slider_neighbor')
        _destroy(form)

    def test_dead_code_removed(self, qapp):
        """表单死代码已清理：settings_applied 信号 / _original_config / apply_animations"""
        from app.ui.widgets.gguf_settings_page import GgufSettingsForm as Cls
        assert not hasattr(Cls, 'settings_applied')
        form = Cls(_make_config())
        assert not hasattr(form, '_original_config')
        assert not hasattr(form, 'apply_animations')
        _destroy(form)

    def test_animations_switch_applies_immediately(self, qapp, monkeypatch):
        """禁用动画开关即时生效（不再只写配置）"""
        calls = []
        monkeypatch.setattr(
            "app.ui.widgets.gguf_settings_page.AnimationManager.set_enabled",
            lambda enabled: calls.append(enabled))
        form = GgufSettingsForm(_make_config())
        calls.clear()  # 忽略 __init__/_load_settings 的初始调用
        form.sw_animations["switch"].setChecked(True)  # 勾选 = 禁用
        assert calls and calls[-1] is False
        form.sw_animations["switch"].setChecked(False)
        assert calls[-1] is True
        _destroy(form)

    def test_n_gpu_layers_empty_falls_back_to_999(self, qapp):
        """清空 n_gpu_layers 保存时兜底 999（与默认值/重置一致）"""
        form = GgufSettingsForm(_make_config())
        form.ed_n_gpu_layers.setText("")
        patch = form.get_config_patch()["ocr"]["gguf"]
        assert patch["n_gpu_layers"] == 999
        _destroy(form)

    def test_cpu_mode_disables_gpu_fields(self, qapp):
        """CPU 模式联动：禁用 GPU 层数与 mmproj 卸载输入（引擎强制 0/关）"""
        form = GgufSettingsForm(_make_config())
        assert form.ed_n_gpu_layers.isEnabled()
        assert form.sw_mmproj_offload.isEnabled()
        form.rb_device_cpu.setChecked(True)
        assert not form.ed_n_gpu_layers.isEnabled()
        assert not form.sw_mmproj_offload.isEnabled()
        # 切回 GPU 恢复可编辑
        form.rb_device_gpu.setChecked(True)
        assert form.ed_n_gpu_layers.isEnabled()
        assert form.sw_mmproj_offload.isEnabled()
        _destroy(form)

    def test_cpu_loaded_config_disables_gpu_fields(self, qapp):
        """加载 cpu 配置时初始状态即禁用 GPU 相关输入"""
        cfg = _make_config()
        cfg["ocr"]["gguf"]["device"] = "cpu"
        form = GgufSettingsForm(cfg)
        assert not form.ed_n_gpu_layers.isEnabled()
        assert not form.sw_mmproj_offload.isEnabled()
        _destroy(form)

    def test_default_resets_service_fields(self, qapp):
        form = GgufSettingsForm(_make_config())
        form.ed_port.setText("1")
        form.rb_device_cpu.setChecked(True)
        form._on_default()
        assert form.ed_port.text() == "8080"
        assert form.rb_device_gpu.isChecked()
        _destroy(form)

    def test_reset_uses_official_defaults(self, qapp):
        """重置：从 get_default_config() 恢复官方默认，路径不置空"""
        form = GgufSettingsForm(_make_config())
        form.ed_port.setText("1")
        form.ed_max_tokens.setText("256")
        form.ed_n_gpu_layers.setText("0")
        form.sw_mmproj_offload.setChecked(False)
        form._set_slider_value(form.slider_min_pixels, 100000)
        form._set_slider_value(form.slider_max_pixels, 5000000)
        form.ed_render_dpi.setText("150")
        form.ed_max_workers.setText("1")
        form.ed_retry_times.setText("0")
        form.sw_include_confidence["switch"].setChecked(False)
        form._on_default()

        assert form.ed_server_path.text() == "llama-b9969/llama-server.exe"
        assert form.ed_model_path.text() == "models/PaddleOCR-VL-1.6-GGUF.gguf"
        assert form.ed_mmproj_path.text() == "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf"
        assert form.ed_port.text() == "8080"
        assert form.ed_n_gpu_layers.text() == "999"
        assert form.ed_max_tokens.text() == "2048"
        assert form.ed_temperature.text() == "0.0"
        assert form.ed_timeout.text() == "120"
        assert form.sw_mmproj_offload.isChecked() is True
        assert form._get_slider_value(form.slider_min_pixels) == 112896
        assert form._get_slider_value(form.slider_max_pixels) == 1003520
        assert form.ed_render_dpi.text() == "200"
        assert form.ed_max_workers.text() == "4"
        assert form.ed_retry_times.text() == "2"
        assert form.sw_include_confidence["switch"].isChecked() is True
        _destroy(form)

    def test_tooltips_cover_all_controls(self, qapp):
        """数值/开关/滑块提示均含默认值，数值含调大调小、开关含开启关闭"""
        form = GgufSettingsForm(_make_config())

        path_tips = [
            form.ed_server_path.toolTip(),
            form.ed_model_path.toolTip(),
            form.ed_mmproj_path.toolTip(),
        ]
        for tip in path_tips:
            assert "默认" in tip, tip

        fixed_tips = [
            form.ed_host.toolTip(),
            form.ed_port.toolTip(),
        ]
        for tip in fixed_tips:
            assert "默认" in tip, tip

        numeric_tips = [
            form.ed_n_gpu_layers.toolTip(),
            form.ed_max_tokens.toolTip(),
            form.ed_temperature.toolTip(),
            form.ed_timeout.toolTip(),
            form.ed_render_dpi.toolTip(),
            form.ed_max_workers.toolTip(),
            form.ed_retry_times.toolTip(),
            form.slider_repetition["line_edit"].toolTip(),
            form.slider_stability["line_edit"].toolTip(),
            form.slider_confidence["line_edit"].toolTip(),
            form.slider_min_pixels["line_edit"].toolTip(),
            form.slider_max_pixels["line_edit"].toolTip(),
        ]
        for tip in numeric_tips:
            assert "默认" in tip and "调大" in tip and "调小" in tip, tip

        switch_tips = [
            form.sw_header["switch"].toolTip(),
            form.sw_footer["switch"].toolTip(),
            form.sw_page_number["switch"].toolTip(),
            form.sw_footnote["switch"].toolTip(),
            form.sw_margin_text["switch"].toolTip(),
            form.sw_header_image["switch"].toolTip(),
            form.sw_footer_image["switch"].toolTip(),
            form.sw_orientation["switch"].toolTip(),
            form.sw_distortion["switch"].toolTip(),
            form.sw_layout["switch"].toolTip(),
            form.sw_chart["switch"].toolTip(),
            form.sw_seal["switch"].toolTip(),
            form.sw_image_text["switch"].toolTip(),
            form.sw_cross_page["switch"].toolTip(),
            form.sw_heading["switch"].toolTip(),
            form.sw_mmproj_offload.toolTip(),
            form.sw_nms.toolTip(),
            form.sw_include_confidence["switch"].toolTip(),
        ]
        for tip in switch_tips:
            assert "默认" in tip and "开启" in tip and "关闭" in tip, tip
        _destroy(form)

    def test_slider_wheel_does_not_adjust(self, qapp):
        """悬停滑块横条时滚轮不调节数值，避免误触"""
        form = GgufSettingsForm(_make_config())

        class FakeWheel:
            def __init__(self):
                self.ignored = False

            def ignore(self):
                self.ignored = True

        slider = form.slider_min_pixels["slider"]
        before = slider.value()
        event = FakeWheel()
        slider.wheelEvent(event)
        assert slider.value() == before
        assert event.ignored is True
        _destroy(form)


class TestGgufSettingsPage:
    def test_page_builds_and_exposes_form(self, qapp):
        page = GgufSettingsPage(_make_config())
        assert page.form is not None
        assert page.btn_save is not None
        assert page.btn_restart is not None
        assert page.btn_test is not None
        assert page.btn_reset is not None
        _destroy(page)

    def test_reset_button_right_of_save(self, qapp):
        """重置按钮位于操作栏右下角（保存按钮右侧）"""
        page = GgufSettingsPage(_make_config())
        bar = page.btn_save.parentWidget()
        assert bar.layout().indexOf(page.btn_reset) > bar.layout().indexOf(page.btn_save)
        _destroy(page)

    def test_reset_requires_confirmation(self, qapp, monkeypatch):
        """未确认不重置；确认后调用表单 _on_default，且不触发保存"""
        page = GgufSettingsPage(_make_config())
        calls = []
        monkeypatch.setattr(page.form, "_on_default", lambda: calls.append("reset"))
        saved = []
        page.save_requested.connect(saved.append)

        monkeypatch.setattr(
            "app.ui.widgets.gguf_settings_page.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.No)
        page.btn_reset.click()
        assert calls == []

        monkeypatch.setattr(
            "app.ui.widgets.gguf_settings_page.QMessageBox.question",
            lambda *a, **k: QMessageBox.StandardButton.Yes)
        page.btn_reset.click()
        assert calls == ["reset"]
        assert saved == []
        _destroy(page)

    def test_page_signals_emit_patch(self, qapp):
        page = GgufSettingsPage(_make_config())
        saved = []
        restarted = []
        tested = []
        page.save_requested.connect(saved.append)
        page.restart_requested.connect(restarted.append)
        page.test_connection_requested.connect(
            lambda host, port: tested.append((host, port)))

        page.btn_save.click()
        page.btn_restart.click()
        page.btn_test.click()

        assert len(saved) == 1 and "ocr" in saved[0]
        assert len(restarted) == 1 and "ocr" in restarted[0]
        assert tested == [("127.0.0.1", 8080)]
        _destroy(page)

    def test_test_button_emits_form_values_not_saved_config(self, qapp):
        """测试连接携带表单当前 host/port（未保存也应测编辑中的值）"""
        page = GgufSettingsPage(_make_config())
        got = []
        page.test_connection_requested.connect(
            lambda host, port: got.append((host, port)))
        page.form.ed_host.setText("192.168.1.10")
        page.form.ed_port.setText("9999")
        page.btn_test.click()
        assert got == [("192.168.1.10", 9999)]
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

    def test_window_disables_dwm_material(self, window):
        """防截图变白：禁用 Mica 与导航 acrylic（DWM 合成材质在
        系统截图工具下会失效，透明背景回退白色）"""
        assert window.isMicaEffectEnabled() is False
        assert window.navigationInterface.isAcrylicEnabled() is False

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
        window._on_settings_test_connection("127.0.0.1", 8080)
        QTest.qWait(300)  # 后台线程 + 定时回调，不崩即可
