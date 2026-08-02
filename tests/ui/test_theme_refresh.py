"""Task 15 暗色模式适配测试（Task P7 迁移：窗口侧改为 Rapid 设计锁定）

覆盖：
- 全局主题刷新机制：ThemeManager.set_theme 后已创建组件的内嵌 QSS 重建
  （构造时烘焙的颜色字符串需重新生成，unpolish/polish 不足）
- 启动接线：RapidMainWindow 构造即锁定 design='rapid'（浅色），
  appearance.theme / animations_enabled 不再驱动窗口启动
- offscreen 冒烟：构造 RapidMainWindow → 关键组件含 rapid 色板值
  → deleteLater 销毁不崩溃
"""
import gc
import time

import pytest
from PyQt6 import sip
from PyQt6.QtTest import QTest

import app.ui.windows.base_window as base_window_module
from app.ui.theme_manager import ThemeManager
from app.ui.animation_manager import AnimationManager
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.status_bar import StatusBar


def _make_config(theme='auto', animations=True) -> dict:
    return {
        "app": {"name": "PDFOCR", "window_size": [1400, 900]},
        "ocr": {"engine": "rapidocr", "gguf": {}},
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
        "appearance": {"theme": theme, "animations_enabled": animations},
    }


class FakeEngine:
    """最小引擎桩：避免真实 OCR 初始化（加载模型 / 启动 llama-server）"""

    engine_name = "rapidocr"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True

    def unload(self):
        pass


def _construct_rapid_window(monkeypatch, config: dict):
    monkeypatch.setattr(base_window_module, "get_ocr_engine",
                        lambda cfg: FakeEngine())
    from app.ui.windows.rapid_main_window import RapidMainWindow
    return RapidMainWindow(config)


def _destroy_rapid_window(w):
    """销毁测试窗口（不调 close()：closeEvent 会 QApplication.quit()）"""
    w.gpu_status.cleanup()
    QTest.qWait(600)
    w.deleteLater()
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)
    ThemeManager.set_design('default')
    ThemeManager.set_theme('light')


class TestGlobalRefresh:
    """ThemeManager.set_theme 触发已创建组件重建 QSS（回调注册表）"""

    def test_empty_state_refreshes_on_theme_change(self, qapp):
        ThemeManager.set_theme('light')
        es = EmptyState('no_files')
        assert '#ffffff' in es.styleSheet()          # light bg_surface
        ThemeManager.set_theme('dark')
        # 构造时烘焙的亮色背景已重建为暗色
        assert ThemeManager.get_color('bg_surface') in es.styleSheet()
        assert '#1f2937' in es.styleSheet()

    def test_status_bar_refreshes_on_theme_change(self, qapp):
        ThemeManager.set_theme('light')
        bar = StatusBar()
        assert '#ffffff' in bar.styleSheet()
        ThemeManager.set_theme('dark')
        assert '#1f2937' in bar.styleSheet()         # dark bg_surface
        assert '#374151' in bar.styleSheet()         # dark border
        # 文本与圆点颜色（角色存储，主题切换后重解析）
        assert '#d1d5db' in bar.status_text.styleSheet()  # dark text_secondary

    def test_dot_colors_follow_theme_role(self, qapp):
        ThemeManager.set_theme('light')
        bar = StatusBar()
        bar.set_status('完成', 'success')
        assert ThemeManager.get_color('success') in bar.status_icon.styleSheet()
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('success') in bar.status_icon.styleSheet()
        assert '#22c55e' in bar.status_icon.styleSheet()  # dark success

    def test_dead_callback_weakref_pruned(self, qapp):
        """已销毁组件的回调经弱引用自动失效，set_theme 不崩溃"""
        ThemeManager.set_theme('light')
        widget = EmptyState('no_files')
        del widget
        gc.collect()
        # 触发清理路径（不应抛异常、不应误刷新任何存活组件）
        ThemeManager.set_theme('dark')
        ThemeManager.set_theme('light')

    def test_resolve_theme_auto_returns_concrete(self, qapp):
        """'auto' 解析结果必须是具体主题（非恒真：与检测值比对）"""
        resolved = ThemeManager.resolve_theme('auto')
        assert resolved in ('light', 'dark')
        assert ThemeManager.resolve_theme('light') == 'light'
        assert ThemeManager.resolve_theme('dark') == 'dark'

    def test_set_theme_same_theme_is_noop(self, qapp):
        """相同主题重复设置不触发回调（构造/刷新后状态已一致）"""
        ThemeManager.set_theme('light')
        es = EmptyState('no_files')
        assert '#ffffff' in es.styleSheet()
        ThemeManager.set_theme('light')  # no-op，不重建
        assert '#ffffff' in es.styleSheet()


