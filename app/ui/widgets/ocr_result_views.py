"""结果视图：文档解析（左图右文 + 检测框高亮）与 JSON 树"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
                             QTextBrowser, QTreeWidget, QTreeWidgetItem,
                             QCheckBox, QLabel)
from app.models.page_result import PageResult
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.theme_manager import ThemeManager


class OcrDocView(QWidget):
    """文档解析视图：PDF 页渲染 + 结构化文本 + 检测框高亮开关"""
    boxes_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_boxes = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PdfCanvas()
        self.canvas.set_drawing_enabled(False)  # 只读浏览
        self.text_browser = QTextBrowser()
        self.text_browser.setStyleSheet("font-size: 14px;")
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.text_browser)
        self.splitter.setSizes([480, 480])
        layout.addWidget(self.splitter, 1)
        toolbar = QHBoxLayout()
        self.boxes_check = QCheckBox("显示检测框")
        self.boxes_check.setChecked(True)
        self.boxes_check.toggled.connect(self._on_boxes_toggled)
        toolbar.addWidget(self.boxes_check)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

    def _on_boxes_toggled(self, on):
        self._show_boxes = on
        self.boxes_toggled.emit(on)
        if not on:
            self.canvas.clear_highlights()

    def set_boxes_visible(self, visible: bool):
        """编程方式开关检测框高亮（与复选框状态联动）"""
        self.boxes_check.setChecked(visible)

    def show_page(self, result, image, show_boxes: bool = True):
        """渲染一页：原图 + 结构化文本 + 检测框"""
        self.canvas.load_image(image)
        self._show_boxes = show_boxes
        self.text_browser.setHtml(self._blocks_to_html(result))
        if show_boxes and result.blocks:
            self.canvas.clear_highlights()
            for b in result.blocks:
                if b.bbox and len(b.bbox) == 4:
                    self.canvas.highlight_bbox(b.bbox)

    def text(self) -> str:
        return self.text_browser.toPlainText()

    @staticmethod
    def _blocks_to_html(result: PageResult) -> str:
        """markdown/块内容 → HTML：标题/段落、table 等宽、行内 <br>

        markdown 为整页结构化文本（优先）；markdown 为空时回退到 blocks 逐块渲染。
        """
        if result.markdown:
            return _render_markdown(result.markdown)
        parts = []
        for b in result.blocks:
            content = str(b.content).replace("\n", "<br>")
            if b.block_type == "table":
                parts.append(f"<pre>{content}</pre>")
            else:
                parts.append(f"<p>{content}</p>")
        return "<html><body style='font-family:sans-serif'>" \
               + "".join(parts) + "</body></html>"


def _render_markdown(md: str) -> str:
    """极简 Markdown → HTML：标题、段落、表格行转 <pre>"""
    parts = []
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            text = stripped.lstrip("#").strip()
            parts.append(f"<h2>{text}</h2>")
        elif "|" in stripped:
            parts.append(f"<pre>{stripped}</pre>")
        else:
            parts.append(f"<p>{stripped}</p>")
    return "<html><body style='font-family:sans-serif'>" \
           + "".join(parts) + "</body></html>"


class OcrJsonView(QTreeWidget):
    """JSON 树视图：递归构建可折叠树（基于 PageResult.raw_json）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("原始解析结果（JSON）")
        self.setColumnCount(2)
        self.setHeaderLabels(["键 / 值", "类型"])

    def show_result(self, raw_json: dict):
        self.clear()
        if not raw_json:
            return
        if isinstance(raw_json, dict):
            for k, v in raw_json.items():
                item = QTreeWidgetItem(
                    [str(k), "object" if isinstance(v, (dict, list)) else type(v).__name__])
                self.addTopLevelItem(item)
                self._fill(item, v)
                item.setExpanded(True)
        else:
            # 非 dict（如列表）按索引铺开
            for i, v in enumerate(raw_json):
                item = QTreeWidgetItem(
                    [f"[{i}]", "object" if isinstance(v, (dict, list)) else type(v).__name__])
                self.addTopLevelItem(item)
                self._fill(item, v)
                item.setExpanded(True)

    def _fill(self, parent: QTreeWidgetItem, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                item = QTreeWidgetItem([str(k), "object" if isinstance(v, (dict, list)) else type(v).__name__])
                parent.addChild(item)
                self._fill(item, v)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                item = QTreeWidgetItem([f"[{i}]", "object" if isinstance(v, (dict, list)) else type(v).__name__])
                parent.addChild(item)
                self._fill(item, v)
        else:
            # 叶子：键值同显（dict 键 或 列表 [i]），避免键被值覆盖
            parent.setText(0, f"{parent.text(0)}: {obj}")
            parent.setText(1, type(obj).__name__)
