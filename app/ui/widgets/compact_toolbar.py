# app/ui/widgets/compact_toolbar.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QPushButton, QComboBox, QLabel,
)
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.gpu_status import GpuStatusWidget


class CompactToolbar(QWidget):
    """紧凑工具栏"""

    # 信号
    upload_clicked = pyqtSignal()
    test_ocr_clicked = pyqtSignal()
    batch_ocr_clicked = pyqtSignal()
    save_template_clicked = pyqtSignal()
    load_template_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    engine_changed = pyqtSignal(str)
    nav_toggle_clicked = pyqtSignal()  # 切换版面导航图显示/隐藏

    ENGINE_OPTIONS = [
        '本地 GPU (GGUF)',
        '本地 CPU (GGUF)',
        'CPU (RapidOCR)',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._icon_buttons = []  # 主题化图标按钮（apply_theme 时重建 QSS）
        self._separators = []    # 主题化分隔线（apply_theme 时重建 QSS）
        self._captions = []      # 分组 caption（apply_theme 时统一上色）
        self._setup_ui()
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _setup_ui(self):
        self.setFixedHeight(36)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            0
        )
        layout.setSpacing(ThemeManager.get_spacing('xs'))

        # 主要操作组（caption: 操作）
        self._add_caption(layout, '操作')
        self._create_icon_button(layout, '⬆️', '上传 PDF (Ctrl+O)', self.upload_clicked)
        self._create_icon_button(layout, '🔍', '试识别 (Ctrl+T)', self.test_ocr_clicked)
        self._create_icon_button(layout, '▶️', '批量识别 (Ctrl+Enter)', self.batch_ocr_clicked)

        # 分隔线（加宽周围间距强化分组）
        self._add_separator_with_spacing(layout)

        # 模板操作组（caption: 模板）
        self._add_caption(layout, '模板')
        self._create_icon_button(layout, '💾', '保存模板 (Ctrl+S)', self.save_template_clicked)
        self._create_icon_button(layout, '📂', '加载模板', self.load_template_clicked)

        # 分隔线（加宽周围间距强化分组）
        self._add_separator_with_spacing(layout)

        # 推理后端组（caption: 推理后端: + GpuStatusWidget 圆点并入其旁 + 引擎选择）
        self.engine_caption = QLabel('推理后端:')
        self.engine_caption.setFont(ThemeManager.get_font('caption'))
        layout.addWidget(self.engine_caption)
        self._captions.append(self.engine_caption)

        # 引擎状态（集成 GpuStatusWidget：彩色圆点 + 引擎缩写）
        self.engine_status = GpuStatusWidget()
        layout.addWidget(self.engine_status)

        # 引擎选择
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(self.ENGINE_OPTIONS)
        self.engine_combo.setFixedWidth(140)
        self.engine_combo.currentTextChanged.connect(self.engine_changed.emit)
        layout.addWidget(self.engine_combo)

        layout.addStretch()

        # 导航图切换按钮（仅 VLM 模式显示，由主窗口 _switch_ui_mode 控制显隐）
        self.nav_toggle_btn = self._create_icon_button(
            layout, '🗺', '切换版面导航图', self.nav_toggle_clicked)

        # 设置按钮
        self._create_icon_button(layout, '⚙️', '设置', self.settings_clicked)

        # 帮助按钮
        help_btn = QPushButton('?')
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip('快捷键帮助 (F1)')
        layout.addWidget(help_btn)
        self._help_btn = help_btn

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用）"""
        self.setStyleSheet(f"""
            CompactToolbar {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        self.engine_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('sm')}px;
                padding: 2px 4px;
                font-size: 12px;
            }}
            QComboBox:focus {{
                border-color: {ThemeManager.get_color('border_focus')};
            }}
        """)
        self._help_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('full')}px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)
        for btn in self._icon_buttons:
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: {ThemeManager.get_radius('sm')}px;
                    font-size: 14px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeManager.get_color('bg_hover')};
                }}
                QPushButton:pressed {{
                    background-color: {ThemeManager.get_color('bg_selected')};
                }}
            """)
        for separator in self._separators:
            separator.setStyleSheet(
                f"background-color: {ThemeManager.get_color('border')};"
            )
        for caption in self._captions:
            caption.setStyleSheet(
                f"color: {ThemeManager.get_color('text_secondary')};"
            )

    def _create_icon_button(self, layout, icon: str, tooltip: str, signal):
        """创建图标按钮"""
        btn = QPushButton(icon)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(signal.emit)
        layout.addWidget(btn)
        self._icon_buttons.append(btn)
        return btn

    def _add_caption(self, layout, text: str):
        """添加分组 caption（ThemeManager caption 字体；apply_theme 时统一上色）"""
        label = QLabel(text)
        label.setFont(ThemeManager.get_font('caption'))
        layout.addWidget(label)
        self._captions.append(label)
        return label

    def _add_separator_with_spacing(self, layout):
        """添加分隔线并加宽周围间距（强化分组）"""
        gap = ThemeManager.get_spacing('lg')
        layout.addSpacing(gap)
        self._add_separator(layout)
        layout.addSpacing(gap)

    def _add_separator(self, layout):
        """添加分隔线"""
        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setFixedHeight(20)
        layout.addWidget(separator)
        self._separators.append(separator)

    def set_engine_status(self, engine: str, status: str):
        """设置引擎状态

        Args:
            engine: 引擎名称
            status: 'ready', 'initializing', 'unavailable', 'cpu_mode'
        """
        # 委托给集成的 GpuStatusWidget（彩色圆点 + 缩写）
        self.engine_status.set_engine_status(engine, status)