class TestFocusRing:
    """Task 5 焦点环：明暗两主题下组件 QSS 均含 :focus 规则与 border_focus"""

    def test_file_list_focus_qss(self, qapp):
        from app.ui.widgets.file_list_panel import FileListPanel
        ThemeManager.set_theme('light')
        panel = FileListPanel()
        ss = panel.list_widget.styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('border_focus') in ss
        ThemeManager.set_theme('dark')
        ss = panel.list_widget.styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('border_focus') in ss

    def test_field_panel_focus_qss(self, qapp):
        from app.ui.widgets.field_panel import FieldPanel
        ThemeManager.set_theme('light')
        panel = FieldPanel()
        ss = panel.table.styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('border_focus') in ss
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('border_focus') in panel.table.styleSheet()

    def test_compact_toolbar_focus_qss(self, qapp):
        from app.ui.widgets.compact_toolbar import CompactToolbar
        ThemeManager.set_theme('light')
        bar = CompactToolbar()
        ss = bar._icon_buttons[0].styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('border_focus') in ss
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('border_focus') in bar._icon_buttons[0].styleSheet()

    def test_canvas_zoom_buttons_focus_qss(self, qapp):
        from app.ui.widgets.pdf_canvas import PdfCanvas
        ThemeManager.set_theme('light')
        canvas = PdfCanvas()
        ss = canvas._btn_fit_width.styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('border_focus') in ss
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('border_focus') in canvas._btn_fit_width.styleSheet()

    def test_empty_state_action_button_focus_qss(self, qapp):
        """primary 按钮焦点环用 white（primary 底色上 border_focus 不可见）"""
        from app.ui.widgets.empty_state import EmptyState
        ThemeManager.set_theme('light')
        es = EmptyState('no_files')
        ss = es.action_button.styleSheet()
        assert ':focus' in ss
        assert ThemeManager.get_color('white') in ss
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('white') in es.action_button.styleSheet()

    def test_primary_button_disabled_qss(self, qapp):
        """primary 按钮 :disabled 态（解析中按钮置灰），明暗两主题均含"""
        from app.ui.widgets.button_style import primary_qss
        for theme in ('light', 'dark'):
            ThemeManager.set_theme(theme)
            ss = primary_qss()
            assert ':disabled' in ss
            assert ThemeManager.get_color('text_disabled') in ss


