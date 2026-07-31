# app/ui/widgets/slidable_panel.py
from PyQt6.QtCore import Qt, QPoint, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.ui.theme_manager import ThemeManager


class SlidablePanel(QWidget):
    """可滑动面板容器（从右侧滑入/滑出）"""

    visible_changed = pyqtSignal(bool)

    def __init__(self, parent=None, panel_width: int = 320,
                 min_width: int = 280, max_width: int = 480):
        super().__init__(parent)
        self._panel_width = panel_width
        self._min_width = min_width
        self._max_width = max_width
        self._is_visible = True
        self._animation = None
        self._content_widget = None
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedWidth(self._panel_width)
        self.setMinimumWidth(self._min_width)
        self.setMaximumWidth(self._max_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部控制栏
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )

        # 标题
        self.title_label = QLabel()
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # 关闭按钮
        self.close_button = QPushButton('✕')
        self.close_button.setFixedSize(24, 24)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {ThemeManager.get_color('error')};
                background-color: {ThemeManager.get_color('bg_hover')};
                border-radius: {ThemeManager.get_radius('sm')}px;
            }}
        """)
        self.close_button.clicked.connect(self.slide_out)
        header_layout.addWidget(self.close_button)

        layout.addWidget(header)

        # 内容区域
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )
        layout.addWidget(self.content_area, stretch=1)

        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
            f"border-left: 1px solid {ThemeManager.get_color('border')};"
        )

    def set_content(self, widget: QWidget):
        """设置内容控件"""
        self._content_widget = widget
        self.content_layout.addWidget(widget)

    def set_title(self, title: str):
        """设置标题"""
        self.title_label.setText(title)

    def slide_in(self):
        """滑入显示"""
        if self._is_visible:
            return
        self._is_visible = True
        self.setVisible(True)

        # 从右侧滑入动画
        parent = self.parent()
        if parent:
            end_x = parent.width() - self.width()
            start_x = parent.width()
            self.move(start_x, self.y())

            self._animation = QPropertyAnimation(self, b"pos")
            self._animation.setDuration(250)
            self._animation.setStartValue(self.pos())
            self._animation.setEndValue(self.pos() + QPoint(end_x - start_x, 0))
            self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._animation.start()

        self.visible_changed.emit(True)

    def slide_out(self):
        """滑出隐藏"""
        if not self._is_visible:
            return
        self._is_visible = False

        # 滑出动画
        parent = self.parent()
        if parent:
            end_x = parent.width()

            self._animation = QPropertyAnimation(self, b"pos")
            self._animation.setDuration(250)
            self._animation.setStartValue(self.pos())
            self._animation.setEndValue(self.pos() + QPoint(end_x - self.x(), 0))
            self._animation.setEasingCurve(QEasingCurve.Type.InCubic)
            self._animation.finished.connect(lambda: self.setVisible(False))
            self._animation.start()
        else:
            self.setVisible(False)

        self.visible_changed.emit(False)

    def is_visible(self) -> bool:
        """是否可见"""
        return self._is_visible
