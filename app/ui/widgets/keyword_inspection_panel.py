"""内嵌核对面板 — 渲染该页 + PDF 文本层高亮 + 该页单元格表（可改值回写）

坐标只来自 PDF 文本层（text_layer_locator），绝不来自 VLM。
"""
import fitz

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView)

from app.core.text_layer_locator import locate_words
from app.models.keyword_result import KeywordCell
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.theme_manager import ThemeManager

_STATUS_TEXT = {"confirmed": "✓ 已确认", "pending": "⚠ 待确认",
                "not_found": "— 未找到"}
_STATUS_COLOR = {"confirmed": "success", "pending": "warning_text",
                 "not_found": "text_disabled"}


class KeywordInspectionPanel(QWidget):
    """右侧核对面板（汇总页内嵌，初始隐藏）"""

    value_edited = pyqtSignal(int, int, str, str)  # file_index, page_no, keyword, new_value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(430)
        self._file_index = 0
        self._page_no = 1
        self._cells = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ThemeManager.get_spacing('sm'), 0, 0, 0)
        self.title_label = QLabel("")
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        layout.addWidget(self.title_label)
        self.canvas = PdfCanvas()
        layout.addWidget(self.canvas, stretch=3)
        self.cell_table = QTableWidget(0, 3)
        self.cell_table.setHorizontalHeaderLabels(["关键字", "值", "状态"])
        self.cell_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.cell_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.cell_table.itemChanged.connect(self._on_cell_changed)
        layout.addWidget(self.cell_table, stretch=2)
        ThemeManager.register_refresh_callback(self.apply_theme)

    def show_inspection(self, file_path: str, page_no: int, loader, dpi: int,
                        cells: dict, focus_keyword: str = None,
                        line_boxes: list = None):
        """渲染该页、高亮焦点单元格（值优先，值未找到退而定位关键字）、填表

        高亮优先级：PDF 文本层定位（精确）→ OCR 检测层行盒兜底
        （line_boxes：引擎检测出的行级 Block，bbox 为图像像素坐标，
        扫描件无文本层时的唯一坐标源）。
        """
        self._page_no = page_no
        self._cells = cells
        self.title_label.setText(f"{file_path}  ·  第 {page_no} 页")
        image = loader.render_page(file_path, page_no - 1)
        self.canvas.load_image(image)
        self.canvas.clear_highlights()
        focus = None
        if focus_keyword and focus_keyword in cells and cells[focus_keyword].status != "not_found":
            focus = cells[focus_keyword].value or focus_keyword
        elif focus_keyword:
            focus = focus_keyword
        hit = False
        if focus:
            # 值优先；文本层未命中（OCR 值与文本层格式差异）→ 退而定位关键字本身
            hit = self._highlight_on_text_layer(file_path, page_no, focus, dpi)
            if not hit and focus_keyword:
                hit = self._highlight_on_text_layer(file_path, page_no, focus_keyword, dpi)
        if not hit:
            # 文本层无命中（扫描件无文本层等）→ OCR 检测层行盒兜底
            self._highlight_on_ocr_boxes(line_boxes or [], focus, focus_keyword)
        self._fill_table()

    def _highlight_on_ocr_boxes(self, line_boxes: list, focus: str = None,
                                 focus_keyword: str = None) -> bool:
        """OCR 检测层行盒高亮 — 命中行（值/关键字任一）主题色，其余淡色

        行盒 Block.bbox 为图像像素坐标（与画布场景坐标一致，直接画）。
        返回是否画了任何框。
        """
        if not line_boxes:
            return False
        needles = []
        for n in (focus, focus_keyword):
            n = (n or "").replace(" ", "")
            if n and n not in needles:
                needles.append(n)
        matched_rows = set()
        for i, b in enumerate(line_boxes):
            content = (getattr(b, "content", "") or "").replace(" ", "")
            for n in needles:
                if n and n in content:
                    matched_rows.add(i)
                    break
        for i, b in enumerate(line_boxes):
            bbox = getattr(b, "bbox", None)
            if not bbox or len(bbox) != 4:
                continue
            if i in matched_rows:
                self.canvas.highlight_bbox(bbox)  # 主题色 primary
            else:
                # 淡色：未命中行 / 无 focus 时兜底展示识别版面
                self.canvas.highlight_bbox(
                    bbox, color=ThemeManager.get_color('text_disabled'))
        return True

    def _highlight_on_text_layer(self, file_path: str, page_no: int, text: str,
                                 dpi: int) -> bool:
        """fitz 文本层定位 → 画布高亮（pt→像素 scale = dpi/72）；返回是否找到"""
        try:
            doc = fitz.open(file_path)
            try:
                page = doc[page_no - 1]
                rects = locate_words(page, text, scale=dpi / 72.0)
            finally:
                doc.close()
        except Exception:
            rects = []
        for r in rects:
            self.canvas.highlight_bbox(r)
        return bool(rects)

    def _fill_table(self):
        self.cell_table.blockSignals(True)
        self.cell_table.setRowCount(len(self._cells))
        for row, (kw, cell) in enumerate(self._cells.items()):
            self.cell_table.setItem(row, 0, QTableWidgetItem(kw))
            value_item = QTableWidgetItem(cell.value if cell.status != "not_found" else "")
            value_item.setFlags(value_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.cell_table.setItem(row, 1, value_item)
            status_item = QTableWidgetItem(_STATUS_TEXT.get(cell.status, cell.status))
            color_role = _STATUS_COLOR.get(cell.status)
            if color_role:
                status_item.setForeground(QColor(ThemeManager.get_color(color_role)))
            self.cell_table.setItem(row, 2, status_item)
        self.cell_table.blockSignals(False)

    def _on_cell_changed(self, item):
        if item.column() != 1:
            return
        row = item.row()
        kw = self.cell_table.item(row, 0).text() if self.cell_table.item(row, 0) else ""
        self.value_edited.emit(self._file_index, self._page_no, kw, item.text())

    def apply_theme(self):
        self.cell_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
                gridline-color: {ThemeManager.get_color('border')};
                alternate-background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
            QTableWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_primary')};
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
