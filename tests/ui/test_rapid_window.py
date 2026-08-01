"""Task P3a 测试：RapidMainWindow 壳（MSFluentWindow 双界面重构）

覆盖：
- 空壳构造成功（FakeEngine monkeypatch get_ocr_engine，与
  tests/ui/integration_test.py 同一模式）
- 顶部标签 3 页（工作区/识别结果/历史记录）注册与切换
- _apply_design 固定配色（setTheme(LIGHT) + setThemeColor('#0C8CE9')）
- 壳阶段无 keyword_page/engine_combo/pdf_canvas/field_panel
  （后两者 P3b 迁入后改断言）

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
    """销毁测试窗口（顺序污染修复，与 integration_test 同策略）

    不调用 w.close()：closeEvent 会启动异步清理线程并最终经
    QTimer.singleShot 调 QApplication.quit()，影响 tests/ui 共享的 qapp
    单例。qWait(600) 覆盖构造期 singleShot(0/500ms) 定时器（OCR-Init
    回调 / _check_pending_task）后 deleteLater 走析构，轮询自验证。
    """
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
    # 还原 ThemeManager 全局设计状态（rapid 固定单色调板会使 set_theme
    # no-op，污染后续 default 设计测试；顺序必须 design 先）
    ThemeManager.set_design('default')
    ThemeManager.set_theme('light')


class TestRapidWindowShell:
    def test_constructs(self, rapid_window):
        """空壳可构造：MSFluentWindow 结构 + 标题/尺寸"""
        w = rapid_window
        assert w is not None
        assert w.windowTitle() == "PDF OCR — 文档工作台"
        w_, h_ = w.config["app"]["window_size"]
        assert (w.size().width(), w.size().height()) == (w_, h_)
        # MSFluentWindow 结构（顶部 NavigationBar 导航）
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
        # 统计卡片 / 筛选工具栏 / 结果表格 / 历史面板
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

    def test_no_workspace_widgets(self, rapid_window):
        """壳阶段不存在的组件（P3b 迁入工作区后改断言）"""
        w = rapid_window
        assert not hasattr(w, 'keyword_page')
        assert not hasattr(w, 'engine_combo')
        assert not hasattr(w, 'pdf_canvas')
        assert not hasattr(w, 'field_panel')

    def test_no_system_theme_listener(self, rapid_window):
        """固定配色：窗口不监听系统主题变化（无 paletteChanged 槽）"""
        assert not hasattr(rapid_window, '_on_system_palette_changed')

    def test_result_toolbar_slots_safe_without_status_bar(self, rapid_window):
        """壳阶段无状态栏时结果页槽函数可正常触发（getattr 防御，P3b 后解除）"""
        w = rapid_window
        assert not hasattr(w, 'status_label')
        w._on_filter_changed()  # 无状态栏不崩
        w._on_reset_all_results()
        w._on_toggle_low_confidence()
        w._on_toggle_low_confidence()  # 切回显示全部分支
        w._on_result_data_changed()
        assert not hasattr(w, 'status_label')


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
        # 构造后 ThemeManager 已切到 rapid 设计
        assert ThemeManager.current_design() == 'rapid'
        # 统计标签内嵌 QSS 已按 rapid 色板烘焙（set_design 触发 refresh 回调）
        assert ThemeManager.get_color('success') in w.stat_success.styleSheet()
        assert ThemeManager.get_color('error') in w.stat_fail.styleSheet()
        _destroy_test_window(w)
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