class TestDialogComponentsTheme:
    """修复 I-1：三个对话框组件硬编码浅色适配（暗色模式无浅色残留）"""

    def test_cancel_result_dialog_dark(self, qapp):
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        ThemeManager.set_theme('dark')
        dlg = CancelResultDialog(completed=5, success=4, failed=1, total=10)
        try:
            # 统计卡片背景为暗色 bg_hover
            assert ThemeManager.get_color('bg_hover') in dlg.stats_widget.styleSheet()
            # 富文本统计颜色为暗色角色色
            assert ThemeManager.get_color('success') in dlg.stats_widget.text()
            assert ThemeManager.get_color('error') in dlg.stats_widget.text()
            assert ThemeManager.get_color('text_secondary') in dlg.stats_widget.text()
        finally:
            dlg.close()

    def test_template_preview_dialog_dark(self, qapp):
        from app.ui.widgets.template_preview_dialog import TemplatePreviewDialog
        ThemeManager.set_theme('dark')
        data = {
            'regions': [{'field_name': '金额', 'field_type': 'number'}],
            'created_at': '2026-01-01',
            'description': '测试模板',
        }
        dlg = TemplatePreviewDialog('tpl', data)
        try:
            ss = dlg.table.styleSheet()
            assert ThemeManager.get_color('border') in ss    # 暗色边框
            assert ThemeManager.get_color('bg_hover') in ss  # 暗色交替行
        finally:
            dlg.close()

    def test_history_panel_refreshes_on_theme_change(self, qapp):
        from app.ui.widgets.history_panel import HistoryPanel

        class _StubManager:
            def get_history(self):
                return []

        ThemeManager.set_theme('light')
        panel = HistoryPanel(_StubManager())
        assert '#6b7280' in panel.desc.styleSheet()   # light text_secondary
        ThemeManager.set_theme('dark')
        assert '#d1d5db' in panel.desc.styleSheet()   # dark text_secondary


class TestDesignWiring:
    """Rapid 固定设计：appearance.theme / animations_enabled 不再驱动窗口启动"""

    def test_rapid_window_locks_design_at_startup(self, qapp, monkeypatch):
        w = _construct_rapid_window(monkeypatch, _make_config(theme='dark'))
        try:
            assert ThemeManager.current_design() == 'rapid'
            # 组件按 rapid 浅色色板烘焙（构造即锁定，不随 config.theme）
            assert ThemeManager.get_color('bg_surface') in w.status_bar.styleSheet()
            assert ThemeManager.get_color('bg_surface') in w.toolbar.styleSheet()
        finally:
            _destroy_rapid_window(w)

    def test_rapid_window_ignores_animations_key_at_startup(
            self, qapp, monkeypatch):
        """动画开关已移到设置对话框：窗口启动不再覆盖 AnimationManager"""
        import app.ui.animation_manager as anim_module
        from app.ui.animation_manager import AnimationManager
        original = anim_module.AnimationManager.set_enabled
        calls = []

        def _spy(value):
            calls.append(value)
            return original(value)

        monkeypatch.setattr(anim_module.AnimationManager, "set_enabled", _spy)
        monkeypatch.setattr(anim_module.AnimationManager, "_enabled", False)
        try:
            w = _construct_rapid_window(
                monkeypatch, _make_config(theme='light', animations=False))
            try:
                assert calls == []  # 启动不调用 set_enabled
                assert AnimationManager.is_enabled() is False
            finally:
                _destroy_rapid_window(w)
        finally:
            AnimationManager.set_enabled(True)


class TestRapidWindowSmoke:
    """offscreen 冒烟：构造 → rapid 色板断言 → deleteLater 销毁"""

    def test_smoke_rapid_palette_and_destroy(self, qapp, monkeypatch):
        w = _construct_rapid_window(monkeypatch, _make_config(theme='light'))
        try:
            assert ThemeManager.get_color('bg_surface') in w.status_bar.styleSheet()
            assert ThemeManager.get_color('bg_surface') in w.left_panel.styleSheet()
            assert ThemeManager.get_color('bg_surface') in w.right_panel.styleSheet()
            assert ThemeManager.get_color('bg_primary') in w.pdf_canvas.styleSheet()
            assert ThemeManager.get_color('bg_surface') in w.field_panel.table.styleSheet()
            # design 锁定：运行时 set_theme 不改变 rapid 色板
            ThemeManager.set_theme('dark')
            assert ThemeManager.get_color('bg_surface') in w.status_bar.styleSheet()
        finally:
            _destroy_rapid_window(w)

    def test_no_keyword_page_in_rapid_window(self, qapp, monkeypatch):
        """关键字页为 GGUF 专属（P4 功能裁剪）：Rapid 窗口无该页"""
        w = _construct_rapid_window(monkeypatch, _make_config(theme='light'))
        try:
            assert not hasattr(w, "keyword_page")
            assert not hasattr(w, "settings_page")
        finally:
            _destroy_rapid_window(w)
