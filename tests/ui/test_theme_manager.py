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

    # ── Task 5 (P3) 对比度 ───────────────────────────────────

    @staticmethod
    def _relative_luminance(hex_color: str) -> float:
        """WCAG 相对亮度（sRGB 线性化）"""
        def channel(c):
            v = int(c, 16) / 255.0
            return v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
        r, g, b = hex_color[1:3], hex_color[3:5], hex_color[5:7]
        return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)

    @classmethod
    def _contrast_ratio(cls, fg: str, bg: str) -> float:
        l1, l2 = cls._relative_luminance(fg), cls._relative_luminance(bg)
        if l1 < l2:
            l1, l2 = l2, l1
        return (l1 + 0.05) / (l2 + 0.05)

    def test_warning_text_role(self):
        # warning（圆点，亮色）与 warning_text（文本用途，压暗）两角色共存
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('warning') == '#f59e0b'
        assert ThemeManager.get_color('warning_text') == '#b45309'
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('warning_text') == '#fbbf24'

    def test_dark_disabled_text_contrast_meets_aa(self):
        """P3: dark text_disabled on bg_surface 对比度必须 ≥ 4.5:1"""
        ThemeManager.set_theme('dark')
        fg = ThemeManager.get_color('text_disabled')
        bg = ThemeManager.get_color('bg_surface')
        assert self._contrast_ratio(fg, bg) >= 4.5

    def test_light_warning_text_contrast_meets_aa(self):
        """P3: light warning_text on white 对比度必须 ≥ 4.5:1（文本用途可读）"""
        ThemeManager.set_theme('light')
        fg = ThemeManager.get_color('warning_text')
        bg = ThemeManager.get_color('bg_surface')
        assert self._contrast_ratio(fg, bg) >= 4.5

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
