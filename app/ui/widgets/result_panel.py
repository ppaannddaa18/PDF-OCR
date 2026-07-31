"""ResultPanel — VLM解析结果展示 + 导出（Task 12 重构版：QTabBar 标签页切换视图）

设计要点：
- QTabBar（3 个标签：Markdown预览/字段提取/表格数据）替代原下拉框视图切换，
  标签页与 QStackedWidget 内容区通过 currentChanged 信号联动
- set_view() 保留按索引/名称切换视图的接口语义
- 三个视图内容组件完整保留：Markdown 预览、字段提取表格（3 列+校验状态）、
  表格数据预览
- 导出按钮保留（📥 导出），支持 md/json/docx/xlsx 四种格式
- 全部颜色/字体/间距来自 ThemeManager，禁止硬编码颜色
  （原校验失败硬编码红色 QColor(0xd1,0x34,0x38) → 主题 error 色）
- 表格渲染兜底：tabulate 未安装时 df.to_markdown 抛 ImportError，降级为
  df.to_string 纯文本输出，避免运行期崩溃
"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTextEdit, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QStackedWidget,
    QTabBar, QMessageBox, QHeaderView,
)
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor
from typing import Optional
import json
import logging

from app.ui.theme_manager import ThemeManager

logger = logging.getLogger("PDFOCR")

# 标签页顺序（索引即 content_stack 页面索引）
TAB_LABELS = ["Markdown预览", "字段提取", "表格数据"]


class ResultPanel(QWidget):
    """右面板：Markdown预览 / 字段提取 / 表格数据 + 导出（标签页切换）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page_result = None
        self._finance_result = None
        self._init_ui()
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标签页切换（替代原视图切换下拉框）
        self.tab_bar = QTabBar()
        for label in TAB_LABELS:
            self.tab_bar.addTab(label)
        layout.addWidget(self.tab_bar)

        # 内容区（堆叠视图）
        self.content_stack = QStackedWidget()

        # 视图0: Markdown预览
        self._md_view = QTextEdit()
        self._md_view.setReadOnly(True)
        self.content_stack.addWidget(self._md_view)

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
        self.content_stack.addWidget(self._field_table)

        # 视图2: 表格数据预览
        self._table_view = QTextEdit()
        self._table_view.setReadOnly(True)
        self.content_stack.addWidget(self._table_view)

        layout.addWidget(self.content_stack, stretch=1)

        # 导出按钮
        self.export_btn = QPushButton("📥 导出")
        self.export_btn.clicked.connect(self._on_export)
        layout.addWidget(self.export_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # 标签页切换联动内容区
        self.tab_bar.currentChanged.connect(self._on_tab_changed)

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用）"""
        self.tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {ThemeManager.get_color('bg_surface')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('sm')}px
                         {ThemeManager.get_spacing('md')}px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {ThemeManager.get_color('primary')};
                border-bottom: 2px solid {ThemeManager.get_color('primary')};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
        """)
        self.export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: {ThemeManager.get_color('white')};
                border: none;
                border-radius: {ThemeManager.get_radius('md')}px;
                padding: {ThemeManager.get_spacing('sm')}px
                         {ThemeManager.get_spacing('lg')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)

    # ---------- 视图切换 ----------

    def set_view(self, index_or_name):
        """切换当前视图（接受标签索引或标签名；TabBar 与内容区联动）"""
        if isinstance(index_or_name, str):
            if index_or_name not in TAB_LABELS:
                raise ValueError(f"未知视图: {index_or_name}")
            index_or_name = TAB_LABELS.index(index_or_name)
        self.tab_bar.setCurrentIndex(index_or_name)

    def _on_tab_changed(self, idx: int):
        """标签页切换：同步内容区并渲染当前视图"""
        self.content_stack.setCurrentIndex(idx)
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
                        item.setForeground(QColor(ThemeManager.get_color('error')))
                    self._field_table.setItem(i, 2, item)
                self._field_table.resizeColumnsToContents()
            else:
                self._field_table.setRowCount(0)
        elif idx == 2:
            # 表格数据
            if self._page_result.tables:
                texts = []
                for i, df in enumerate(self._page_result.tables):
                    try:
                        table_text = df.to_markdown(index=False)
                    except ImportError:
                        # tabulate 未安装时降级为纯文本表格，避免运行期崩溃
                        table_text = df.to_string(index=False)
                    texts.append(f"### 表格 {i+1}\n\n{table_text}")
                self._table_view.setMarkdown("\n\n".join(texts))
            else:
                self._table_view.setPlainText("(未检测到表格)")

    # ---------- 数据接口 ----------

    def load_result(self, page_result, finance_result=None):
        """加载解析结果"""
        self._page_result = page_result
        self._finance_result = finance_result
        self._on_tab_changed(self.tab_bar.currentIndex())

    def clear(self):
        """清空所有视图"""
        self._page_result = None
        self._finance_result = None
        self._md_view.clear()
        self._field_table.setRowCount(0)
        self._table_view.clear()

    # ---------- 导出 ----------

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
