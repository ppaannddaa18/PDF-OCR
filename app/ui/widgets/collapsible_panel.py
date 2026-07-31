# app/ui/widgets/collapsible_panel.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.ui.animation_manager import AnimationManager
from app.ui.theme_manager import ThemeManager


class CollapsiblePanel(QWidget):
    """可折叠面板容器"""

    collapsed_changed = pyqtSignal(bool)  # True = collapsed

    def __init__(self, parent=None, expanded_width: int = 240, collapsed_width: int = 48):
        super().__init__(parent)
        self._expanded_width = expanded_width
        self._collapsed_width = collapsed_width
        self._is_collapsed = False
        self._animations = []  # 保留两个动画引用，防止被 Python GC 回收导致动画不运行
        self._content_widget = None
        self._setup_ui()

    def _setup_ui(self):
        # 不用 setFixedWidth：显式设置最小/最大宽度，与宽度动画兼容
        self.setMinimumWidth(self._expanded_width)
        self.setMaximumWidth(self._expanded_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 折叠按钮
        self.toggle_button = QPushButton('◀')
        self.toggle_button.setFixedSize(24, 24)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {ThemeManager.get_color('text_primary')};
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
        """)
        self.toggle_button.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_button, alignment=Qt.AlignmentFlag.AlignRight)

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

        # 折叠状态指示
        self.collapsed_indicator = QLabel()
        self.collapsed_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collapsed_indicator.setStyleSheet(f"""
            color: {ThemeManager.get_color('text_secondary')};
            font-size: 11px;
        """)
        self.collapsed_indicator.setVisible(False)
        layout.addWidget(self.collapsed_indicator)

        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
        )

    def set_content(self, widget: QWidget):
        """设置内容控件"""
        self._content_widget = widget
        self.content_layout.addWidget(widget)

    def collapse(self):
        """折叠面板"""
        if self._is_collapsed:
            return
        self._is_collapsed = True

        # 隐藏内容
        self.content_area.setVisible(False)
        self.collapsed_indicator.setVisible(True)

        # 更新指示器
        if self._content_widget:
            # 显示内容数量或标识
            self.collapsed_indicator.setText('📄')

        # 动画
        self._animate_width(self._expanded_width, self._collapsed_width)
        self.toggle_button.setText('▶')
        self.collapsed_changed.emit(True)

    def expand(self):
        """展开面板"""
        if not self._is_collapsed:
            return
        self._is_collapsed = False

        # 显示内容
        self.content_area.setVisible(True)
        self.collapsed_indicator.setVisible(False)

        # 动画
        self._animate_width(self._collapsed_width, self._expanded_width)
        self.toggle_button.setText('◀')
        self.collapsed_changed.emit(False)

    def toggle(self):
        """切换折叠状态"""
        if self._is_collapsed:
            self.expand()
        else:
            self.collapse()

    def is_collapsed(self) -> bool:
        """是否已折叠"""
        return self._is_collapsed

    def _animate_width(self, start_width: int, end_width: int):
        """宽度动画

        同时动画 minimumWidth 和 maximumWidth，保证折叠/展开后宽度真实变化到目标值：
        - 折叠时 maximumWidth 先低于当前宽度，驱动宽度收窄
        - 展开时 minimumWidth 先高于当前宽度，驱动宽度展宽
        """
        # 停止可能仍在运行的旧动画，避免新旧动画相互覆盖属性值
        for anim in self._animations:
            anim.stop()
        self._animations = []

        # 经 AnimationManager 统一创建（禁用时直接设置最终值并返回 None，无需保留引用）
        for prop in (b"minimumWidth", b"maximumWidth"):
            anim = AnimationManager.animate(self, prop, start_width, end_width)
            if anim is not None:
                self._animations.append(anim)
