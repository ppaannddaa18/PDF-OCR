# app/ui/widgets/slidable_panel.py
from PyQt6.QtCore import Qt, QPoint, QEasingCurve, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.ui.animation_manager import AnimationManager
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
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _setup_ui(self):
        self.setMinimumWidth(self._min_width)
        self.setMaximumWidth(self._max_width)
        # 显式设置初始宽度为 panel_width（在 [min, max] 范围内合法）。
        # 不能用 setFixedWidth：其固定约束会被后续 min/max 覆盖，show 时
        # 布局激活会把宽度塌缩回 minimumWidth，导致 panel_width 参数失效。
        self.resize(self._panel_width, self.height())

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
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # 关闭按钮
        self.close_button = QPushButton('✕')
        self.close_button.setFixedSize(24, 24)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
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

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用）"""
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
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

            self._animation = AnimationManager.animate(
                self, b"pos", self.pos(), self.pos() + QPoint(end_x - start_x, 0),
                duration=250, easing=QEasingCurve.Type.OutCubic)

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

            self._animation = AnimationManager.animate(
                self, b"pos", self.pos(), self.pos() + QPoint(end_x - self.x(), 0),
                duration=250, easing=QEasingCurve.Type.InCubic)
            if self._animation is not None:
                self._animation.finished.connect(lambda: self.setVisible(False))
            else:
                # 动画禁用时 animate 直接设置最终值并返回 None，立即隐藏
                self.setVisible(False)
        else:
            self.setVisible(False)

        self.visible_changed.emit(False)

    def is_visible(self) -> bool:
        """是否可见"""
        return self._is_visible
