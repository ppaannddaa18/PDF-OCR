"""结果视图：文档解析（左图右文 + 检测框高亮）与 JSON 树

观片台形态：左右两栏为「原页对开 + 誊写文本」双白卡，浮于冷钢灰画布上；
JSON 树为整卡白底数据页。所有样式 token 化 + apply_theme 刷新回调。
"""
import re

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
                             QTextBrowser, QTreeWidget, QTreeWidgetItem,
                             QCheckBox, QFrame, QLabel)
from app.models.page_result import PageResult
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.theme_manager import ThemeManager


def _html_document(fragment: str) -> str:
    """整页 HTML：样式集中放 <style> 块（保持 <h2>/<p>/<pre> 标签结构
    原样，既不破坏测试断言，也让 QTextBrowser 统一应用站内排印）"""
    t = ThemeManager
    css = (
        f"body {{ color: {t.get_color('text_primary')};"
        f"font-family: 'Microsoft YaHei UI', 'Segoe UI', sans-serif;"
        f"font-size: 14px; line-height: 1.6; margin: 0; }}"
        f"h2 {{ font-size: 17px; font-weight: 600; margin: 16px 0 8px;"
        f"padding-bottom: 6px; border-bottom: 1px solid "
        f"{t.get_color('border')}; }}"
        f"p {{ margin: 6px 0; }}"
        f"p.empty {{ color: {t.get_color('text_disabled')}; }}"
        f"pre {{ font-family: Consolas, 'Courier New', monospace;"
        f"font-size: 12.5px; background: {t.get_color('bg_hover')};"
        f"border-radius: {t.get_radius('sm')}px; padding: 10px 12px;"
        f"margin: 8px 0; line-height: 1.5;}}"
    )
    return (f"<html><head><style>{css}</style></head>"
            f"<body>{fragment}</body></html>")


