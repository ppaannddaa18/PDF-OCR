# app/ui/widgets/button_style.py
"""共享按钮样式生成器（Task 3 / P2-a 单一事实源）

primary_qss() / secondary_qss() 只从 ThemeManager token 生成 QSS，
消除 result_panel / empty_state / main_window 中重复的内联主按钮样式，
保证「解析」/「导出」等主操作按钮层级与外观一致。

仅依赖 app.ui.theme_manager，无循环导入风险。
"""
from app.ui.theme_manager import ThemeManager


def primary_qss() -> str:
    """主操作按钮 QSS（primary 背景 + white 文字 + md 圆角 + sm/lg 内边距）

    按钮几何（固定高度/宽度）由调用方负责，样式只描述外观。
    """
    return f"""
        QPushButton {{
            background-color: {ThemeManager.get_color('primary')};
            color: {ThemeManager.get_color('white')};
            border: none;
            border-radius: {ThemeManager.get_radius('md')}px;
            padding: {ThemeManager.get_spacing('sm')}px
                     {ThemeManager.get_spacing('lg')}px;
        }}
        QPushButton:hover {{
            background-color: {ThemeManager.get_color('primary_hover')};
        }}
        QPushButton:focus {{
            /* 焦点环：primary 底色上用白环保证键盘导航可见性 */
            border: 1px solid {ThemeManager.get_color('white')};
        }}
        QPushButton:disabled {{
            background-color: {ThemeManager.get_color('bg_hover')};
            color: {ThemeManager.get_color('text_disabled')};
        }}
    """


def secondary_qss() -> str:
    """次级按钮 QSS（bg_surface 背景 + 边框 + 文字主色 + bg_hover 悬停）"""
    return f"""
        QPushButton {{
            background-color: {ThemeManager.get_color('bg_surface')};
            color: {ThemeManager.get_color('text_primary')};
            border: 1px solid {ThemeManager.get_color('border')};
            border-radius: {ThemeManager.get_radius('sm')}px;
            padding: {ThemeManager.get_spacing('xs')}px
                     {ThemeManager.get_spacing('md')}px;
        }}
        QPushButton:hover {{
            background-color: {ThemeManager.get_color('bg_hover')};
        }}
        QPushButton:focus {{
            border-color: {ThemeManager.get_color('border_focus')};
        }}
        QPushButton:disabled {{
            color: {ThemeManager.get_color('text_disabled')};
        }}
    """
