from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView
)
from PyQt6.QtCore import pyqtSignal as Signal, Qt
from PyQt6.QtGui import QColor, QBrush
from qfluentwidgets import SubtitleLabel, PushButton, ComboBox, BodyLabel
from app.models.region import Region
from app.models.template import Template


class FieldPanel(QWidget):
    region_changed = Signal(list)          # List[Region]
    region_deleted = Signal(str)           # region_id

    # 字段类型颜色映射
    TYPE_COLORS = {
        "text": "#0078d4",
        "number": "#107c10",
        "date": "#5c2d91",
        "email": "#008272",
        "phone": "#d83b01",
    }

    def __init__(self):
        super().__init__()
        self.regions = {}   # id -> Region
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Fluent 标签
        layout.addWidget(SubtitleLabel("字段配置"))

        # 空状态提示
        self.empty_label = BodyLabel("暂无字段\n在 PDF 画布上拖拽框选区域")
        self.empty_label.setStyleSheet("color: #888; text-align: center;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.empty_label.setMinimumHeight(100)
        layout.addWidget(self.empty_label)

        # 字段表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "识别结果", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                alternate-background-color: #f5f5f5;
            }
        """)
        layout.addWidget(self.table, 1)

        # 操作按钮
        btn_clear = PushButton("清空所有字段")
        btn_clear.clicked.connect(self.clear_all)
        layout.addWidget(btn_clear)

        self._update_empty_state()

    def _update_empty_state(self):
        has_fields = len(self.regions) > 0
        self.empty_label.setVisible(not has_fields)
        self.table.setVisible(has_fields)

    def add_region(self, region: Region):
        self.regions[region.id] = region
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 字段名（可编辑）- 带颜色标识
        name_item = QTableWidgetItem(region.field_name)
        name_item.setForeground(QBrush(QColor(region.color)))
        name_item.setData(Qt.ItemDataRole.UserRole, region.id)
        self.table.setItem(row, 0, name_item)

        # Fluent 下拉框
        type_combo = ComboBox()
        type_combo.addItems(["text", "number", "date", "email", "phone"])
        type_combo.setCurrentText(region.field_type)
        self.table.setCellWidget(row, 1, type_combo)

        # 识别结果（初始为空）
        self.table.setItem(row, 2, QTableWidgetItem(""))

        # Fluent 删除按钮
        btn = PushButton("删除")
        btn.clicked.connect(lambda _, rid=region.id: self._delete(rid))
        self.table.setCellWidget(row, 3, btn)

        self._update_empty_state()

    def _delete(self, region_id):
        if region_id in self.regions:
            del self.regions[region_id]
        # 找到并删除对应行
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.table.removeRow(row)
                break
        self.region_deleted.emit(region_id)
        self._update_empty_state()

    def clear_all(self):
        self.regions.clear()
        self.table.setRowCount(0)
        self.region_changed.emit([])
        self._update_empty_state()

    def build_template(self) -> Template:
        regions = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid not in self.regions:
                continue
            r = self.regions[rid]
            r.field_name = item.text()
            combo = self.table.cellWidget(row, 1)
            if combo:
                r.field_type = combo.currentText()
            regions.append(r)
        return Template(name="current", regions=regions)

    def load_template(self, template: Template):
        self.clear_all()
        for r in template.regions:
            self.add_region(r)
        self.region_changed.emit(list(self.regions.values()))

    def show_preview_result(self, file_result):
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            name = item.text()
            if name in file_result.fields:
                fr = file_result.fields[name]
                result_item = QTableWidgetItem(fr.text)
                if fr.confidence < 0.7:
                    result_item.setBackground(QColor("#FFE5E5"))
                    result_item.setToolTip(f"置信度: {fr.confidence:.2%}")
                else:
                    result_item.setToolTip(f"置信度: {fr.confidence:.2%}")
                self.table.setItem(row, 2, result_item)