class OcrDocView(QWidget):
    """文档解析视图：PDF 页渲染 + 结构化文本 + 检测框高亮开关"""
    boxes_toggled = pyqtSignal(bool)
    guide_clicked = pyqtSignal()  # 空态引导卡被点击（窗口接线：打开文件选择器）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_boxes = True
        self._last_result = None  # 最近一次 show_page 的结果（重新勾选时重放检测框）
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.splitter.setHandleWidth(8)
        self.canvas = PdfCanvas()
        self.canvas.set_drawing_enabled(False)  # 只读浏览
        # 预览右键平移由 PdfCanvas 只读分支统一提供（共享画布底层实现，
        # 本视图不装 viewport 事件过滤器——避免构造期事件提前派发）

        # 双白卡「页面对开」：左卡＝原页（画布），右卡＝誊写文本
        self.left_card = QFrame()
        left_layout = QVBoxLayout(self.left_card)
        left_layout.setContentsMargins(8, 8, 8, 8)
        left_layout.addWidget(self.canvas)
        self.right_card = QFrame()
        right_layout = QVBoxLayout(self.right_card)
        right_layout.setContentsMargins(8, 8, 8, 8)
        self.text_browser = QTextBrowser()
        right_layout.addWidget(self.text_browser)

        self.splitter.addWidget(self.left_card)
        self.splitter.addWidget(self.right_card)
        self.splitter.setSizes([480, 480])
        layout.addWidget(self.splitter, 1)
        toolbar = QHBoxLayout()
        self.boxes_check = QCheckBox("显示检测框")
        self.boxes_check.setChecked(True)
        self.boxes_check.toggled.connect(self._on_boxes_toggled)
        toolbar.addWidget(self.boxes_check)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

        # 两步引导层（未展示页面时覆盖左卡，替代共享画布的空态文案）：
        # 作为 left_card 的子控件，经 eventFilter 随卡片尺寸自动贴合；
        # 整卡可点击（hover 高亮 + 手型光标），点击 = 打开文件选择器
        self.guide_overlay = QWidget(self.left_card)
        self.guide_overlay.setCursor(Qt.CursorShape.PointingHandCursor)
        guide_layout = QVBoxLayout(self.guide_overlay)
        guide_layout.setContentsMargins(24, 24, 24, 24)
        guide_layout.setSpacing(10)
        guide_layout.addStretch(1)
        self.guide_title = QLabel("选择文件开始识别")
        self.guide_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guide_step1 = QLabel("① 点击「+ 加文件」添加文档")
        self.guide_step1.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.guide_step2 = QLabel("② 点击「解析」开始识别，完成后逐页浏览")
        self.guide_step2.setAlignment(Qt.AlignmentFlag.AlignCenter)
        guide_layout.addWidget(self.guide_title)
        guide_layout.addWidget(self.guide_step1)
        guide_layout.addWidget(self.guide_step2)
        guide_layout.addStretch(2)

        # 右栏占位说明（识别文本为空时覆盖显示在文本浏览器之上）
        self.text_placeholder = QLabel(
            "识别文本将显示在这里\n\n右上角可切换「JSON」查看原始结构")
        self.text_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.text_placeholder.setWordWrap(True)
        self.text_placeholder.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self.text_placeholder.setParent(self.right_card)

        self.left_card.installEventFilter(self)
        self.right_card.installEventFilter(self)
        self.guide_overlay.installEventFilter(self)
        self.apply_theme()
        ThemeManager.register_refresh_callback(self.apply_theme)
        self.show_guide()

    def apply_theme(self):
        """设计刷新回调：冷钢灰底 + 双白卡 + 文本内衬 + 引导层文字"""
        t = ThemeManager
        self.setObjectName('docView')
        self.setStyleSheet(
            f"QWidget#docView {{ background: {t.get_color('bg_primary')}; }}"
            f"QWidget#docView QSplitter::handle "
            f"{{ background: transparent; }}")
        card_qss = (f"QFrame {{ background: {t.get_color('bg_surface')};"
                    f"border: 1px solid {t.get_color('border')};"
                    f"border-radius: {t.get_radius('md')}px; }}")
        self.left_card.setStyleSheet(card_qss)
        self.right_card.setStyleSheet(card_qss)
        self.text_browser.setStyleSheet(
            f"QTextBrowser {{ background: transparent; border: none;"
            f"padding: {t.get_spacing('md')}px; color: "
            f"{t.get_color('text_primary')}; }}")
        self.boxes_check.setStyleSheet(
            f"color: {t.get_color('text_secondary')}; background: transparent;")
        self.guide_title.setStyleSheet(
            f"color: {t.get_color('text_primary')};"
            f"font-size: 16px; font-weight: 600;")
        self.guide_step1.setStyleSheet(
            f"color: {t.get_color('text_secondary')}; font-size: 13px;")
        self.guide_step2.setStyleSheet(
            f"color: {t.get_color('text_secondary')}; font-size: 13px;")
        self.text_placeholder.setStyleSheet(
            f"color: {t.get_color('text_secondary')};"
            f"font-size: 13px; background: transparent;")
        # 引导卡 hover 背景（accent 色 7% 透明度，静态预计算）
        c = QColor(t.get_color('primary'))
        c.setAlphaF(0.07)
        self._guide_hover_qss = (
            f"QWidget {{ background-color: rgba({c.red()}, {c.green()}, "
            f"{c.blue()}, {round(c.alphaF() * 255)}); }}")

    # ── 引导层 ──────────────────────────────────────────────

    def show_guide(self):
        """未展示页面时显示引导：隐藏画布共享空态，露出左卡引导 + 右栏占位"""
        self.guide_overlay.setGeometry(self.left_card.rect())
        self.guide_overlay.setVisible(True)
        self.text_placeholder.setGeometry(self.right_card.rect())
        self.text_placeholder.setVisible(True)
        hide_empty = getattr(self.canvas, '_hide_empty_state', None)
        if hide_empty is not None:
            try:
                hide_empty()
            except Exception:
                pass

    def hide_guide(self):
        self.guide_overlay.setVisible(False)
        self.text_placeholder.setVisible(False)

    def eventFilter(self, obj, event):
        """卡片尺寸变化时让引导层/占位贴合；引导卡可点击 + hover 反馈。

        异常防御：构造早期（子属性创建前）Qt 可能派发事件到已安装的
        过滤器，PyQt 事件过滤器内未捕获异常会触发 qFatal 硬崩（无输出），
        必须兜底。
        """
        try:
            return self._event_filter_inner(obj, event)
        except Exception:
            import traceback
            traceback.print_exc()
            return False

    def _event_filter_inner(self, obj, event):
        if event.type() == QEvent.Type.Resize:
            if obj is self.left_card:
                self.guide_overlay.setGeometry(self.left_card.rect())
            elif obj is self.right_card:
                self.text_placeholder.setGeometry(self.right_card.rect())
        elif obj is self.guide_overlay:
            if event.type() == QEvent.Type.Enter:
                self.guide_overlay.setStyleSheet(
                    getattr(self, "_guide_hover_qss", ""))
                return False
            if event.type() == QEvent.Type.Leave:
                self.guide_overlay.setStyleSheet("")
                return False
            if event.type() == QEvent.Type.MouseButtonRelease:
                if event.button() == Qt.MouseButton.LeftButton:
                    self.guide_clicked.emit()
                return False
        return super().eventFilter(obj, event)

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
        self.hide_guide()
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
        """清空视图：画布复位 + 文本/检测框/高亮清空 + 引导层恢复"""
        self.canvas.clear()
        self.text_browser.clear()
        self._last_result = None
        self.show_guide()

    @staticmethod
    def _blocks_to_html(result: PageResult) -> str:
        """markdown/块内容 → HTML：标题/段落、table 等宽、行内 <br>

        markdown 为整页结构化文本（优先）；markdown 为空时回退到 blocks 逐块渲染。
        两者皆空 → 灰色占位文案（无可解析内容）。
        """
        if not result.markdown and not result.blocks:
            return _html_document("<p class='empty'>无可解析内容</p>")
        if result.markdown:
            return _render_markdown(result.markdown)
        parts = []
        for b in result.blocks:
            content = str(b.content).replace("\n", "<br>")
            if b.block_type == "table":
                parts.append(f"<pre>{content}</pre>")
            else:
                parts.append(f"<p>{content}</p>")
        return _html_document("".join(parts))


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
    return _html_document("".join(parts))


