# app/ui/widgets/toast_notification.py
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from app.ui.theme_manager import ThemeManager


class ToastNotification(QWidget):
    """轻量通知组件"""

    _instance = None
    _active_toasts = []

    TYPE_COLORS = {
        'success': 'success',
        'warning': 'warning_text',  # 文本/边框用途 → 压暗版；圆点用途仍用 warning
        'error': 'error',
        'info': 'primary',
    }

    TYPE_ICONS = {
        'success': '✓',
        'warning': '⚠',
        'error': '✗',
        'info': 'ℹ',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._animation = None
        self._last_type = None
        self._setup_ui()
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _setup_ui(self):
        self.setFixedWidth(320)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('lg'),
            ThemeManager.get_spacing('md'),
            ThemeManager.get_spacing('lg'),
            ThemeManager.get_spacing('md')
        )
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # 图标
        self.icon_label = QLabel()
        self.icon_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.icon_label)

        # 消息
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(ThemeManager.get_font('body'))
        layout.addWidget(self.message_label, stretch=1)

    def show_message(self, message: str, type: str = 'info', duration: int = 3000):
        """显示通知"""
        self._last_type = type
        self.icon_label.setText(self.TYPE_ICONS.get(type, 'ℹ'))
        self.message_label.setText(message)
        self.apply_theme()

        # 定位到右下角
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.width() - self.width() - ThemeManager.get_spacing('lg')
            y = parent_rect.height() - self.height() - ThemeManager.get_spacing('lg')
            # 考虑已有 toast 的偏移
            offset = len(ToastNotification._active_toasts) * (self.height() + ThemeManager.get_spacing('sm'))
            self.move(x, y - offset)

        # 注意：不能用 self.show()，类方法 show 会遮蔽 QWidget.show
        super().show()

        # 入场动画
        self._animation = QPropertyAnimation(self, b"pos")
        self._animation.setDuration(150)
        self._animation.setStartValue(QPoint(self.x(), self.y() + 20))
        self._animation.setEndValue(QPoint(self.x(), self.y()))
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

        # 自动消失
        QTimer.singleShot(duration, self._hide)

        ToastNotification._active_toasts.append(self)

    def apply_theme(self):
        """重建通知样式（Task 15：ThemeManager.set_theme 后调用；
        未显示过时仅重设图标/消息颜色样式）"""
        color_role = self.TYPE_COLORS.get(self._last_type or 'info', 'primary')
        color = ThemeManager.get_color(color_role)
        self.icon_label.setStyleSheet(
            f"font-size: 16px; color: {color};"
        )
        self.message_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-left: 4px solid {color};
                border-radius: {ThemeManager.get_radius('md')}px;
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)

    def _hide(self):
        """隐藏通知（带动画）"""
        if self in ToastNotification._active_toasts:
            ToastNotification._active_toasts.remove(self)

        self._animation = QPropertyAnimation(self, b"windowOpacity")
        self._animation.setDuration(200)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._animation.finished.connect(self.close)
        self._animation.start()

    @classmethod
    def show(cls, message: str, type: str = 'info', duration: int = 3000, parent=None):
        """类方法：快速显示通知"""
        toast = cls(parent)
        toast.show_message(message, type, duration)
        return toast
