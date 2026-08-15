"""PaddleOCR-VL 独立识别主窗口（参考 AI Studio 文件任务页形态）

Task 9：单页窗口 —— 左侧解析队列 + 右侧源文件面板/双视图/工具按钮。
MRO：OcrMainWindow → AppBaseWindowMixin → FluentWindow → ... → QWidget。
构造协议：_init_app_base(config)（pre-super）→ super().__init__() →
_post_init_base()（post-super）。
"""
import json
import os
import logging
from datetime import datetime

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QSpinBox,
                             QFileDialog, QFrame, QApplication)
from qfluentwidgets import (FluentWindow, InfoBar, PushButton, BodyLabel,
                            setTheme, Theme, setThemeColor)

from app.ui.windows.base_window import AppBaseWindowMixin, _icon
from app.ui.theme_manager import ThemeManager
from app.core.ocr_doc_processor import OcrDocProcessor, is_image_file
from app.core.ocr_exporter import export_txt, export_markdown, export_json
from app.ui.widgets.ocr_file_panel import OcrFilePanel
from app.ui.widgets.ocr_result_views import OcrDocView, OcrJsonView
from app.ui.widgets.ocr_parse_config_dialog import OcrParseConfigDialog

logger = logging.getLogger("PDFOCR")

_HISTORY_FILE = "ocr_doc_history.json"


