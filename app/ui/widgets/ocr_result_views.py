"""结果视图：文档解析（左图右文 + 检测框高亮）与 JSON 树"""
import re
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
        self._last_result = None  # 最近一次 show_page 的结果（重新勾选时重放检测框）
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
        if on:
            # 重新勾选：用最近一次结果重放检测框（当前页立即恢复，无需翻页）
            if self._last_result is not None:
                self._apply_highlights(self._last_result)
        else:
            self.canvas.clear_highlights()

    def set_boxes_visible(self, visible: bool):
        """编程方式开关检测框高亮（与复选框状态联动）"""
        self.boxes_check.setChecked(visible)

    def show_page(self, result, image, show_boxes: bool = None):
        """渲染一页：原图 + 结构化文本 + 检测框

        show_boxes 为 None（默认）时跟随复选框状态，不再覆盖用户勾选；
        显式传布尔值时同步复选框，保证 _show_boxes 与勾选态始终一致。
        """
        self._last_result = result
        self.canvas.load_image(image)
        if show_boxes is not None:
            # setChecked 同态时不触发 toggled 信号，直接赋值保持同步
            self._show_boxes = show_boxes
            self.boxes_check.setChecked(show_boxes)
        else:
            self._show_boxes = self.boxes_check.isChecked()
        self.text_browser.setHtml(self._blocks_to_html(result))
        if self._show_boxes:
            self._apply_highlights(result)

    def _apply_highlights(self, result):
        """清空后绘制 result 的全部检测框（与复选框状态解耦）"""
        self.canvas.clear_highlights()
        for b in result.blocks:
            if b.bbox and len(b.bbox) == 4:
                self.canvas.highlight_bbox(b.bbox)

    def text(self) -> str:
        return self.text_browser.toPlainText()

    def clear_view(self):
        """清空视图：画布复位 + 文本/检测框/高亮清空（清空队列后防残留旧状态）"""
        self.canvas.clear()
        self.text_browser.clear()
        self._last_result = None

    @staticmethod
    def _blocks_to_html(result: PageResult) -> str:
        """markdown/块内容 → HTML：标题/段落、table 等宽、行内 <br>

        markdown 为整页结构化文本（优先）；markdown 为空时回退到 blocks 逐块渲染。
        两者皆空 → 灰色占位文案（无可解析内容）。
        """
        if not result.markdown and not result.blocks:
            return "<html><body style='font-family:sans-serif'>" \
                   "<p style='color:gray'>无可解析内容</p></body></html>"
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
    r"""极简 Markdown → HTML：标题、段落、表格行转 <pre>

    标题要求 `#` 后随空白（`^#{1,6}\s`，避免 "###" 无空格文本与 "#1 章节"
    等误判）；表格行要求两侧 `|`（`^\|.*\|$`）才按等宽渲染。
    """
    parts = []
    for line in md.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if re.match(r"^#{1,6}\s", stripped):
            text = stripped.lstrip("#").strip()
            parts.append(f"<h2>{text}</h2>")
        elif re.match(r"^\|.*\|$", stripped):
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

    def show_result(self, raw_json):
        self.clear()
        if not raw_json:
            # 空 dict/None/空列表：占位行，不渲染空树
            self.addTopLevelItem(QTreeWidgetItem(["（无 JSON 数据）", ""]))
            return
        if isinstance(raw_json, dict):
            for k, v in raw_json.items():
                item = QTreeWidgetItem(
                    [str(k), "object" if isinstance(v, (dict, list)) else type(v).__name__])
                self.addTopLevelItem(item)
                self._fill(item, v)
                item.setExpanded(True)
        elif isinstance(raw_json, (list, tuple)):
            # list/tuple 根值按索引铺开
            for i, v in enumerate(raw_json):
                item = QTreeWidgetItem(
                    [f"[{i}]", "object" if isinstance(v, (dict, list)) else type(v).__name__])
                self.addTopLevelItem(item)
                self._fill(item, v)
                item.setExpanded(True)
        else:
            # 标量根值（str/int/float/bool）：单行显示，不逐字符展开
            self.addTopLevelItem(QTreeWidgetItem(
                [str(raw_json), type(raw_json).__name__]))

    def _fill(self, parent: QTreeWidgetItem, obj):
        if isinstance(obj, dict):
            # 大数组降级标记 {"__ndarray__": [shape...], "dtype": ...}：
            # 单行紧凑显示 shape/dtype，不把 shape 列表展开成节点
            if "__ndarray__" in obj:
                shape = obj["__ndarray__"]
                dtype = obj.get("dtype", "?")
                parent.setText(0, f"{parent.text(0)}: （数组已降级）"
                                  f"shape={shape} dtype={dtype}")
                parent.setText(1, "ndarray")
                return
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
