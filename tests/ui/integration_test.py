"""双界面集成测试：RapidMainWindow 全链路冒烟（Task P7 迁移自旧 MainWindow）

覆盖：
- RapidMainWindow 创建（窗口 / 中央区 / 三个子页面）
- 面板折叠/展开（CollapsiblePanel / SlidablePanel 集成）
- 设计锁定（design='rapid' 固定浅色，ThemeManager.set_theme no-op）
- 快捷键绑定（QShortcut.objectName = 快捷键字符串，findChild 可寻）
- 焦点跟踪（StatusBar.set_focus_area 随焦点区域切换）

说明：
- 不构造真实 OCR 引擎，monkeypatch base_window.get_ocr_engine 注入 FakeEngine
- 全部在 offscreen 平台运行
- 焦点测试：发射 QApplication.focusChanged 信号模拟焦点转移，走真实接线
- teardown 还原 ThemeManager 全局设计状态（rapid 固定单色调板会污染后续测试）
"""
import pytest
from PyQt6 import sip
from PyQt6.QtGui import QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

import app.ui.windows.base_window as base_window_module
import app.ui.windows.rapid_main_window as rw_module
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.status_bar import StatusBar


class FakeEngine:
    """最小引擎桩：避免真实 OCR 初始化（加载模型 / 启动子进程）"""

    engine_name = "rapidocr"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True

    def unload(self):
        pass


def _make_config() -> dict:
    return {
        "app": {"name": "PDFOCR", "window_size": [1400, 900], "theme": "light"},
        "ocr": {"engine": "rapidocr"},
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
    }


@pytest.fixture
def main_window(qapp, monkeypatch):
    monkeypatch.setattr(base_window_module, "get_ocr_engine",
                        lambda config: FakeEngine())
    from app.ui.widgets.cancel_result_dialog import CancelResultDialog
    monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
    w = rw_module.RapidMainWindow(_make_config())
    yield w
    _destroy_test_window(w)
    ThemeManager.set_design('default')
    ThemeManager.set_theme('light')


def _destroy_test_window(w):
    """销毁测试窗口（不调用 close()：closeEvent 会 QApplication.quit()）"""
    app_inst = QApplication.instance()
    if app_inst is not None:
        for signal, slot in (
            (app_inst.paletteChanged, getattr(w, '_on_system_palette_changed', None)),
            (app_inst.focusChanged, getattr(w, '_on_focus_changed', None)),
        ):
            if slot is None:
                continue
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass
    w.gpu_status.cleanup()
    QTest.qWait(600)
    from app.ui.animation_manager import AnimationManager
    AnimationManager.stop_all()
    w.deleteLater()
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)
    assert sip.isdeleted(w), \
        "fixture 窗口未销毁：deleteLater + 2s 后 C++ 对象仍存活"


class TestRapidWindowCreation:
    def test_main_window_creation(self, main_window):
        w = main_window
        assert w is not None
        assert w.windowTitle() == "PDF OCR — 文档工作台"
        w_, h_ = w.config["app"]["window_size"]
        assert (w.size().width(), w.size().height()) == (w_, h_)
        assert w.stackedWidget is not None
        assert w.navigationInterface is not None

    def test_three_pages_registered(self, main_window):
        """三个子页面（工作区/结果/历史）均已加入 stackedWidget"""
        w = main_window
        assert w.stackedWidget.count() == 3
        assert w.stackedWidget.currentWidget() is w.workspace_page

    def test_core_layout_widgets_present(self, main_window):
        """工作区单层水平布局关键组件齐备"""
        w = main_window
        assert w.left_panel is not None
        assert w.right_panel is not None
        assert w.workspace is not None
        assert w.file_panel is not None
        assert w.pdf_canvas is not None
        assert w.field_panel is not None
        assert w.toolbar is not None
        assert isinstance(w.status_bar, StatusBar)
        assert w.status_label is w.status_bar.status_text
        # 单会话一引擎：无引擎选择下拉框（P4）
        assert not hasattr(w, 'engine_combo')


class TestPanelToggle:
    def test_left_panel_collapse_expand(self, main_window):
        w = main_window
        w.show()
        assert not w.left_panel.is_collapsed()
        assert w.left_panel.content_area.isVisible()

        w.left_panel.collapse()
        assert w.left_panel.is_collapsed()
        assert not w.left_panel.content_area.isVisible()
        assert w.left_panel.collapsed_indicator.isVisible()

        w.left_panel.expand()
        assert not w.left_panel.is_collapsed()
        assert w.left_panel.content_area.isVisible()
        assert not w.left_panel.collapsed_indicator.isVisible()

    def test_left_panel_toggle_is_idempotent(self, main_window):
        w = main_window
        w.left_panel.collapse()
        w.left_panel.collapse()
        assert w.left_panel.is_collapsed()
        w.left_panel.expand()
        w.left_panel.expand()
        assert not w.left_panel.is_collapsed()

    def test_right_panel_slide_in_out(self, main_window):
        w = main_window
        assert w.right_panel.is_visible()
        w.right_panel.slide_out()
        assert not w.right_panel.is_visible()
        w.right_panel.slide_in()
        assert w.right_panel.is_visible()

    def test_panel_toggle_shortcut_bound(self, main_window):
        w = main_window
        w.left_panel.expand()
        w.findChild(QShortcut, 'Ctrl+Shift+L').activated.emit()
        assert w.left_panel.is_collapsed()
        w.findChild(QShortcut, 'Ctrl+Shift+L').activated.emit()
        assert not w.left_panel.is_collapsed()