class OcrMainWindow(AppBaseWindowMixin, FluentWindow):
    """文档识别主窗口：左文件列表 + 右工作区（源文件面板/双视图/工具按钮）"""

    # 窗口标题跟随 config["app"]["name"]（独立程序标题可经 config.yaml 定制）
    WINDOW_TITLE = None
    DESIGN = 'paddle_vl'
    ACCENT_COLOR = '#1E7B5C'
    FLUENT_THEME = Theme.LIGHT

    def __init__(self, config):
        self._init_app_base(config)   # 必须在 super().__init__() 之前
        super().__init__()
        self._post_init_base()

    # ── 构造接线（post-super） ─────────────────────────────────

    def _post_init_base(self):
        super()._post_init_base()
        self._create_processor()
        self._restore_history()

    def _check_pending_task(self):
        pass  # 文档识别程序无待恢复任务

    def _on_ocr_ready(self):
        """引擎就绪回调（覆写 base）：文档窗口自管 OcrDocProcessor，
        不调用 super（base 会创建 BatchProcessor 并覆盖 self.processor）"""
        if hasattr(self, '_ready_gen') and self._ready_gen != self._init_gen:
            return
        if self.ocr_engine.is_ready:
            self.loading_overlay.hide_overlay()
        else:
            error_msg = self.ocr_engine.init_error or "未知错误"
            self.loading_overlay.show_error(error_msg)

    def _apply_design(self):
        """应用设计：ThemeManager 暂无 paddle_vl 设计表，映射 rapid
        （浅色暖纸 × 档案绿，强调色同为 #1E7B5C），不随系统主题变化。"""
        setTheme(self.FLUENT_THEME)
        setThemeColor(self.ACCENT_COLOR)
        ThemeManager.set_design('rapid')
        # 禁用 DWM 材质（同 base：截图工具不破坏窗口背景）
        self.setMicaEffectEnabled(False)
        if hasattr(self, 'navigationInterface') and hasattr(
                self.navigationInterface, 'setAcrylicEnabled'):
            self.navigationInterface.setAcrylicEnabled(False)

    # ── 页面构建覆写 ───────────────────────────────────────────

    def _register_sub_interfaces(self):
        """单页面布局：只注册工作区，不注册 result/history 页"""
        self.workspace_page.setObjectName('workspace')
        self.addSubInterface(self.workspace_page, _icon('fa5s.file'), '文档解析')
        self.switchTo(self.workspace_page)

    def _create_result_page(self) -> QWidget:
        """单页窗口：结果/历史页不注册导航，占位空页（避免构建无用重型组件）"""
        return self._placeholder_page("本窗口无识别结果页")

    def _create_history_page(self) -> QWidget:
        return self._placeholder_page("本窗口无历史记录页")

    def _placeholder_page(self, text: str) -> QWidget:
        page = QWidget()
        layout = QVBoxLayout(page)
        label = BodyLabel(text)
        label.setStyleSheet(f"color: {ThemeManager.get_color('text_secondary')};")
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        return page

    def _create_workspace_page(self) -> QWidget:
        """工作区：文件面板 + 源文件面板 + 视图区 + 底部状态行"""
        page = QWidget()
        root = QVBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)

        # 左侧文件面板 + 右侧工作区
        body = QHBoxLayout()
        body.setContentsMargins(0, 0, 0, 0)

        self.file_panel = OcrFilePanel()
        self.file_panel.setFixedWidth(240)
        self.file_panel.file_selected.connect(self._on_file_selected)
        self.file_panel.clear_requested.connect(self._on_files_cleared)
        body.addWidget(self.file_panel)

        right = QVBoxLayout()
        right.setContentsMargins(8, 0, 0, 0)
        right.addWidget(self._create_source_bar())
        right.addWidget(self._create_view_area(), 1)
        body.addLayout(right, 1)
        root.addLayout(body, 1)

        # 底部状态行（FluentWindow 非 QMainWindow，无 statusBar()，自建标签）
        self.status_label = BodyLabel("就绪")
        self.status_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        root.addWidget(self.status_label)
        return page

    def _create_source_bar(self) -> QWidget:
        """源文件面板：文件名/大小/页码导航/加文件 + 视图切换 + 工具按钮"""
        bar = QFrame()
        bar.setStyleSheet(
            f"background: {ThemeManager.get_color('bg_surface')};"
            f"border-radius: 8px;")
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(12, 8, 12, 8)

        self.file_label = BodyLabel("未选择文件")
        layout.addWidget(self.file_label, 1)

        # 页码导航
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(70)
        self.total_label = BodyLabel("/ 1")
        prev_btn = PushButton("◀")
        next_btn = PushButton("▶")
        prev_btn.clicked.connect(lambda: self.page_spin.setValue(
            self.page_spin.value() - 1))
        next_btn.clicked.connect(lambda: self.page_spin.setValue(
            self.page_spin.value() + 1))
        self.page_spin.valueChanged.connect(self._on_page_changed)
        layout.addWidget(prev_btn)
        layout.addWidget(self.page_spin)
        layout.addWidget(self.total_label)
        layout.addWidget(next_btn)
        layout.addSpacing(8)

        # 视图切换（文档解析 / JSON）
        self.view_doc_btn = PushButton("文档解析")
        self.view_json_btn = PushButton("JSON")
        self.view_doc_btn.setCheckable(True)
        self.view_json_btn.setCheckable(True)
        self.view_doc_btn.setChecked(True)
        self._active_view = "doc"  # 复制操作依据的当前视图
        self.view_doc_btn.clicked.connect(lambda: self._switch_view("doc"))
        self.view_json_btn.clicked.connect(lambda: self._switch_view("json"))
        layout.addWidget(self.view_doc_btn)
        layout.addWidget(self.view_json_btn)
        layout.addSpacing(8)

        # 工具按钮：配置 / 重新解析 / 复制 / 导出 / 添加文件
        for text, slot in [("≡ 配置", self._open_config_dialog),
                           ("↻", self._on_retry),
                           ("⧉", self._on_copy),
                           ("⇩", self._on_export)]:
            btn = PushButton(text)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        add_btn = PushButton("+ 加文件")
        add_btn.clicked.connect(self._on_add_files)
        layout.addWidget(add_btn)
        return bar

    def _create_view_area(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 8, 0, 0)
        self.doc_view = OcrDocView()
        self.json_view = OcrJsonView()
        self.json_view.setVisible(False)
        layout.addWidget(self.doc_view, 1)
        layout.addWidget(self.json_view, 1)
        return wrap

    # ── 文件与处理 ─────────────────────────────────────────────

    def add_files(self, paths):
        for p in paths:
            self.file_panel.add_file(p)
            self._add_history(p)
        self.processor.add_files(paths)
        self.processor.start()

    def _on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "",
            "文档/图片 (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if paths:
            self.add_files(paths)

    def _on_file_selected(self, path):
        pages = self.processor.get_cache(path)
        if pages:
            self._show_file(path, pages)
        else:
            # 未缓存 → 自动入队解析；导航复位到单页（防残留页号）
            self.file_label.setText(os.path.basename(path))
            self.page_spin.blockSignals(True)
            self.page_spin.setRange(1, 1)
            self.page_spin.setValue(1)
            self.page_spin.blockSignals(False)
            self.total_label.setText("/ 1")
            if not self.processor.is_running():
                self.processor.add_files([path])
                self.processor.start()

    def _on_files_cleared(self):
        self.processor.cancel()
        self.processor.clear_queue()  # 清空未处理条目，终止续跑
        self.processor.clear_cache()
        self.file_panel.clear()

    # ── 视图 ───────────────────────────────────────────────────

    def _switch_view(self, name):
        self._active_view = name
        self.view_doc_btn.setChecked(name == "doc")
        self.view_json_btn.setChecked(name == "json")
        self.doc_view.setVisible(name == "doc")
        self.json_view.setVisible(name == "json")

    def _on_page_changed(self, page_no):
        # 当前文件缓存页 → 重新渲染
        path = self.file_panel.selected_path()
        if not path:
            return
        pages = self.processor.get_cache(path)
        if pages and 1 <= page_no <= len(pages):
            self._render_page(path, pages[page_no - 1], page_no)

    def _show_file(self, path, pages):
        if not pages:
            return
        self.file_label.setText(f"{os.path.basename(path)} · {len(pages)} 页")
        self.total_label.setText(f"/ {len(pages)}")
        # blockSignals：setRange 钳位 / setValue(1) 都会触发 valueChanged
        # 导致 _on_page_changed 二次渲染，此处统一抑制
        self.page_spin.blockSignals(True)
        self.page_spin.setRange(1, len(pages))
        self.page_spin.setValue(1)
        self.page_spin.blockSignals(False)
        self._render_page(path, pages[0], 1)

    def _render_page(self, path, page_result, page_no):
        """渲染一页：PDF 渲染/图片 + 视图更新"""
        if is_image_file(path):
            from PIL import Image
            image = Image.open(path).convert("RGB")
        else:
            image = self.pdf_loader.render_page(path, page_no - 1)
        self.doc_view.show_page(page_result, image)
        self.json_view.show_result(page_result.raw_json)

    # ── 工具按钮 ───────────────────────────────────────────────

    def _open_config_dialog(self):
        dlg = OcrParseConfigDialog(self.config, self)
        dlg.apply_requested.connect(self._on_config_apply)
        dlg.exec()

    def _on_config_apply(self, patch):
        """保存配置 + 热生效（引擎 predict 参数即时读取；无需重启管线）"""
        self._merge_config_patch(self.config, patch)
        from app.utils.config_loader import save_config
        try:
            save_config(self.config)
        except Exception as e:
            logger.warning(f"配置保存失败: {e}")
        InfoBar.success(title="配置已应用", content="解析参数已更新",
                        parent=self, duration=2000)

    def _on_retry(self):
        path = self.file_panel.selected_path()
        if not path:
            return
        self.processor.clear_cache()
        if self.processor.is_running():
            # 运行中：取消当前批次并把目标重新入队；取消后 processor 续跑机制
            # 自动重跑（add_files 会把它从本次运行快照摘除，不被清出）
            self.processor.cancel()
            self.processor.add_files([path])
        else:
            self.processor.add_files([path])
            self.processor.start()

    def _on_copy(self):
        text = self._current_view_text()
        if not text:
            InfoBar.warning(title="无内容可复制", content="当前视图没有可复制的内容",
                            parent=self, duration=2000)
            return
        QApplication.clipboard().setText(text)
        InfoBar.success(title="已复制", content="当前视图内容已复制到剪贴板",
                        parent=self, duration=2000)

    def _current_view_text(self) -> str:
        """按当前视图取文本：doc → 文档视图纯文本；json → 树节点拼接"""
        if self._active_view == "json":
            return self._json_tree_text()
        return self.doc_view.text()

    def _json_tree_text(self) -> str:
        """JSON 树文本：递归拼接各 item 第 0 列（叶子为 '键: 值'）"""
        lines = []

        def walk(item):
            text = item.text(0)
            if text:
                lines.append(text)
            for i in range(item.childCount()):
                walk(item.child(i))

        root = self.json_view.invisibleRootItem()
        for i in range(root.childCount()):
            walk(root.child(i))
        return "\n".join(lines)

    def _on_export(self):
        path = self.file_panel.selected_path()
        pages = self.processor.get_cache(path) if path else None
        if not pages:
            InfoBar.error(title="无可导出内容", content="请先解析文件",
                          parent=self, duration=2000)
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out_dir:
            return
        base = os.path.splitext(os.path.basename(path))[0]
        files = export_txt(pages, out_dir, base)
        files += export_markdown(pages, out_dir, base)
        files += export_json(pages, out_dir, base)
        InfoBar.success(title="导出完成", content=f"{len(files)} 个文件",
                        parent=self, duration=3000)

    # ── 历史（轻量：路径+时间列表） ────────────────────────────

    def _history_path(self):
        return os.path.join(os.path.expanduser("~/.pdf_ocr_tool"),
                            _HISTORY_FILE)

    def _add_history(self, path):
        try:
            data = self._load_history()
            data = [p for p in data if p["path"] != path]
            data.insert(0, {"path": path,
                            "time": datetime.now().isoformat(timespec="seconds")})
            with open(self._history_path(), "w", encoding="utf-8") as f:
                json.dump(data[:50], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"历史写入失败: {e}")

    def _load_history(self):
        try:
            with open(self._history_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _restore_history(self):
        for entry in self._load_history():
            try:
                if os.path.exists(entry["path"]):
                    self.file_panel.add_file(entry["path"])
            except Exception as e:
                logger.warning(f"历史记录条目损坏，跳过: {e}")

    # ── 引擎/处理接线（post-init） ─────────────────────────────

    def _set_status(self, text: str):
        self.status_label.setText(text)

    def _create_processor(self):
        self.processor = OcrDocProcessor(self.pdf_loader, self.ocr_engine,
                                         self.config)
        self.processor.file_started.connect(
            lambda idx, total: self._set_status(f"解析中 {idx + 1}/{total}"))
        self.processor.page_progress.connect(
            lambda path, page, total, ms: self._set_status(
                f"{os.path.basename(path)} 第 {page}/{total} 页 "
                f"({ms / 1000:.1f}s)"))
        self.processor.file_done.connect(self._on_processor_file_done)
        self.processor.file_failed.connect(self._on_processor_file_failed)
        self.processor.all_done.connect(
            lambda: self._set_status("解析完成"))

    def _on_processor_file_done(self, path, pages):
        fid = self.file_panel.file_id_by_path(path)
        if fid:
            total = sum(1 for p in pages if p.markdown or p.blocks)
            self.file_panel.set_status(fid, "done",
                                       f"{len(pages)} 页 · 成功 {total}")
        if self.file_panel.selected_path() == path:
            self._show_file(path, pages)

    def _on_processor_file_failed(self, path, err):
        fid = self.file_panel.file_id_by_path(path)
        if fid:
            self.file_panel.set_status(fid, "failed", err)
        InfoBar.error(title="解析失败", content=f"{os.path.basename(path)}: {err}",
                      parent=self, duration=3000)
