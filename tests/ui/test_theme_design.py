"""P2 双设计 token 管道测试

覆盖：
- set_design / current_design；未知 design 抛 ValueError
- design 非 default 时 get_color 取设计专属调色板（gguf 深色 / rapid 浅色）
- set_design 变化触发已注册刷新回调；相同 design 重复设置 no-op
- gguf=dark-only / rapid=light-only：set_theme no-op，get_color 不受影响
- default 回归：light/dark 切换行为与改造前一致
- 已注册组件（如 StatusBar）set_design 后 QSS 自动重建为设计色
- apply_card_shadow 挂载 QGraphicsDropShadowEffect（blur 12 / rgba(15,23,42,0.06)）
- get_radius design 感知（gguf sm=2 / rapid sm=4 / default sm=4）
- get_font('mono') 解析 mono family（Consolas 优先，缺省 Courier New）
- button_style.primary_qss 三设计下取对应 accent/primary 色
- EngineStatusBand 骨架冒烟：三态 set_status 颜色映射
"""
import pytest
from PyQt6.QtWidgets import QGraphicsDropShadowEffect, QWidget

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss
from app.ui.widgets.engine_status_band import EngineStatusBand


class TestDesignTokenPipeline:
    """design 维度 token 管道"""

    def test_current_design_default(self):
        assert ThemeManager.current_design() == 'default'

    def test_set_design_gguf(self):
        ThemeManager.set_design('gguf')
        assert ThemeManager.current_design() == 'gguf'

    def test_gguf_get_color_dark_palette(self):
        ThemeManager.set_design('gguf')
        assert ThemeManager.get_color('bg_primary') == '#10150F'
        assert ThemeManager.get_color('bg_surface') == '#171E16'
        assert ThemeManager.get_color('accent') == '#C9A227'
        assert ThemeManager.get_color('surface_2') == '#202A1E'
        assert ThemeManager.get_color('text_primary') == '#E9E7D9'

    def test_rapid_get_color_light_palette(self):
        ThemeManager.set_design('rapid')
        assert ThemeManager.get_color('bg_primary') == '#F6F3ED'
        assert ThemeManager.get_color('bg_surface') == '#FFFFFF'
        assert ThemeManager.get_color('accent') == '#1E7B5C'
        assert ThemeManager.get_color('surface_2') == '#EFEAE2'
        assert ThemeManager.get_color('text_primary') == '#2A2724'

    def test_unknown_design_raises(self):
        with pytest.raises(ValueError, match="Unknown design"):
            ThemeManager.set_design('nonexistent')

    def test_unknown_role_raises_in_design(self):
        ThemeManager.set_design('gguf')
        with pytest.raises(ValueError, match="Unknown color role"):
            ThemeManager.get_color('nonexistent')

    def test_set_design_triggers_callbacks(self):
        ThemeManager.set_design('default')
        calls = []

        def cb():
            calls.append(1)

        ThemeManager.register_refresh_callback(cb)
        ThemeManager.set_design('gguf')
        assert len(calls) == 1

    def test_set_design_same_is_noop(self):
        ThemeManager.set_design('default')
        calls = []

        def cb():
            calls.append(1)

        ThemeManager.register_refresh_callback(cb)
        ThemeManager.set_design('default')  # 相同设计，不触发回调
        assert calls == []

    def test_gguf_set_theme_noop(self):
        """gguf 固定深色：set_theme('light') 不生效，token 仍取深色值"""
        ThemeManager.set_design('gguf')
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('bg_primary') == '#10150F'
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('bg_primary') == '#10150F'

    def test_rapid_set_theme_noop(self):
        """rapid 固定浅色：set_theme('dark') 不生效，token 仍取浅色值"""
        ThemeManager.set_design('rapid')
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('bg_surface') == '#FFFFFF'

    def test_default_light_dark_regression(self):
        """default 回归：light/dark 切换行为与改造前一致"""
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('primary') == '#2563eb'
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('primary') == '#3b82f6'
        assert ThemeManager.get_color('bg_primary') == '#111827'

    def test_apply_stylesheet_design_palette(self, qapp):
        """apply_stylesheet 在 design 非 default 时用设计调色板解析"""
        widget = QWidget()
        ThemeManager.set_design('gguf')
        ThemeManager.apply_stylesheet(widget, {
            'background-color': 'bg_primary',
            'color': 'text_primary'
        })
        style = widget.styleSheet()
        assert '#10150F' in style
        assert '#E9E7D9' in style

    def test_registered_widget_refreshes_on_design_change(self, qapp):
        """已注册 apply_theme 的组件 set_design 后 QSS 自动重建为设计色"""
        from app.ui.widgets.status_bar import StatusBar
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
        bar = StatusBar()
        assert '#ffffff' in bar.styleSheet()  # default light bg_surface
        ThemeManager.set_design('gguf')
        assert '#171E16' in bar.styleSheet()  # gguf bg_surface
        assert '#2F3B2C' in bar.styleSheet()  # gguf border

    def test_apply_card_shadow(self, qapp):
        widget = QWidget()
        ThemeManager.apply_card_shadow(widget)
        effect = widget.graphicsEffect()
        assert isinstance(effect, QGraphicsDropShadowEffect)
        assert effect.blurRadius() == 12
        assert effect.offset().y() == 2
        c = effect.color()
        assert (c.red(), c.green(), c.blue()) == (15, 23, 42)
        assert c.alpha() == 15  # 0.06 * 255

    def test_radius_design_aware(self):
        ThemeManager.set_design('gguf')
        assert ThemeManager.get_radius('sm') == 2
        assert ThemeManager.get_radius('md') == 4
        assert ThemeManager.get_radius('lg') == 6
        ThemeManager.set_design('rapid')
        assert ThemeManager.get_radius('sm') == 4
        assert ThemeManager.get_radius('lg') == 12
        ThemeManager.set_design('default')
        assert ThemeManager.get_radius('sm') == 4
        assert ThemeManager.get_radius('md') == 8
        assert ThemeManager.get_radius('full') == 9999

    def test_get_font_mono(self, qapp):
        font = ThemeManager.get_font('mono')
        assert font.family() in ('Consolas', 'Courier New')
        assert font.pointSize() == 13

    def test_get_font_unknown_level_still_raises(self):
        with pytest.raises(ValueError, match="Unknown font level"):
            ThemeManager.get_font('nonexistent')