class TestDesignLock:
    def test_rapid_design_locked(self, main_window):
        """Rapid 固定浅色：design='rapid' 且 ThemeManager.set_theme no-op"""
        w = main_window
        assert ThemeManager.current_design() == 'rapid'
        before = ThemeManager.current_theme()
        w._apply_design()
        assert ThemeManager.current_design() == 'rapid'
        other = 'dark' if before == 'light' else 'light'
        ThemeManager.set_theme(other)
        assert ThemeManager.current_theme() == before  # no-op

    def test_status_bar_colors_from_rapid_palette(self, main_window):
        w = main_window
        bar = w.status_bar
        assert ThemeManager.get_color('bg_surface') in bar.styleSheet()
        assert ThemeManager.get_color('border') in bar.styleSheet()


class TestShortcuts:
    SHORTCUT_NAMES = [
        'Ctrl+O', 'Ctrl+S', 'Ctrl+Return', 'Ctrl+T', 'Delete',
        'Ctrl+Z', 'Ctrl+Y', 'Ctrl+Shift+L', 'Ctrl+Shift+R',
        'Ctrl+Shift+N', 'Space',
    ]

    @pytest.mark.parametrize('shortcut_name', SHORTCUT_NAMES)
    def test_shortcut_binding_exists(self, main_window, shortcut_name):
        assert main_window.findChild(QShortcut, shortcut_name) is not None

    def test_shortcut_objects_unique(self, main_window):
        for name in self.SHORTCUT_NAMES:
            matches = main_window.findChildren(QShortcut, name)
            assert len(matches) == 1, f"{name} 绑定数量 = {len(matches)}"


class TestFocusTracking:
    HINTS = {
        'file_list': 'Ctrl+O 上传 | Delete 移除 | Space 预览',
        'pdf_preview': '左键框选 | 右键平移 | 滚轮缩放',
        'field_panel': 'Ctrl+S 保存 | Delete 删除字段',
        'global': 'Ctrl+Shift+L 文件栏 | Ctrl+Shift+R 字段栏',
    }

    @staticmethod
    def _emit_focus(widget):
        QApplication.instance().focusChanged.emit(None, widget)

    def test_focus_in_panels_updates_status_bar_hint(self, main_window):
        w = main_window
        bar = w.status_bar
        self._emit_focus(w.file_panel.list_widget)
        assert bar.shortcut_hint.text() == self.HINTS['file_list']
        self._emit_focus(w.pdf_canvas)
        assert bar.shortcut_hint.text() == self.HINTS['pdf_preview']
        self._emit_focus(w.field_panel.table)
        assert bar.shortcut_hint.text() == self.HINTS['field_panel']

    def test_focus_outside_panels_returns_global(self, main_window):
        w = main_window
        bar = w.status_bar
        self._emit_focus(w.file_panel.list_widget)
        assert bar.shortcut_hint.text() == self.HINTS['file_list']
        # 工具栏（三面板之外）→ 全局提示（P4 后无 engine_combo，用 toolbar）
        self._emit_focus(w.toolbar)
        assert bar.shortcut_hint.text() == self.HINTS['global']
        self._emit_focus(None)
        assert bar.shortcut_hint.text() == self.HINTS['global']

    def test_focus_area_hint_differs_by_area(self, main_window):
        w = main_window
        bar = w.status_bar
        seen = set()
        for widget, expected in [
            (w.file_panel.list_widget, self.HINTS['file_list']),
            (w.pdf_canvas, self.HINTS['pdf_preview']),
            (w.field_panel.table, self.HINTS['field_panel']),
        ]:
            self._emit_focus(widget)
            text = bar.shortcut_hint.text()
            assert text == expected
            seen.add(text)
        assert len(seen) == 3


class TestUploadRequestedWiring:
    def test_file_panel_upload_requested_triggers_upload_dialog(
            self, main_window, monkeypatch):
        w = main_window
        monkeypatch.setattr(
            rw_module.QFileDialog, "getOpenFileNames",
            lambda *args, **kwargs: (["dummy1.pdf", "dummy2.pdf"], ""),
        )
        assert w.file_panel.files == []
        w.file_panel.upload_requested.emit()
        assert w.file_panel.files == ["dummy1.pdf", "dummy2.pdf"]
        assert "已加载 2 个文件" in w.status_label.text()


class TestTemplateNameLabelTheme:
    def test_template_name_label_created_with_theme_manager_primary(self, main_window):
        w = main_window
        ss = w.template_name_label.styleSheet()
        assert ThemeManager.get_color('primary') in ss
        assert '#0078d4' not in ss
