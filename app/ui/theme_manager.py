# app/ui/theme_manager.py
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget


class ThemeManager:
    """主题管理器 - 集中管理所有视觉常量"""

    _current_theme = 'light'

    COLORS = {
        'light': {
            'bg_primary': '#f8f9fa',
            'bg_surface': '#ffffff',
            'bg_hover': '#f3f4f6',
            'bg_selected': '#eff6ff',
            'primary': '#2563eb',
            'primary_hover': '#1d4ed8',
            'success': '#16a34a',
            'warning': '#f59e0b',
            'error': '#dc2626',
            'text_primary': '#1f2937',
            'text_secondary': '#6b7280',
            'text_disabled': '#9ca3af',
            'border': '#e5e7eb',
            'border_focus': '#2563eb',
        },
        'dark': {
            'bg_primary': '#111827',
            'bg_surface': '#1f2937',
            'bg_hover': '#374151',
            'bg_selected': '#1e3a5f',
            'primary': '#3b82f6',
            'primary_hover': '#2563eb',
            'success': '#22c55e',
            'warning': '#fbbf24',
            'error': '#ef4444',
            'text_primary': '#f9fafb',
            'text_secondary': '#d1d5db',
            'text_disabled': '#6b7280',
            'border': '#374151',
            'border_focus': '#3b82f6',
        }
    }

    FONTS = {
        'heading': {'size': 18, 'weight': 600, 'line_height': 1.4},
        'subheading': {'size': 14, 'weight': 500, 'line_height': 1.4},
        'body': {'size': 13, 'weight': 400, 'line_height': 1.5},
        'caption': {'size': 11, 'weight': 400, 'line_height': 1.4},
        'button': {'size': 13, 'weight': 500, 'line_height': 1.0},
    }

    SPACING = {
        'xs': 4,
        'sm': 8,
        'md': 12,
        'lg': 16,
        'xl': 24,
        '2xl': 32,
    }

    RADIUS = {
        'sm': 4,
        'md': 8,
        'lg': 12,
        'full': 9999,
    }

    @classmethod
    def get_color(cls, role: str) -> str:
        """获取当前主题下的颜色值"""
        theme = cls._current_theme
        if role not in cls.COLORS[theme]:
            raise ValueError(f"Unknown color role: {role}")
        return cls.COLORS[theme][role]

    @classmethod
    def get_font(cls, level: str) -> QFont:
        """获取指定层级的字体"""
        if level not in cls.FONTS:
            raise ValueError(f"Unknown font level: {level}")
        config = cls.FONTS[level]
        font = QFont()
        font.setPointSize(config['size'])
        font.setWeight(config['weight'])
        return font

    @classmethod
    def get_spacing(cls, name: str) -> int:
        """获取间距值"""
        if name not in cls.SPACING:
            raise ValueError(f"Unknown spacing name: {name}")
        return cls.SPACING[name]

    @classmethod
    def get_radius(cls, name: str) -> int:
        """获取圆角值"""
        if name not in cls.RADIUS:
            raise ValueError(f"Unknown radius name: {name}")
        return cls.RADIUS[name]

    @classmethod
    def current_theme(cls) -> str:
        """获取当前主题名称"""
        return cls._current_theme

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """设置当前主题"""
        if theme not in cls.COLORS:
            raise ValueError(f"Unknown theme: {theme}")
        cls._current_theme = theme

    @classmethod
    def apply_stylesheet(cls, widget: QWidget, styles: dict) -> None:
        """应用样式到控件

        Args:
            widget: 目标控件
            styles: 样式字典，如 {'background': 'bg_primary', 'color': 'text_primary'}
                   值如果是颜色角色名，会自动解析为实际颜色值
        """
        style_parts = []
        for prop, value in styles.items():
            # 如果值是颜色角色名，解析为实际颜色
            if value in cls.COLORS[cls._current_theme]:
                value = cls.get_color(value)
            style_parts.append(f"{prop}: {value};")
        widget.setStyleSheet("".join(style_parts))
