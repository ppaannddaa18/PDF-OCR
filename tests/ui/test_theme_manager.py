import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from app.ui.theme_manager import ThemeManager


class TestThemeManager:
    def test_get_color_light_theme(self):
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('primary') == '#2563eb'
        assert ThemeManager.get_color('bg_primary') == '#f8f9fa'

    def test_get_color_dark_theme(self):
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('primary') == '#3b82f6'
        assert ThemeManager.get_color('bg_primary') == '#111827'

    def test_get_color_white(self):
        # white 角色为跨主题通用颜色（组件按钮文字使用，禁止硬编码）
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('white') == '#ffffff'
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('white') == '#ffffff'

    def test_get_color_unknown_role(self):
        with pytest.raises(ValueError, match="Unknown color role"):
            ThemeManager.get_color('nonexistent')

    def test_get_font(self):
        font = ThemeManager.get_font('heading')
        assert font.pointSize() == 18
        assert font.weight() == 600

    def test_get_font_unknown_level(self):
        with pytest.raises(ValueError, match="Unknown font level"):
            ThemeManager.get_font('nonexistent')

    def test_get_spacing(self):
        assert ThemeManager.get_spacing('xs') == 4
        assert ThemeManager.get_spacing('lg') == 16

    def test_get_radius(self):
        assert ThemeManager.get_radius('sm') == 4
        assert ThemeManager.get_radius('full') == 9999

    def test_current_theme(self):
        ThemeManager.set_theme('light')
        assert ThemeManager.current_theme() == 'light'
        ThemeManager.set_theme('dark')
        assert ThemeManager.current_theme() == 'dark'

    def test_set_theme_invalid(self):
        with pytest.raises(ValueError, match="Unknown theme"):
            ThemeManager.set_theme('invalid')

    def test_apply_stylesheet(self, qapp):
        widget = QWidget()
        ThemeManager.set_theme('light')
        ThemeManager.apply_stylesheet(widget, {
            'background-color': 'bg_primary',
            'color': 'text_primary'
        })
        style = widget.styleSheet()
        assert '#f8f9fa' in style
        assert '#1f2937' in style
