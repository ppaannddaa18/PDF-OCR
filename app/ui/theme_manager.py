# app/ui/theme_manager.py
import types
import weakref

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget


class ThemeManager:
    """主题管理器 - 集中管理所有视觉常量

    Task 15 增强：
    - 刷新回调注册表：组件在 __init__ 时注册 apply_theme（弱引用），
      set_theme 切换主题后自动调用全部回调，使构造时烘焙进 QSS 字符串的
      颜色重新生成（unpolish/polish 不足以刷新内嵌样式表）
    - detect_system_theme / resolve_theme：'auto' 模式跟随系统主题
      （Qt 6.5+ QStyleHints.colorScheme()，已验证 PyQt6 6.11 可用）
    """

    _current_theme = 'light'
    _refresh_callbacks = []  # weakref.WeakMethod / weakref.ref 列表（组件销毁后自动失效）

    COLORS = {
        'light': {
            'bg_primary': '#f8f9fa',
            'bg_surface': '#ffffff',
            'bg_hover': '#f3f4f6',
            'bg_selected': '#eff6ff',
            'primary': '#2563eb',
            'primary_hover': '#1d4ed8',
            'white': '#ffffff',
            'success': '#16a34a',
            'warning': '#f59e0b',
            'warning_text': '#b45309',
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
            'white': '#ffffff',
            'success': '#22c55e',
            'warning': '#fbbf24',
            'warning_text': '#fbbf24',
            'error': '#ef4444',
            'text_primary': '#f9fafb',
            'text_secondary': '#d1d5db',
            'text_disabled': '#9ca3af',
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

    # ── 主题切换与全局刷新 ──────────────────────────────────────

    @classmethod
    def register_refresh_callback(cls, callback) -> None:
        """注册主题刷新回调：set_theme 切换主题后自动调用

        回调以弱引用持有（WeakMethod/ref），组件被 GC 后自动失效，
        无需显式注销。典型用法：组件 __init__ 末尾
        ``ThemeManager.register_refresh_callback(self.apply_theme)``。
        """
        if callback is None:
            return
        if isinstance(callback, types.MethodType):
            ref = weakref.WeakMethod(callback)
        else:
            ref = weakref.ref(callback)
        cls._refresh_callbacks.append(ref)

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """设置当前主题，并触发全部已注册的刷新回调

        相同主题重复调用为 no-op（组件构造/刷新后状态已一致，
        避免启动双接线时重复刷新）。
        """
        if theme not in cls.COLORS:
            raise ValueError(f"Unknown theme: {theme}")
        if theme == cls._current_theme:
            return
        cls._current_theme = theme
        cls._invoke_refresh_callbacks()

    @classmethod
    def _invoke_refresh_callbacks(cls) -> None:
        """调用全部刷新回调；失效（已销毁）回调在本轮清理"""
        dead = []
        for ref in cls._refresh_callbacks:
            callback = ref()
            if callback is None:
                dead.append(ref)
                continue
            try:
                callback()
            except RuntimeError:
                # 组件 C++ 对象已销毁，标记清理
                dead.append(ref)
            except Exception:
                # 单个组件刷新失败不应阻断其余组件
                pass
        for ref in dead:
            try:
                cls._refresh_callbacks.remove(ref)
            except ValueError:
                pass

    # ── 系统主题检测（'auto' 跟随系统） ─────────────────────────

    @classmethod
    def detect_system_theme(cls) -> str:
        """检测系统主题（'light' | 'dark'）

        Qt 6.5+：QApplication.styleHints().colorScheme() 返回
        Qt.ColorScheme（Unknown/Light/Dark）——已验证 PyQt6 6.11 可用。
        API 不可用或检测失败时回退 'light'（与旧行为一致）。
        """
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return 'light'
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return 'dark'
            return 'light'
        except Exception:
            return 'light'

    @classmethod
    def resolve_theme(cls, mode: str) -> str:
        """解析主题模式 → 实际生效主题

        'auto' → 跟随系统（detect_system_theme）；
        'light'/'dark' → 原样返回。
        """
        if mode == 'auto':
            return cls.detect_system_theme()
        if mode not in cls.COLORS:
            raise ValueError(f"Unknown theme: {mode}")
        return mode

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
