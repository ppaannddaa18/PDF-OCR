from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtGui import QColor
from app.models.ocr_result import FileResult
from pathlib import Path


class ResultTable(QTableWidget):
    def __init__(self):
        super().__init__()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._results = []

    def load_results(self, results: list):
        self._results = results
        if not results:
            return
        # 收集所有字段名
        field_names = []
        for r in results:
            for fn in r.fields:
                if fn not in field_names:
                    field_names.append(fn)

        headers = ["源文件"] + field_names + ["状态"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(results))

        for row, r in enumerate(results):
            self.setItem(row, 0, QTableWidgetItem(Path(r.source_file).name))
            for col, fn in enumerate(field_names, start=1):
                fr = r.fields.get(fn)
                if fr:
                    item = QTableWidgetItem(fr.text)
                    if fr.confidence < 0.7:
                        item.setBackground(QColor("#FFE5E5"))
                    self.setItem(row, col, item)
            status = "成功" if r.success else f"失败: {r.error_msg}"
            self.setItem(row, len(headers)-1, QTableWidgetItem(status))

    def collect_results(self) -> list:
        """用户在表格中编辑过的值回写到 results"""
        field_names = [self.horizontalHeaderItem(i).text()
                       for i in range(1, self.columnCount()-1)]
        for row, r in enumerate(self._results):
            for col, fn in enumerate(field_names, start=1):
                item = self.item(row, col)
                if item and fn in r.fields:
                    new_text = item.text()
                    if new_text != r.fields[fn].text:
                        r.fields[fn].text = new_text
                        r.fields[fn].manually_edited = True
        return self._results
