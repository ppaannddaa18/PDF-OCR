# app/ui/widgets/empty_state.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QFont
from app.ui.theme_manager import ThemeManager


class EmptyState(QWidget):
    """统一空状态组件"""

    # 预定义变体配置
    VARIANTS = {
        'no_files': {
            'icon': '📄',
            'title': '暂无 PDF 文件',
            'description': '点击上方「上传」按钮或拖拽 PDF 文件到此处',
            'action': '上传 PDF',
        },
        'no_preview': {
            'icon': '👁️',
            'title': 'PDF 预览区域',
            'description': '上传 PDF 后在此显示',
            'action': None,
        },
        'no_fields': {
            'icon': '✏️',
            'title': '暂无识别字段',
            'description': '在 PDF 预览中框选区域以添加字段',
            'action': None,
        },
        'no_results': {
            'icon': '📊',
            'title': '暂无解析结果',
            'description': '点击「试识别」或「批量识别」开始解析',
            'action': '试识别',
        },
    }

    def __init__(self, variant: str = None, parent=None):
        super().__init__(parent)
        self._setup_ui()
        if variant:
            self.apply_variant(variant)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(ThemeManager.get_spacing('md'))

        # 图标
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = ThemeManager.get_font('heading')
        font.setPointSize(48)
        self.icon_label.setFont(font)
        layout.addWidget(self.icon_label)

        # 标题
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        layout.addWidget(self.title_label)

        # 说明
        self.desc_label = QLabel()
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setFont(ThemeManager.get_font('body'))
        self.desc_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        # 操作按钮
        self.action_button = QPushButton()
        self.action_button.setFont(ThemeManager.get_font('button'))
        self.action_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: white;
                border: none;
                border-radius: {ThemeManager.get_radius('md')}px;
                padding: {ThemeManager.get_spacing('sm')}px {ThemeManager.get_spacing('lg')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)
        self.action_button.setVisible(False)
        layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # 设置背景
        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
        )

    def apply_variant(self, variant: str):
        """应用预定义变体"""
        if variant not in self.VARIANTS:
            raise ValueError(f"Unknown variant: {variant}")
        config = self.VARIANTS[variant]
        self.set_icon(config['icon'])
        self.set_title(config['title'])
        self.set_description(config['description'])
        if config['action']:
            self.set_action(config['action'], lambda: None)

    def set_icon(self, icon_name: str):
        """设置图标"""
        self.icon_label.setText(icon_name)

    def set_title(self, title: str):
        """设置标题"""
        self.title_label.setText(title)

    def set_description(self, description: str):
        """设置说明"""
        self.desc_label.setText(description)

    def set_action(self, text: str, callback: callable):
        """设置操作按钮"""
        self.action_button.setText(text)
        self.action_button.clicked.connect(callback)
        self.action_button.setVisible(True)
