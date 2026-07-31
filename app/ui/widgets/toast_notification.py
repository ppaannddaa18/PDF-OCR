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
        'warning': 'warning',
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
        self._setup_ui()
        self._animation = None

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
        color_role = self.TYPE_COLORS.get(type, 'primary')
        color = ThemeManager.get_color(color_role)
        icon = self.TYPE_ICONS.get(type, 'ℹ')

        self.icon_label.setText(icon)
        self.message_label.setText(message)
        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-left: 4px solid {color};
                border-radius: {ThemeManager.get_radius('md')}px;
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)

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
