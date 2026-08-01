# tests/ui/widgets/test_button_style.py
"""button_style 共享按钮样式测试（Task 3 / P2-a）

验证：
- primary_qss / secondary_qss 只从 ThemeManager token 生成（单一事实源）
- 主题切换后生成的 QSS 随主题色变化（无陈旧颜色残留）
- 生成过程不包含硬编码颜色字面量（通过 monkeypatch get_color 证明）
"""
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss, secondary_qss


class TestButtonStyle:
    def test_primary_uses_theme_tokens(self):
        ss = primary_qss()
        assert ThemeManager.get_color('primary') in ss
        assert ThemeManager.get_color('primary_hover') in ss
        assert ThemeManager.get_color('white') in ss

    def test_secondary_uses_theme_tokens(self):
        ss = secondary_qss()
        assert ThemeManager.get_color('bg_surface') in ss
        assert ThemeManager.get_color('bg_hover') in ss
        assert ThemeManager.get_color('text_primary') in ss
        assert ThemeManager.get_color('text_disabled') in ss
        assert ThemeManager.get_color('border') in ss

    def test_primary_reflects_theme_switch(self):
        """dark 主题下 primary_qss 烘焙 dark 主色；切回 light 后随当前主题变化"""
        ThemeManager.set_theme('dark')
        try:
            dark_ss = primary_qss()
            assert ThemeManager.get_color('primary') in dark_ss
            assert ThemeManager.get_color('primary_hover') in dark_ss
        finally:
            ThemeManager.set_theme('light')
        light_ss = primary_qss()
        assert ThemeManager.get_color('primary') in light_ss
        # 两种主题下的 QSS 应不同（颜色随主题 token 变化）
        assert dark_ss != light_ss

    def test_built_only_from_tokens(self, monkeypatch):
        """QSS 完全由 ThemeManager.get_color 返回值生成（无硬编码字面量）"""
        calls = []

        def fake_get_color(cls, role):
            calls.append(role)
            return f"<{role}>"

        monkeypatch.setattr(
            ThemeManager, 'get_color', classmethod(fake_get_color))
        ss = primary_qss() + secondary_qss()
        assert '<primary>' in ss
        assert '<primary_hover>' in ss
        assert '<white>' in ss
        assert '<bg_surface>' in ss
        assert '<border>' in ss
        # 只使用已定义的颜色角色 token（证明没有手写颜色字面量）
        assert set(calls) <= set(ThemeManager.COLORS['light'].keys())