class TestButtonStyleDesign:
    """primary_qss 按设计取 accent 色"""

    def test_primary_qss_accent_per_design(self):
        ThemeManager.set_design('default')
        ThemeManager.set_theme('light')
        assert '#2563eb' in primary_qss()  # default light primary
        ThemeManager.set_design('gguf')
        assert '#C9A227' in primary_qss()  # gguf accent
        ThemeManager.set_design('rapid')
        assert '#1E7B5C' in primary_qss()  # rapid accent

    def test_primary_qss_default_dark_regression(self):
        ThemeManager.set_design('default')
        ThemeManager.set_theme('dark')
        assert '#3b82f6' in primary_qss()  # default dark primary


class TestEngineStatusBand:
    """EngineStatusBand 骨架冒烟（P2 占位色，P6 精修动效）"""

    def test_smoke_three_states(self, qapp):
        band = EngineStatusBand()
        assert band.status() == 'initializing'
        assert band.STATUS_COLORS['initializing'] == '#E0B23C'
        assert band.minimumHeight() == 2
        band.set_status('ready')
        assert band.status() == 'ready'
        assert band.STATUS_COLORS['ready'] == '#8FB573'
        band.set_status('error')
        assert band.status() == 'error'
        assert band.STATUS_COLORS['error'] == '#E2574C'

    def test_unknown_status_raises(self, qapp):
        band = EngineStatusBand()
        with pytest.raises(ValueError, match="Unknown engine status"):
            band.set_status('unknown')

    def test_same_status_noop(self, qapp):
        band = EngineStatusBand()
        band.set_status('ready')
        band.set_status('ready')  # 不抛错、状态不变
        assert band.status() == 'ready'
