# app/ui/widgets/empty_state.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QFont
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss


# qtawesome 延迟加载（避免启动开销与字体警告）
_qta = None


def _get_qta():
    """获取 qtawesome 实例（延迟加载）"""
    global _qta
    if _qta is None:
        import qtawesome
        _qta = qtawesome
    return _qta


class EmptyState(QWidget):
    """统一空状态组件"""

    # 预定义变体配置
    VARIANTS = {
        'no_files': {
            'icon': 'fa5s.file-pdf',
            'title': '暂无 PDF 文件',
            'description': '点击上方「上传」按钮或拖拽 PDF 文件到此处',
            'action': '上传 PDF',
        },
        'no_preview': {
            'icon': 'fa5s.eye',
            'title': 'PDF 预览区域',
            'description': '上传 PDF 后在此显示',
            'action': None,
        },
        'no_fields': {
            'icon': 'fa5s.edit',
            'title': '暂无识别字段',
            'description': '在 PDF 预览中框选区域以添加字段',
            'action': None,
        },
        'no_results': {
            'icon': 'fa5s.chart-bar',
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
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _setup_ui(self):
        self._icon_name = None
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
        layout.addWidget(self.title_label)

        # 说明
        self.desc_label = QLabel()
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setFont(ThemeManager.get_font('body'))
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        # 操作按钮
        self.action_button = QPushButton()
        self.action_button.setFont(ThemeManager.get_font('button'))
        self.action_button.setVisible(False)
        layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用）"""
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        self.desc_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        # P2-a: 主操作按钮样式复用共享 single-source 样式（与导出/解析一致）
        self.action_button.setStyleSheet(primary_qss())
        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
        )
        self._update_icon()

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
        else:
            self.action_button.setVisible(False)

    def set_icon(self, icon_name: str):
        """设置图标（QtAwesome 图标名，如 'fa5s.file-pdf'）"""
        self._icon_name = icon_name
        self._update_icon()

    def _update_icon(self):
        """按当前主题色重绘 48px 图标"""
        name = self._icon_name or 'fa5s.file'
        self.icon_label.setPixmap(_get_qta().icon(
            name, color=ThemeManager.get_color('text_secondary')).pixmap(48, 48))

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
