"""关键字汇总树 — 按文件分组折叠、每页一行、列头命中率徽标

视觉（frontend-design 确认）：档案夹文件组头（默认折叠）、值单元格按状态
着色（ThemeManager 状态底色角色）、not_found 显示 '—'、双击编辑 + 人工
修正标记（bg_selected 蓝底）、双击值单元格发射核对信号。
"""
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from app.models.keyword_result import FileKeywordResult, KeywordCell
from app.ui.theme_manager import ThemeManager

_STATUS_BG = {"confirmed": "success_bg", "pending": "warning_bg", "error": "error_bg"}
_STATUS_TEXT = {"confirmed": "已确认", "pending": "待确认",
                "not_found": "未找到", "error": "失败"}
_SOURCE_TEXT = {"exact": "精确", "loose": "宽松", "none": "未匹配"}

LOW_HIT_RATIO = 0.6  # 命中率低于此值的列头加 ⚠ 警示


class KeywordSummaryTree(QTreeWidget):
    """分组折叠汇总树"""

    cell_inspect_requested = pyqtSignal(int, int, str)  # file_index, page_no, keyword

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: List[FileKeywordResult] = []
        self._loading = False
        self.setColumnCount(2)
        self.setHeaderLabels(["单据", "状态"])
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemChanged.connect(self._on_item_changed)
        ThemeManager.register_refresh_callback(self.apply_theme)

    # ---------- 数据 ----------

    def load_results(self, results: List[FileKeywordResult]):
        self._results = results
        keywords = self._collect_keywords(results)
        self.setColumnCount(2 + len(keywords))
        self._loading = True
        try:
            self._rebuild_headers(keywords)
            self.clear()
            for idx, fr in enumerate(results):
                group = self._make_group_item(idx, fr)
                self.addTopLevelItem(group)
                for page in fr.pages:
                    group.addChild(self._make_page_item(idx, page, keywords))
                group.setExpanded(False)  # 默认折叠
        finally:
            self._loading = False
        self.resizeColumnToContents(0)

    def _collect_keywords(self, results: List[FileKeywordResult]) -> List[str]:
        kws: List[str] = []
        for fr in results:
            for page in fr.pages:
                for kw in page.cells:
                    if kw not in kws:
                        kws.append(kw)
        return kws

    def _rebuild_headers(self, keywords: List[str]):
        total_pages = sum(len(fr.pages) for fr in self._results)
        headers = ["单据", "状态"]
        for kw in keywords:
            hit = sum(1 for fr in self._results for pg in fr.pages
                      if pg.cells.get(kw) and pg.cells[kw].status != "not_found")
            ratio = (hit / total_pages) if total_pages else 0.0
            mark = "⚠ " if ratio < LOW_HIT_RATIO else ""
            headers.append(f"{kw} ({mark}{int(round(ratio * 100))}%)")
        self.setHeaderLabels(headers)

    def _make_group_item(self, idx: int, fr: FileKeywordResult) -> QTreeWidgetItem:
        pending = sum(1 for pg in fr.pages
                      for c in pg.cells.values() if c.status == "pending")
        text = f"{fr.source_file}  ·  {len(fr.pages)}页"
        if pending:
            text += f"  ·  {pending}待确认"
        item = QTreeWidgetItem([text, "成功" if fr.success else "失败"])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if not fr.success:
            item.setToolTip(1, fr.error_msg)
        return item

    def _make_page_item(self, idx: int, page, keywords: List[str]) -> QTreeWidgetItem:
        row = [f"第 {page.page_no} 页", "成功" if page.success else "失败"]
        item = QTreeWidgetItem(row)
        if not page.success:
            item.setToolTip(1, page.error_msg)
            for col in range(self.columnCount()):
                item.setBackground(col, QColor(ThemeManager.get_color("error_bg")))
            return item
        for k, kw in enumerate(keywords):
            col = 2 + k
            cell = page.cells.get(kw)
            if cell is None:
                continue
            if cell.status == "not_found":
                item.setText(col, "—")
                item.setForeground(col, QColor(ThemeManager.get_color("text_disabled")))
            else:
                item.setText(col, cell.value)
                if cell.status == "pending":
                    item.setForeground(col, QColor(ThemeManager.get_color("warning_text")))
                bg = _STATUS_BG.get(cell.status)
                if bg:
                    item.setBackground(col, QColor(ThemeManager.get_color(bg)))
            if cell.manually_edited:
                item.setBackground(col, QColor(ThemeManager.get_color("bg_selected")))
            tip = self._cell_tooltip(cell)
            if tip:
                item.setToolTip(col, tip)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(col, Qt.ItemDataRole.UserRole, (idx, page.page_no, kw))
        return item

    @staticmethod
    def _cell_tooltip(cell: KeywordCell) -> str:
        parts = [f"状态: {_STATUS_TEXT.get(cell.status, cell.status)}",
                 f"匹配: {_SOURCE_TEXT.get(cell.source, cell.source)}"]
        if cell.line_text:
            parts.append(f"原文: {cell.line_text}")
        if cell.manually_edited:
            parts.append("已人工修正")
        return "\n".join(parts)

    # ---------- 交互 ----------

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        if column < 2:
            return
        data = item.data(column, Qt.ItemDataRole.UserRole)
        if data:
            idx, page_no, kw = data
            self.cell_inspect_requested.emit(idx, page_no, kw)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._loading or column < 2:
            return
        data = item.data(column, Qt.ItemDataRole.UserRole)
        if not data:
            return
        idx, page_no, kw = data
        fr = self._results[idx]
        if page_no < 1 or page_no > len(fr.pages):
            return
        cell = fr.pages[page_no - 1].cells.get(kw)
        if cell is None:
            return
        new_value = item.text(column)
        if new_value == cell.value and cell.manually_edited:
            return
        cell.value = new_value
        cell.manually_edited = True
        item.setBackground(column, QColor(ThemeManager.get_color("bg_selected")))

    # ---------- 主题 ----------

    def apply_theme(self):
        self.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                alternate-background-color: {ThemeManager.get_color('bg_hover')};
                border: none;
                outline: none;
                color: {ThemeManager.get_color('text_primary')};
            }}
            QTreeWidget::item {{
                padding: {ThemeManager.get_spacing('xs')}px;
            }}
            QTreeWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_primary')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('xs')}px;
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        # 主题切换后重建整树：状态底色/文字色随新主题重涂（load_results 幂等）
        if self._results:
            self.load_results(self._results)
