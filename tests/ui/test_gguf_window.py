"""Task P4 测试：GgufMainWindow（FluentWindow 侧边导航 4 页深色操作台）

覆盖：
- 构造成功（FakeEngine monkeypatch get_ocr_engine）
- 侧边导航 4 页（关键字提取/识别结果/历史记录/模型设置）注册与切换
- _apply_design 固定深色（setTheme(DARK) + setThemeColor('#C9A227')）
- 无模板工作区（无 pdf_canvas/field_panel/engine_combo）
- 关键字提取完成 → adapter → 结果页/历史/统计同步
- 顶部 EngineStatusBand 发光带随引擎就绪变冰青

说明：不调用 w.close()（closeEvent 会 QApplication.quit()），销毁走
deleteLater；teardown 还原 ThemeManager 全局设计状态。
"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest
from qfluentwidgets import Theme

import app.ui.windows.base_window as base_window_module
from app.ui.windows.gguf_main_window import GgufMainWindow
from app.ui.theme_manager import ThemeManager


class FakeEngine:
    """最小引擎桩：避免真实启动 llama-server"""

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
        "ocr": {"engine": "gguf", "gguf": {"device": "gpu"}},
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
    }


def _destroy_test_window(w):
    QTest.qWait(600)
    w.deleteLater()
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)
    assert sip.isdeleted(w), "fixture 窗口未销毁"


def _make_keyword_results():
    from app.models.keyword_result import (
        FileKeywordResult, KeywordCell, PageKeywordResult,
    )
    return [
        FileKeywordResult(
            source_file=r"C:\\tmp\\a.pdf",
            pages=[PageKeywordResult(page_no=1, cells={
                "发票号码": KeywordCell(keyword="发票号码", value="12345",
                                        status="confirmed", confidence=0.95),
                "价税合计": KeywordCell(keyword="价税合计", value="678",
                                        status="pending", confidence=0.5),
            })],
            success=True,
        ),
        FileKeywordResult(
            source_file=r"C:\\tmp\\b.pdf",
            pages=[],
            success=False,
            error_msg="boom",
        ),
    ]


@pytest.fixture
def gguf_window(qapp, monkeypatch):
    monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
    from app.ui.widgets.cancel_result_dialog import CancelResultDialog
    monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
    w = GgufMainWindow(_make_config())
    yield w
    _destroy_test_window(w)
    ThemeManager.set_design('default')
    ThemeManager.set_theme('dark')


class TestGgufWindowShell:
    def test_constructs(self, gguf_window):
        w = gguf_window
        assert w is not None
        assert w.windowTitle() == "PDF OCR — 推理操作台"
        w_, h_ = w.config["app"]["window_size"]
        assert (w.size().width(), w.size().height()) == (w_, h_)
        assert w.stackedWidget is not None
        assert w.navigationInterface is not None

    def test_four_pages_registered(self, gguf_window):
        """侧边导航 4 页：关键字提取/识别结果/历史记录/模型设置"""
        w = gguf_window
        assert w.stackedWidget.count() == 4
        names = [w.stackedWidget.widget(i).objectName()
                 for i in range(w.stackedWidget.count())]
        assert names == ['keyword', 'result', 'history', 'settings']
        assert w.stackedWidget.currentWidget() is w.keyword_page

    def test_gguf_pages_and_no_workspace(self, gguf_window):
        """有 keyword/settings/file_panel/engine_band；无模板工作区组件"""
        w = gguf_window
        assert w.keyword_page is not None
        assert w.settings_page is not None
        # P5：设置页为 GgufSettingsPage（含表单与操作带）
        assert hasattr(w.settings_page, 'form')
        assert hasattr(w.settings_page, 'btn_save')
        assert w.file_panel is not None
        assert w.left_panel is not None
        assert w.engine_band is not None
        assert w.status_label is not None
        assert w.result_page is not None
        assert w.history_page is not None
        assert not hasattr(w, 'pdf_canvas')
        assert not hasattr(w, 'field_panel')
        assert not hasattr(w, 'engine_combo')
        assert not hasattr(w, 'toolbar')

    def test_tab_switching(self, gguf_window):
        w = gguf_window
        w.switchTo(w.result_page)
        assert w.stackedWidget.currentWidget() is w.result_page
        w.switchTo(w.settings_page)
        assert w.stackedWidget.currentWidget() is w.settings_page
        w.switchTo(w.keyword_page)
        assert w.stackedWidget.currentWidget() is w.keyword_page

    def test_gguf_shortcuts_bound(self, gguf_window):
        from PyQt6.QtGui import QShortcut
        w = gguf_window
        for name in ('Ctrl+O', 'Ctrl+Return', 'Ctrl+S',
                     'Ctrl+Shift+N', 'Ctrl+Shift+F'):
            assert w.findChild(QShortcut, name) is not None, name
        # GGUF 无 Rapid 专属快捷键
        assert w.findChild(QShortcut, 'Delete') is None

    def test_engine_band_turns_ready(self, gguf_window):
        """引擎就绪回调 → 发光带 'ready'（冰青）"""
        w = gguf_window
        QTest.qWait(300)  # 等待 _on_ocr_ready 定时回调
        assert w.engine_band.status() == 'ready'
        assert w._keyword_processor is not None


class TestGgufKeywordFlow:
    def test_keyword_done_syncs_result_page_and_history(
            self, gguf_window, monkeypatch):
        """提取完成 → 汇总页 + adapter → 结果页/历史/统计"""
        w = gguf_window
        records = []
        monkeypatch.setattr(w.history_manager, "add_record",
                            lambda results: records.append(results))

        w._on_keyword_done(_make_keyword_results())

        # 汇总页
        assert len(w.keyword_page.current_results()) == 2
        assert w.keyword_page.btn_export.isEnabled()
        # 结果页（adapter：每文件每关键字一行）
        assert len(w.results) == 2
        assert w.result_table.rowCount() >= 1
        assert '发票号码' in w.filter_field_combo.currentText() or \
            w.filter_field_combo.count() >= 2
        assert records and len(records) == 1 and len(records[0]) == 2
        # 统计
        assert w.stat_total.text() == "共 2 个文件"
        assert w.stat_success.text() == "成功: 1"

    def test_keyword_extract_without_files_is_safe(self, gguf_window):
        w = gguf_window
        w._on_keyword_extract(["发票号码"])  # 无文件：警告，不崩
        assert w._keyword_worker is None

    def test_cell_inspect_without_results_is_safe(self, gguf_window):
        w = gguf_window
        w._on_cell_inspect(0, 1, "发票号码")  # 空结果：直接返回

    def test_file_upload_updates_status(self, gguf_window, monkeypatch, tmp_path):
        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        w = gguf_window
        monkeypatch.setattr(
            "app.ui.windows.gguf_main_window.QFileDialog.getOpenFileNames",
            lambda *a, **k: ([str(pdf_file)], ""))
        w.on_upload()
        assert str(pdf_file) in w.file_panel.files
        assert '已加载' in w.status_label.text()


class TestGgufWindowDesign:
    def test_apply_design_sets_gguf_palette(self, qapp, monkeypatch):
        """_apply_design：setTheme(DARK) + setThemeColor('#C9A227') + design=gguf"""
        calls = []
        monkeypatch.setattr(base_window_module, "setTheme",
                            lambda theme: calls.append(('setTheme', theme)))
        monkeypatch.setattr(base_window_module, "setThemeColor",
                            lambda color: calls.append(('setThemeColor', color)))
        monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        w = GgufMainWindow(_make_config())
        calls.clear()
        w._apply_design()
        assert ('setTheme', Theme.DARK) in calls
        assert ('setThemeColor', '#C9A227') in calls
        assert ThemeManager.current_design() == 'gguf'
        _destroy_test_window(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')

    def test_constructor_applies_design(self, qapp, monkeypatch):
        monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        w = GgufMainWindow(_make_config())
        assert ThemeManager.current_design() == 'gguf'
        assert ThemeManager.get_color('success') in w.stat_success.styleSheet()
        assert ThemeManager.get_color('error') in w.stat_fail.styleSheet()
        _destroy_test_window(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')