class OcrJsonView(QTreeWidget):
    """JSON 树视图：递归构建可折叠树（基于 PageResult.raw_json）

    观片台形态：整树白卡页面，表头缀发丝线（border-bottom），类型列等宽字体。
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("原始解析结果（JSON）")
        self.setColumnCount(2)
        self.setHeaderLabels(["键 / 值", "类型"])
        self.apply_theme()
        ThemeManager.register_refresh_callback(self.apply_theme)

    def apply_theme(self):
        """设计刷新回调：白卡树 + 表头/悬停/选中 token 化"""
        t = ThemeManager
        self.setStyleSheet(
            f"QTreeWidget {{ background: {t.get_color('bg_surface')};"
            f"border: 1px solid {t.get_color('border')};"
            f"border-radius: {t.get_radius('md')}px;"
            f"outline: none; alternate-background-color: #F6F8FA; }}"
            f"QTreeWidget::item {{ padding: 5px 6px; }}"
            f"QTreeWidget::item:hover {{ background: "
            f"{t.get_color('bg_hover')}; }}"
            f"QTreeWidget::item:selected {{ background: "
            f"{t.get_color('bg_selected')}; color: "
            f"{t.get_color('text_primary')}; }}"
            f"QHeaderView::section {{ background: "
            f"{t.get_color('bg_surface')}; color: "
            f"{t.get_color('text_secondary')}; border: none;"
            f"border-bottom: 1px solid {t.get_color('border')};"
            f"padding: 7px 8px; font-weight: 600; }}")
        self.setAlternatingRowColors(True)

    def show_result(self, raw_json):
        self.clear()
        mono = ThemeManager.get_font('mono')
        if not raw_json:
            # 空 dict/None/空列表：占位行，不渲染空树
            item = QTreeWidgetItem(["（无 JSON 数据）", ""])
            item.setFont(1, mono)
            self.addTopLevelItem(item)
            return
        if isinstance(raw_json, dict):
            for k, v in raw_json.items():
                item = QTreeWidgetItem(
                    [str(k), "object" if isinstance(v, (dict, list)) else type(v).__name__])
                item.setFont(1, mono)
                self.addTopLevelItem(item)
                _expand_into(item, v, mono)
                item.setExpanded(True)
        elif isinstance(raw_json, (list, tuple)):
            # list/tuple 根值按索引铺开
            for i, v in enumerate(raw_json):
                item = QTreeWidgetItem(
                    [f"[{i}]", "object" if isinstance(v, (dict, list)) else type(v).__name__])
                item.setFont(1, mono)
                self.addTopLevelItem(item)
                _expand_into(item, v, mono)
                item.setExpanded(True)
        else:
            # 标量根值（str/int/float/bool）：单行显示，不逐字符展开
            item = QTreeWidgetItem(
                [str(raw_json), type(raw_json).__name__])
            item.setFont(1, mono)
            self.addTopLevelItem(item)


def _expand_into(node: QTreeWidgetItem, value, mono):
    """迭代把 value 的结构铺进 node 的子节点（显式栈，防深度递归爆栈）"""
    stack = [(node, value)]
    while stack:
        parent, v = stack.pop()
        if isinstance(v, dict):
            # 大数组降级标记 {"__ndarray__": [shape...], "dtype": ...}：
            # 单行紧凑显示 shape/dtype，不把 shape 列表展开成节点
            if "__ndarray__" in v:
                shape = v["__ndarray__"]
                dtype = v.get("dtype", "?")
                parent.setText(0, f"{parent.text(0)}: （数组已降级）"
                                  f"shape={shape} dtype={dtype}")
                parent.setText(1, "ndarray")
                parent.setFont(1, mono)
                continue
            for k, val in v.items():
                child = QTreeWidgetItem(
                    [str(k), "object" if isinstance(val, (dict, list))
                     else type(val).__name__])
                child.setFont(1, mono)
                parent.addChild(child)
                stack.append((child, val))
        elif isinstance(v, (list, tuple)):
            for i, val in enumerate(v):
                child = QTreeWidgetItem(
                    [f"[{i}]", "object" if isinstance(val, (dict, list))
                     else type(val).__name__])
                child.setFont(1, mono)
                parent.addChild(child)
                stack.append((child, val))
        else:
            # 叶子：键值同显（dict 键 或 列表 [i]），避免键被值覆盖
            parent.setText(0, f"{parent.text(0)}: {v}")
            parent.setText(1, type(v).__name__)
            parent.setFont(1, mono)