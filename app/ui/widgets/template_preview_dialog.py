"""
模板预览对话框
用于在加载模板前预览模板内容
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QTableWidget, QTableWidgetItem, QHeaderView
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from qfluentwidgets import BodyLabel, PushButton, SubtitleLabel


class TemplatePreviewDialog(QDialog):
    """模板预览对话框"""

    def __init__(self, template_name: str, template_data: dict, parent=None):
        super().__init__(parent)
        self.template_name = template_name
        self.template_data = template_data
        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("模板预览")
        self.setFixedSize(450, 350)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题区域
        title_layout = QHBoxLayout()
        icon_label = QLabel("📋")
        icon_label.setStyleSheet("font-size: 24px;")
        title_layout.addWidget(icon_label)

        title = SubtitleLabel(f"模板: {self.template_name}")
        title.setStyleSheet("font-weight: bold;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 模板信息
        info_widget = QLabel()
        info_widget.setStyleSheet("""
            background: #f5f5f5;
            border-radius: 8px;
            padding: 12px;
        """)
        regions = self.template_data.get('regions', [])
        created_at = self.template_data.get('created_at', '未知')
        description = self.template_data.get('description', '无描述')

        info_text = f"""
<p style="margin: 0; font-size: 13px;">
    <b>字段数量:</b> {len(regions)} 个<br>
    <b>创建时间:</b> {created_at}<br>
    <b>描述:</b> {description}
</p>
"""
        info_widget.setText(info_text)
        info_widget.setWordWrap(True)
        layout.addWidget(info_widget)

        # 字段列表表格
        fields_title = BodyLabel("字段列表:")
        fields_title.setStyleSheet("font-weight: bold; margin-top: 8px;")
        layout.addWidget(fields_title)

        self.table = QTableWidget()
        self.table.setColumnCount(3)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "OCR模式"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                alternate-background-color: #f5f5f5;
            }
        """)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)

        # 填充字段数据
        self.table.setRowCount(len(regions))
        type_colors = {
            "text": "#0078d4",
            "number": "#107c10",
            "date": "#5c2d91",
            "email": "#008272",
            "phone": "#d83b01",
        }

        for row, region in enumerate(regions):
            # 字段名
            name_item = QTableWidgetItem(region.get('field_name', '未命名'))
            self.table.setItem(row, 0, name_item)

            # 类型
            field_type = region.get('field_type', 'text')
            type_item = QTableWidgetItem(field_type)
            type_item.setForeground(QColor(type_colors.get(field_type, "#333")))
            self.table.setItem(row, 1, type_item)

            # OCR模式
            ocr_mode = region.get('ocr_mode', 'general')
            mode_text = {
                'general': '通用',
                'single_line': '单行',
                'number': '数字'
            }.get(ocr_mode, ocr_mode)
            mode_item = QTableWidgetItem(mode_text)
            self.table.setItem(row, 2, mode_item)

        layout.addWidget(self.table)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_load = PushButton("加载模板")
        self.btn_load.setFixedWidth(100)
        self.btn_load.clicked.connect(self.accept)
        btn_layout.addWidget(self.btn_load)

        btn_layout.addStretch()

        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        # 如果没有字段，显示提示
        if not regions:
            self.table.setVisible(False)
            empty_label = BodyLabel("此模板没有定义任何字段")
            empty_label.setStyleSheet("color: #666; padding: 16px;")
            empty_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            layout.addWidget(empty_label)