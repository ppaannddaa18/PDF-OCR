"""ResultPanel — VLM解析结果展示 + 导出"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QStackedWidget,
    QComboBox, QLabel, QMessageBox, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from typing import Optional
import json
import logging

logger = logging.getLogger("PDFOCR")


class ResultPanel(QWidget):
    """右面板：Markdown预览 / 字段提取 / 表格数据 + 导出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page_result = None
        self._finance_result = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        # 视图切换下拉框 + 导出按钮
        top_bar = QHBoxLayout()
        top_bar.setSpacing(6)
        self._view_selector = QComboBox()
        self._view_selector.addItems(["Markdown预览", "字段提取", "表格数据"])
        self._view_selector.currentIndexChanged.connect(self._update_current_view)
        top_bar.addWidget(QLabel("视图:"))
        top_bar.addWidget(self._view_selector)
        top_bar.addStretch()

        # 导出按钮
        self._btn_export = QPushButton("导出...")
        self._btn_export.clicked.connect(self._on_export)
        top_bar.addWidget(self._btn_export)
        layout.addLayout(top_bar)

        # 堆叠视图
        self._stack = QStackedWidget()

        # 视图0: Markdown预览
        self._md_view = QTextEdit()
        self._md_view.setReadOnly(True)
        self._stack.addWidget(self._md_view)

        # 视图1: 字段提取表格
        self._field_table = QTableWidget()
        self._field_table.setColumnCount(3)
        self._field_table.setHorizontalHeaderLabels(["字段", "值", "状态"])
        self._field_table.horizontalHeader().setStretchLastSection(True)
        self._field_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self._field_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self._field_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self._field_table.setAlternatingRowColors(True)
        self._stack.addWidget(self._field_table)

        # 视图2: 表格数据预览
        self._table_view = QTextEdit()
        self._table_view.setReadOnly(True)
        self._stack.addWidget(self._table_view)

        layout.addWidget(self._stack)

    def load_result(self, page_result, finance_result=None):
        """加载解析结果"""
        self._page_result = page_result
        self._finance_result = finance_result
        self._update_current_view()

    def clear(self):
        """清空所有视图"""
        self._page_result = None
        self._finance_result = None
        self._md_view.clear()
        self._field_table.setRowCount(0)
        self._table_view.clear()

    def _update_current_view(self):
        idx = self._view_selector.currentIndex()
        self._stack.setCurrentIndex(idx)
        if self._page_result is None:
            return
        if idx == 0:
            # Markdown
            self._md_view.setMarkdown(self._page_result.markdown or "(无内容)")
        elif idx == 1:
            # 字段提取
            if self._finance_result and self._finance_result.fields:
                self._field_table.setRowCount(len(self._finance_result.fields))
                for i, f in enumerate(self._finance_result.fields):
                    self._field_table.setItem(i, 0, QTableWidgetItem(f.label))
                    self._field_table.setItem(i, 1, QTableWidgetItem(str(f.value or "")))
                    status = "✓" if f.validated else f"⚠ {f.validation_msg}"
                    item = QTableWidgetItem(status)
                    if not f.validated:
                        item.setForeground(QColor(0xd1, 0x34, 0x38))
                    self._field_table.setItem(i, 2, item)
                self._field_table.resizeColumnsToContents()
            else:
                self._field_table.setRowCount(0)
        elif idx == 2:
            # 表格数据
            if self._page_result.tables:
                texts = []
                for i, df in enumerate(self._page_result.tables):
                    texts.append(f"### 表格 {i+1}\n\n{df.to_markdown(index=False)}")
                self._table_view.setMarkdown("\n\n".join(texts))
            else:
                self._table_view.setPlainText("(未检测到表格)")

    def _on_export(self):
        """导出当前结果"""
        if self._page_result is None:
            QMessageBox.information(self, "提示", "暂无解析结果可导出")
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出结果", "",
            "Markdown (*.md);;JSON (*.json);;Word (*.docx);;Excel (*.xlsx)"
        )
        if not filepath:
            return
        try:
            if filepath.endswith('.md'):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self._page_result.markdown or "")
            elif filepath.endswith('.json'):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self._page_result.raw_json, f, ensure_ascii=False, indent=2)
            elif filepath.endswith('.docx'):
                from docx import Document
                doc = Document()
                doc.add_paragraph(self._page_result.markdown or "(空)")
                doc.save(filepath)
            elif filepath.endswith('.xlsx'):
                import pandas as pd
                if self._page_result.tables:
                    with pd.ExcelWriter(filepath) as writer:
                        for i, df in enumerate(self._page_result.tables):
                            df.to_excel(writer, sheet_name=f"Table_{i+1}", index=False)
                else:
                    pd.DataFrame().to_excel(filepath, index=False)
            QMessageBox.information(self, "导出成功", f"已保存到:\n{filepath}")
        except Exception as e:
            logger.error(f"导出失败: {e}", exc_info=True)
            QMessageBox.critical(self, "导出失败", str(e))
