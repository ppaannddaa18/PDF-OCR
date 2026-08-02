"""Task P3b 测试：RapidMainWindow（MSFluentWindow 双界面重构 + 工作区迁入）

覆盖：
- 构造成功（FakeEngine monkeypatch get_ocr_engine，与
  tests/ui/integration_test.py 同一模式）
- 顶部标签 3 页（工作区/识别结果/历史记录）注册与切换
- _apply_design 固定配色（setTheme(LIGHT) + setThemeColor('#0C8CE9')）
- 工作区组件齐全：CompactToolbar / FileListPanel / PdfCanvas / FieldPanel /
  StatusBar / 预处理工具栏 / 快捷键；关键字页不存在
- 框选/批量冒烟：_on_region_drawn 同步字段面板与画布数据；
  无文件时试识别/批量识别安全降级（不启动 worker）

说明：
- 全部在 offscreen 平台运行：不得真实启动引擎/网络/服务器
- 不调用 w.close()：closeEvent 最终 QApplication.quit()，影响 tests/ui
  共享的 qapp 单例；销毁走 deleteLater（不走 closeEvent）
- teardown 必须还原 ThemeManager 全局设计状态：rapid 为固定单色调板，
  set_theme 在其下是 no-op，不还原会污染后续 default 设计测试
"""
import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication
from qfluentwidgets import Theme

import app.ui.windows.base_window as base_window_module
from app.ui.windows.rapid_main_window import RapidMainWindow
from app.ui.theme_manager import ThemeManager


class FakeEngine:
    """最小引擎桩：避免真实 OCR 初始化（加载模型 / 启动进程）"""

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


def _destroy_test_window(w):
    """销毁测试窗口（顺序污染修复，与 integration_test 同策略）"""
    QTest.qWait(600)
    w.deleteLater()
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)
    assert sip.isdeleted(w), \
        "fixture 窗口未销毁：deleteLater + 2s 后 C++ 对象仍存活"


@pytest.fixture
def rapid_window(qapp, monkeypatch):
    monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
    # 防御：若用户机器 ~/.pdfocr/pending_task.json 存在，构造后 500ms 的
    # _check_pending_task 会 exec() 模态 MessageBox，offscreen 环境无人交互
    # 将永久挂起。测试中禁用恢复流程。
    from app.ui.widgets.cancel_result_dialog import CancelResultDialog
    monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
    w = RapidMainWindow(_make_config())
    yield w
    _destroy_test_window(w)
    # 还原 ThemeManager 全局设计状态（顺序必须 design 先）
    ThemeManager.set_design('default')
    ThemeManager.set_theme('light')


class TestRapidWindowShell:
    def test_constructs(self, rapid_window):
        """可构造：MSFluentWindow 结构 + 标题/尺寸"""
        w = rapid_window
        assert w is not None
        assert w.windowTitle() == "PDF OCR — 文档工作台"
        w_, h_ = w.config["app"]["window_size"]
        assert (w.size().width(), w.size().height()) == (w_, h_)
        assert w.stackedWidget is not None
        assert w.navigationInterface is not None

    def test_result_and_history_pages_present(self, rapid_window):
        """结果页/历史页已迁入（含统计卡片/筛选工具栏/表格/面板）"""
        w = rapid_window
        assert w.result_page is not None
        assert w.history_page is not None
        assert w.workspace_page is not None
        assert w.result_page.objectName() == 'result'
        assert w.history_page.objectName() == 'history'
        assert w.workspace_page.objectName() == 'workspace'
        assert w.stat_total is not None
        assert w.stat_success is not None
        assert w.stat_fail is not None
        assert w.filter_edit is not None
        assert w.filter_field_combo is not None
        assert w.btn_low_conf is not None
        assert w.result_table is not None
        assert w.history_panel is not None

    def test_three_tabs_registered(self, rapid_window):
        """顶部标签 3 页（工作区/识别结果/历史记录）均已加入 stackedWidget"""
        w = rapid_window
        assert w.stackedWidget.count() == 3
        assert w.stackedWidget.widget(0) is w.workspace_page
        assert w.stackedWidget.widget(1) is w.result_page
        assert w.stackedWidget.widget(2) is w.history_page
        assert w.stackedWidget.currentWidget() is w.workspace_page

    def test_tab_switching(self, rapid_window):
        """顶部标签切换正常（switchTo → stackedWidget 当前页变化）"""
        w = rapid_window
        w.switchTo(w.result_page)
        assert w.stackedWidget.currentWidget() is w.result_page
        w.switchTo(w.history_page)
        assert w.stackedWidget.currentWidget() is w.history_page
        w.switchTo(w.workspace_page)
        assert w.stackedWidget.currentWidget() is w.workspace_page

    def test_no_gguf_pages(self, rapid_window):
        """Rapid 窗口无关键字页/设置页（GGUF 专属，P4 建）"""
        w = rapid_window
        assert not hasattr(w, 'keyword_page')
        assert not hasattr(w, 'settings_page')

    def test_no_system_theme_listener(self, rapid_window):
        """固定配色：窗口不监听系统主题变化（无 paletteChanged 槽）"""
        assert not hasattr(rapid_window, '_on_system_palette_changed')

    def test_result_toolbar_slots_update_status_bar(self, rapid_window):
        """结果页槽函数可触发且写入状态栏（P3b 工作区已迁入 StatusBar）"""
        w = rapid_window
        assert hasattr(w, 'status_label')
        w._on_filter_changed()
        w._on_reset_all_results()
        assert '已重置' in w.status_label.text()
        w._on_toggle_low_confidence()
        w._on_toggle_low_confidence()
        w._on_result_data_changed()


