from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QHeaderView, QLabel
)
from PySide6.QtCore import Signal
from PySide6.QtGui import QColor
from app.models.region import Region
from app.models.template import Template


class FieldPanel(QWidget):
    region_changed = Signal(list)          # List[Region]
    region_deleted = Signal(str)           # region_id

    def __init__(self):
        super().__init__()
        self.regions = {}   # id -> Region
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("字段配置"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "识别结果", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_clear = QPushButton("清空所有字段")
        btn_clear.clicked.connect(self.clear_all)
        layout.addWidget(btn_clear)

    def add_region(self, region: Region):
        self.regions[region.id] = region
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 字段名（可编辑）
        self.table.setItem(row, 0, QTableWidgetItem(region.field_name))

        # 类型下拉
        type_combo = QComboBox()
        type_combo.addItems(["text", "number", "date", "email", "phone"])
        type_combo.setCurrentText(region.field_type)
        self.table.setCellWidget(row, 1, type_combo)

        # 识别结果（初始为空）
        self.table.setItem(row, 2, QTableWidgetItem(""))

        # 删除按钮
        btn = QPushButton("删除")
        btn.clicked.connect(lambda _, rid=region.id: self._delete(rid))
        self.table.setCellWidget(row, 3, btn)

        self.table.item(row, 0).setData(256, region.id)  # 存 region_id

    def _delete(self, region_id):
        if region_id in self.regions:
            del self.regions[region_id]
        # 找到并删除对应行
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(256) == region_id:
                self.table.removeRow(row)
                break
        self.region_deleted.emit(region_id)

    def clear_all(self):
        self.regions.clear()
        self.table.setRowCount(0)
        self.region_changed.emit([])

    def build_template(self) -> Template:
        regions = []
        for row in range(self.table.rowCount()):
            rid = self.table.item(row, 0).data(256)
            r = self.regions[rid]
            r.field_name = self.table.item(row, 0).text()
            r.field_type = self.table.cellWidget(row, 1).currentText()
            regions.append(r)
        return Template(name="current", regions=regions)

    def load_template(self, template: Template):
        self.clear_all()
        for r in template.regions:
            self.add_region(r)
        self.region_changed.emit(list(self.regions.values()))

    def show_preview_result(self, file_result):
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            if name in file_result.fields:
                fr = file_result.fields[name]
                item = QTableWidgetItem(fr.text)
                if fr.confidence < 0.7:
                    item.setBackground(QColor("#FFE5E5"))
                self.table.setItem(row, 2, item)
