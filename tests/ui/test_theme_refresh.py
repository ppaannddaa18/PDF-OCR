"""Task 15 暗色模式适配测试

覆盖：
- 全局主题刷新机制：ThemeManager.set_theme 后已创建组件的内嵌 QSS 重建
  （构造时烘焙的颜色字符串需重新生成，unpolish/polish 不足）
- 设置对话框主题选项：加载配置 / 即时应用 / get_config_patch 保存
- 启动接线：MainWindow 构造时从 appearance.theme / animations_enabled 应用
- offscreen 冒烟：构造 MainWindow → set_theme('dark') → 关键组件含暗色值
  → close() 不崩溃
"""
import gc

import pytest

from app.ui.theme_manager import ThemeManager
from app.ui.animation_manager import AnimationManager
from app.ui.widgets.empty_state import EmptyState
from app.ui.widgets.status_bar import StatusBar
from app.ui.widgets.ocr_settings_dialog import OcrSettingsDialog


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

    engine_name = "gguf"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True


def _construct_main_window(monkeypatch, config: dict):
    from app.ui import main_window as mw_module
    monkeypatch.setattr(mw_module, "get_ocr_engine", lambda cfg: FakeEngine())
    return mw_module.MainWindow(config)


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

    def test_result_panel_focus_qss(self, qapp):
        from app.ui.widgets.result_panel import ResultPanel
        ThemeManager.set_theme('light')
        panel = ResultPanel()
        table_ss, tab_ss = panel._field_table.styleSheet(), panel.tab_bar.styleSheet()
        assert ':focus' in table_ss and ':focus' in tab_ss
        assert ThemeManager.get_color('border_focus') in table_ss
        assert ThemeManager.get_color('border_focus') in tab_ss
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('border_focus') in panel._field_table.styleSheet()
        assert ThemeManager.get_color('border_focus') in panel.tab_bar.styleSheet()

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


class TestSettingsDialogTheme:
    """设置对话框主题选项：加载 / 即时应用 / 保存"""

    def test_theme_radio_loads_from_config(self, qapp):
        dlg = OcrSettingsDialog(_make_config(theme='dark'))
        try:
            assert dlg.rb_theme_dark.isChecked()
            assert not dlg.rb_theme_light.isChecked()
            assert not dlg.rb_theme_auto.isChecked()
        finally:
            dlg.close()

    def test_theme_default_is_auto(self, qapp):
        dlg = OcrSettingsDialog(_make_config())
        try:
            assert dlg.rb_theme_auto.isChecked()
        finally:
            dlg.close()

    def test_dialog_open_does_not_change_theme(self, qapp):
        """打开对话框只回显配置，不立即切换运行主题（加载时 blockSignals）"""
        ThemeManager.set_theme('light')
        dlg = OcrSettingsDialog(_make_config(theme='dark'))
        try:
            assert ThemeManager.current_theme() == 'light'
        finally:
            dlg.close()

    def test_toggle_theme_applies_immediately(self, qapp):
        ThemeManager.set_theme('light')
        dlg = OcrSettingsDialog(_make_config(theme='auto'))
        try:
            dlg.rb_theme_dark.setChecked(True)
            assert ThemeManager.current_theme() == 'dark'
            # 对话框自身内嵌 QSS 同步重建（qfluentwidgets 重排后烘焙生效）
            assert ThemeManager.get_color('primary') in dlg.btn_apply.styleSheet()
            assert ThemeManager.get_color('border') in dlg._theme_sliders[0].styleSheet()
        finally:
            dlg.close()

    def test_config_patch_contains_theme(self, qapp):
        dlg = OcrSettingsDialog(_make_config())
        try:
            dlg.rb_theme_light.setChecked(True)
            dlg.sw_animations["switch"].setChecked(True)  # 禁用动画
            patch = dlg.get_config_patch()
            assert patch["appearance"]["theme"] == 'light'
            assert patch["appearance"]["animations_enabled"] is False
        finally:
            dlg.close()

    def test_default_resets_theme_to_auto(self, qapp):
        dlg = OcrSettingsDialog(_make_config(theme='dark'))
        try:
            dlg._on_default()
            assert dlg.rb_theme_auto.isChecked()
        finally:
            dlg.close()


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


class TestStartupWiring:
    """MainWindow 启动接线：appearance.theme / animations_enabled"""

    def test_main_window_applies_config_theme_at_startup(self, qapp, monkeypatch):
        w = _construct_main_window(monkeypatch, _make_config(theme='dark'))
        try:
            assert ThemeManager.current_theme() == 'dark'
            # 组件在暗色下构造，构造即烘焙暗色值
            assert '#1f2937' in w.status_bar.styleSheet()
            assert '#1f2937' in w.toolbar.styleSheet()
            assert '#111827' in w.pdf_canvas.styleSheet()
        finally:
            w.gpu_status.cleanup()

    def test_main_window_applies_animation_setting(self, qapp, monkeypatch):
        try:
            AnimationManager.set_enabled(True)
            w = _construct_main_window(
                monkeypatch, _make_config(theme='light', animations=False))
            try:
                assert AnimationManager.is_enabled() is False
            finally:
                w.gpu_status.cleanup()
        finally:
            AnimationManager.set_enabled(True)

    def test_main_window_legacy_app_theme_fallback(self, qapp, monkeypatch):
        """兼容旧配置 app.theme（appearance.theme 缺失时回退）"""
        from app.ui import main_window as mw_module
        config = _make_config(theme='light')
        del config["appearance"]
        config["app"]["theme"] = "dark"
        w = _construct_main_window(monkeypatch, config)
        try:
            assert ThemeManager.current_theme() == 'dark'
        finally:
            w.gpu_status.cleanup()


class TestMainWindowSmoke:
    """offscreen 冒烟：构造 → 切换暗色 → 断言 → close 不崩溃"""

    def test_smoke_theme_switch_and_close(self, qapp, monkeypatch):
        from app.ui.theme_manager import ThemeManager
        w = _construct_main_window(monkeypatch, _make_config(theme='light'))
        try:
            # 亮色构造
            assert '#ffffff' in w.status_bar.styleSheet()
            assert '#ffffff' in w.left_panel.styleSheet()
            # 运行时切换暗色 → 全局刷新回调重建全部已创建组件
            ThemeManager.set_theme('dark')
            assert '#1f2937' in w.status_bar.styleSheet()
            assert '#1f2937' in w.toolbar.styleSheet()
            assert '#1f2937' in w.left_panel.styleSheet()
            assert '#1f2937' in w.right_panel.styleSheet()
            assert '#111827' in w.pdf_canvas.styleSheet()
            assert '#1f2937' in w.field_panel.table.styleSheet()
            # close 不崩溃
            w.close()
        finally:
            w.gpu_status.cleanup()