class TestRapidWindowWorkspace:
    def test_workspace_widgets_present(self, rapid_window):
        """工作区组件齐全（P3b 迁入：文件栏/画布/字段面板/状态栏/工具栏）"""
        w = rapid_window
        assert hasattr(w, 'toolbar')
        assert hasattr(w, 'file_panel')
        assert hasattr(w, 'left_panel')
        assert hasattr(w, 'pdf_canvas')
        assert hasattr(w, 'field_panel')
        assert hasattr(w, 'right_panel')
        assert hasattr(w, 'preprocess_toolbar')
        assert hasattr(w, 'status_bar')
        assert hasattr(w, 'status_label')
        assert hasattr(w, 'template_name_label')
        assert hasattr(w, 'btn_set_default')
        assert hasattr(w, 'progress_bar')
        # 单会话一引擎（P4）：Rapid 窗口无引擎选择下拉框
        assert not hasattr(w, 'engine_combo')

    def test_status_bar_engine_bridge(self, rapid_window):
        """GpuStatusWidget.status_changed → 底部状态栏引擎状态"""
        w = rapid_window
        w.gpu_status.status_changed.emit('rapidocr', 'ready')
        assert 'RapidOCR' in w.status_bar.engine_label.text()
        assert '就绪' in w.status_bar.engine_label.text()

    def test_workspace_shortcuts_bound(self, rapid_window):
        """工作区快捷键子集全部绑定（对象名 = 快捷键字符串）"""
        from PyQt6.QtGui import QShortcut
        w = rapid_window
        for name in ('Ctrl+O', 'Ctrl+S', 'Ctrl+Return', 'Ctrl+T', 'Delete',
                     'Ctrl+Z', 'Ctrl+Y', 'Ctrl+Shift+L', 'Ctrl+Shift+R',
                     'Ctrl+Shift+N', 'Space'):
            assert w.findChild(QShortcut, name) is not None, name

    def test_region_drawn_updates_field_panel(self, rapid_window):
        """框选区域 → 字段面板 + 画布数据同步（无图时 update_regions 安全跳过）"""
        from app.models.region import Region
        w = rapid_window
        region = Region(id='r1', field_name='姓名', x=0.1, y=0.2, w=0.3, h=0.1)
        w._on_region_drawn(region)
        assert region.id in w.field_panel.regions
        assert region.id in w.pdf_canvas.regions_data
        # 撤销可回滚
        w._undo()
        assert region.id not in w.field_panel.regions

    def test_try_ocr_and_batch_without_files_are_safe(self, rapid_window):
        """无文件时试识别/批量识别安全降级（InfoBar 提示，不启动 worker）"""
        w = rapid_window
        w.on_try_ocr()
        w.on_batch_run()
        assert w.worker is None

    def test_upload_adds_files_and_status(self, rapid_window, monkeypatch, tmp_path):
        """on_upload 走文件对话框（monkeypatch）→ 文件面板加载 + 状态栏提示"""
        pdf_file = tmp_path / "sample.pdf"
        pdf_file.write_bytes(b"%PDF-1.4 fake")
        w = rapid_window
        monkeypatch.setattr(
            "app.ui.windows.rapid_main_window.QFileDialog.getOpenFileNames",
            lambda *a, **k: ([str(pdf_file)], ""))
        w.on_upload()
        assert str(pdf_file) in w.file_panel.files
        assert '已加载' in w.status_label.text()


class TestRapidWindowDesign:
    def test_apply_design_sets_rapid_palette(self, qapp, monkeypatch):
        """_apply_design：setTheme(LIGHT) + setThemeColor('#0C8CE9') + design=rapid"""
        calls = []
        monkeypatch.setattr(base_window_module, "setTheme",
                            lambda theme: calls.append(('setTheme', theme)))
        monkeypatch.setattr(base_window_module, "setThemeColor",
                            lambda color: calls.append(('setThemeColor', color)))
        monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        w = RapidMainWindow(_make_config())
        calls.clear()  # 构造期调用不计，只统计显式调用
        w._apply_design()
        assert ('setTheme', Theme.LIGHT) in calls
        assert ('setThemeColor', '#0C8CE9') in calls
        assert ThemeManager.current_design() == 'rapid'
        _destroy_test_window(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')

    def test_constructor_applies_design(self, qapp, monkeypatch):
        """构造即应用 rapid 设计（set_design 触发统计标签颜色刷新）"""
        monkeypatch.setattr(base_window_module, "get_ocr_engine", lambda config: FakeEngine())
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        w = RapidMainWindow(_make_config())
        assert ThemeManager.current_design() == 'rapid'
        assert ThemeManager.get_color('success') in w.stat_success.styleSheet()
        assert ThemeManager.get_color('error') in w.stat_fail.styleSheet()
        _destroy_test_window(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
