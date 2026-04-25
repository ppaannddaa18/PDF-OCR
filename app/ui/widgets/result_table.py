from PyQt6.QtWidgets import (
    QTableWidget, QTableWidgetItem, QHeaderView, QHBoxLayout, QWidget,
    QPushButton, QLineEdit, QComboBox, QVBoxLayout, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QBrush, QIcon
from app.models.ocr_result import FileResult
from pathlib import Path
import qtawesome as qta


class ResultTable(QTableWidget):
    """增强的结果表格，支持编辑标记、筛选、排序"""
    data_changed = Signal()  # 数据变更信号

    def __init__(self):
        super().__init__()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        self._results = []
        self._original_results = []  # 保存原始结果用于重置
        self._modified_cells = set()  # (row, col) 已修改的单元格
        self._field_names = []

        # 启用编辑
        self.setEditTriggers(QTableWidget.EditTrigger.DoubleClicked | QTableWidget.EditTrigger.EditKeyPressed)
        self.itemChanged.connect(self._on_item_changed)

        # 筛选和排序状态
        self._filter_text = ""
        self._sort_column = -1
        self._sort_order = Qt.SortOrder.AscendingOrder

    def load_results(self, results: list):
        """加载识别结果"""
        self._results = results
        self._original_results = [self._copy_result(r) for r in results]
        self._modified_cells.clear()
        self._refresh_table()

    def _copy_result(self, result: FileResult) -> FileResult:
        """复制结果对象"""
        from copy import deepcopy
        return deepcopy(result)

    def _refresh_table(self):
        """刷新表格显示"""
        self.clear()
        if not self._results:
            return

        # 收集所有字段名
        self._field_names = []
        for r in self._results:
            for fn in r.fields:
                if fn not in self._field_names:
                    self._field_names.append(fn)

        headers = ["源文件"] + self._field_names + ["状态", "操作"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(self._results))

        for row, r in enumerate(self._results):
            # 源文件名列
            self.setItem(row, 0, QTableWidgetItem(Path(r.source_file).name))

            # 字段值列
            for col, fn in enumerate(self._field_names, start=1):
                fr = r.fields.get(fn)
                if fr:
                    item = QTableWidgetItem(fr.text)
                    # 根据置信度设置背景色
                    if fr.confidence < 0.5:
                        item.setBackground(QColor("#FFE5E5"))  # 红色 - 低置信度
                        item.setToolTip(f"置信度: {fr.confidence:.1%} (较低，建议核对)")
                    elif fr.confidence < 0.7:
                        item.setBackground(QColor("#FFF4E5"))  # 黄色 - 中等置信度
                        item.setToolTip(f"置信度: {fr.confidence:.1%} (一般)")
                    else:
                        item.setToolTip(f"置信度: {fr.confidence:.1%}")

                    # 标记手动编辑的单元格
                    if fr.manually_edited:
                        item.setBackground(QColor("#E5F3FF"))  # 蓝色 - 已编辑
                        item.setToolTip(f"{item.toolTip()}\n[已手动编辑]")

                    self.setItem(row, col, item)
                else:
                    self.setItem(row, col, QTableWidgetItem(""))

            # 状态列
            status_item = QTableWidgetItem("成功" if r.success else f"失败: {r.error_msg}")
            if not r.success:
                status_item.setBackground(QColor("#FFE5E5"))
            self.setItem(row, len(headers)-2, status_item)

            # 操作列 - 重置按钮
            reset_btn = QPushButton("重置")
            reset_btn.setFixedWidth(60)
            reset_btn.clicked.connect(lambda checked, r=row: self._reset_row(r))
            self.setCellWidget(row, len(headers)-1, reset_btn)

        # 调整列宽
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(len(headers)-2, QHeaderView.ResizeMode.ResizeToContents)
        self.horizontalHeader().setSectionResizeMode(len(headers)-1, QHeaderView.ResizeMode.Fixed)
        self.setColumnWidth(len(headers)-1, 70)

    def _on_item_changed(self, item: QTableWidgetItem):
        """单元格内容变更处理"""
        row = item.row()
        col = item.column()

        # 忽略非字段列
        if col <= 0 or col >= len(self._field_names) + 1:
            return

        field_name = self._field_names[col - 1]
        new_value = item.text()

        # 更新结果数据
        if row < len(self._results):
            result = self._results[row]
            if field_name in result.fields:
                old_value = result.fields[field_name].text
                if old_value != new_value:
                    result.fields[field_name].text = new_value
                    result.fields[field_name].manually_edited = True
                    self._modified_cells.add((row, col))
                    # 更新背景色标记
                    item.setBackground(QColor("#E5F3FF"))
                    self.data_changed.emit()

    def _reset_row(self, row: int):
        """重置指定行的数据为识别结果"""
        if row >= len(self._results) or row >= len(self._original_results):
            return

        original = self._original_results[row]
        current = self._results[row]

        # 恢复字段值
        for field_name, field_result in original.fields.items():
            if field_name in current.fields:
                current.fields[field_name].text = field_result.text
                current.fields[field_name].manually_edited = False

        # 刷新该行显示
        for col, fn in enumerate(self._field_names, start=1):
            fr = current.fields.get(fn)
            if fr:
                item = QTableWidgetItem(fr.text)
                # 恢复置信度颜色
                if fr.confidence < 0.5:
                    item.setBackground(QColor("#FFE5E5"))
                elif fr.confidence < 0.7:
                    item.setBackground(QColor("#FFF4E5"))
                self.setItem(row, col, item)
                self._modified_cells.discard((row, col))

        self.data_changed.emit()

    def reset_all(self):
        """重置所有数据为识别结果"""
        self._results = [self._copy_result(r) for r in self._original_results]
        self._modified_cells.clear()
        self._refresh_table()
        self.data_changed.emit()

    def collect_results(self) -> list:
        """收集当前表格数据（包含用户编辑）"""
        return self._results

    def get_modified_count(self) -> int:
        """获取已修改的单元格数量"""
        return len(self._modified_cells)

    def filter_by_field(self, field_name: str, keyword: str):
        """[修复] 按字段筛选 - 支持全部字段筛选"""
        if not keyword:
            self.show_all_rows()
            return

        keyword_lower = keyword.lower()

        # 隐藏不匹配的行
        for row in range(self.rowCount()):
            match_found = False

            if field_name == "全部字段" or field_name == "":
                # [修复] 搜索所有字段
                for col in range(1, len(self._field_names) + 1):
                    item = self.item(row, col)
                    if item and keyword_lower in item.text().lower():
                        match_found = True
                        break
            elif field_name in self._field_names:
                # 搜索指定字段
                col = self._field_names.index(field_name) + 1
                item = self.item(row, col)
                if item and keyword_lower in item.text().lower():
                    match_found = True

            if match_found:
                self.showRow(row)
            else:
                self.hideRow(row)

    def show_all_rows(self):
        """显示所有行"""
        for row in range(self.rowCount()):
            self.showRow(row)

    def export_to_dict(self) -> list:
        """导出为字典列表"""
        data = []
        for r in self._results:
            row_data = {"源文件": Path(r.source_file).name}
            for fn, fr in r.fields.items():
                row_data[fn] = fr.text
            row_data["状态"] = "成功" if r.success else f"失败: {r.error_msg}"
            data.append(row_data)
        return data
