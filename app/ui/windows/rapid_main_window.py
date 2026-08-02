"""
RapidMainWindow — RapidOCR 双界面（轻量浅色工作台，Task P3b）

MRO 契约（硬性，详见 base_window.py 顶部注释）：
    RapidMainWindow → AppBaseWindowMixin → MSFluentWindow → ... → QWidget

构造协议：
    _init_app_base(config)（纯数据）必须在 super().__init__() 之前；
    工作区状态 _init_workspace_state()（纯数据）同样在 super().__init__()
    之前；_post_init_base()（UI 部件）在 super().__init__() 之后。

引擎路径固定 rapid：config["ocr"]["engine"] 强制 'rapidocr'（get_ocr_engine
据此构造 RapidOCREngine；GGUF 分支由 GgufMainWindow（P4）承担）。
窗口固定浅色配色（design=rapid，强调色 #0C8CE9），不监听系统主题。

工作区（模板识别）从旧 app/ui/main_window.py 机械迁移（只搬不改逻辑）：
    _create_template_page / 文件/框选/模板/预处理/试识别/批量识别/快捷键。
引擎选择下拉框与热切换逻辑已在 P4 删除（单会话一引擎，会话内固定 rapidocr）。
"""
import logging

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QDialog,
)
from qfluentwidgets import (
    MSFluentWindow,
    TransparentPushButton, StrongBodyLabel, BodyLabel,
    InfoBar, InfoBarPosition, ProgressBar, PushButton,
)

from app.ui.theme_manager import ThemeManager
from app.ui.windows.base_window import AppBaseWindowMixin
from app.core.template_manager import TemplateManager
from app.utils.lru_cache import LRUCache
from app.utils.command_history import CommandHistory
from app.models.region import Region


# qtawesome 延迟加载（与旧 main_window.py 一致）
qta = None

# UI 组件延迟导入缓存（P3b 机械迁移：保持旧文件的重型导入延迟策略）
_UiComponents = None


def _get_ui_components():
    """获取工作区 UI 组件（延迟加载）"""
    global _UiComponents
    if _UiComponents is None:
        from app.ui.widgets.pdf_canvas import PdfCanvas
        from app.ui.widgets.file_list_panel import FileListPanel
        from app.ui.widgets.field_panel import FieldPanel
        from app.ui.widgets.preprocess_toolbar import ImagePreprocessToolbar
        from app.ui.widgets.status_bar import StatusBar
        from app.workers.batch_worker import BatchWorker
        from app.utils.command_history import (
            AddRegionCommand, RemoveRegionCommand, UpdateRegionCommand,
            ClearAllCommand,
        )

        _UiComponents = type('UiComponents', (), {
            'PdfCanvas': PdfCanvas,
            'FileListPanel': FileListPanel,
            'FieldPanel': FieldPanel,
            'ImagePreprocessToolbar': ImagePreprocessToolbar,
            'StatusBar': StatusBar,
            'BatchWorker': BatchWorker,
            'AddRegionCommand': AddRegionCommand,
            'RemoveRegionCommand': RemoveRegionCommand,
            'UpdateRegionCommand': UpdateRegionCommand,
            'ClearAllCommand': ClearAllCommand,
        })()
    return _UiComponents


def _ensure_qta():
    """确保 qtawesome 已加载"""
    global qta
    if qta is None:
        import qtawesome
        qta = qtawesome
    return qta


def _icon(name: str, color: str = '#0C8CE9'):
    """获取图标（延迟加载 qtawesome）"""
    return _ensure_qta().icon(name, color=color)


class RapidMainWindow(AppBaseWindowMixin, MSFluentWindow):
    """RapidOCR 工作台：顶部标签 工作区 / 识别结果 / 历史记录"""

    WINDOW_TITLE = "PDF OCR — 文档工作台"
    WINDOW_ICON = 'fa5s.file-pdf'

    def __init__(self, config):
        # 固定 rapid 路径：config 引擎强制 rapidocr（构造期直接
        # get_ocr_engine 初始化按 rapid 路径，去掉 gguf 分支逻辑）
        config.setdefault("ocr", {})["engine"] = "rapidocr"
        self._init_app_base(config)  # pre-super：纯数据（config/世代/shutting_down/design）
        self._init_workspace_state()  # pre-super：工作区纯数据（模板/缓存/命令历史）
        super().__init__()
        logging.getLogger("PDFOCR").info(
            f"Session start | engine={self.engine_type} | design={self.design} | window=RapidMainWindow")
        self._post_init_base()  # post-super：UI 部件（页面/导航/引擎异步初始化）
        self._connect_signals()
        self._connect_focus_tracking()
        self._setup_shortcuts()

    # ── 工作区纯数据状态（pre-super；P3b 从旧 __init__ 提取） ─────

    def _init_workspace_state(self):
        """初始化工作区状态（模板/缓存/命令历史/引擎切换兼容字段）

        必须在 _post_init_base() 之前调用：_create_workspace_page 内部会
        消费 _last_engine_status（_create_status_bar 回放）与 gpu_status
        接线，其余字段供文件/框选/批量槽函数使用。
        """
        self.state_tooltip = None
        self._last_engine_status = ("", "unavailable")  # GpuStatusWidget.status_changed 最新值
        self._template_is_default = False  # apply_theme 重绘模板名颜色时使用
        self._default_template = None  # 第一个PDF的字段配置作为默认
        self._pdf_overrides = {}       # pdf_path -> Template，仅存储有特殊配置的PDF
        self._current_pdf = None       # 当前选中的PDF
        self._current_preview_result = None  # 当前PDF的试识别结果
        self._pdf_preview_results = LRUCache(max_size=50)  # pdf_path -> FileResult
        self.command_history = CommandHistory(max_size=20)
        self._current_preprocessor = None
        self._current_page_image = None  # 当前显示的PIL Image
        self._pdf_preprocessors = LRUCache(max_size=20)  # pdf_path -> ImagePreprocessor
        self.template_mgr = TemplateManager()

    # ── 工作区页（P3b：从旧 _create_template_page 机械迁移） ──────

    def _create_workspace_page(self) -> QWidget:
        """创建工作区页（模板编辑：左文件栏 | 中央画布 | 右字段面板）"""
        from PyQt6.QtWidgets import QPushButton
        from app.ui.widgets.collapsible_panel import CollapsiblePanel
        from app.ui.widgets.slidable_panel import SlidablePanel
        from app.ui.widgets.compact_toolbar import CompactToolbar

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 工具栏容器：CompactToolbar（engine_combo 接线 P4 删除） ──
        toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(4)

        # 单会话一引擎（P4）：Rapid 窗口不显示引擎选择下拉框
        self.toolbar = CompactToolbar(show_engine_selector=False)
        self.toolbar.upload_clicked.connect(self.on_upload)
        self.toolbar.test_ocr_clicked.connect(self.on_try_ocr)
        self.toolbar.batch_ocr_clicked.connect(self.on_batch_run)
        self.toolbar.save_template_clicked.connect(self.on_save_template)
        self.toolbar.load_template_clicked.connect(self.on_load_template)
        self.toolbar.settings_clicked.connect(self._on_settings_clicked)
        toolbar_layout.addWidget(self.toolbar, 1)

        # GPU 状态别名（兼容既有引用：_on_ocr_ready / closeEvent）
        self.gpu_status = self.toolbar.engine_status

        # 定位 CompactToolbar 内部的试识别/批量识别按钮（模式切换时显示/隐藏）
        for btn in self.toolbar.findChildren(QPushButton):
            tip = btn.toolTip()
            if tip == '试识别 (Ctrl+T)' and not hasattr(self, '_btn_try'):
                self._btn_try = btn
            elif tip == '批量识别 (Ctrl+Enter)' and not hasattr(self, '_btn_batch'):
                self._btn_batch = btn

        # 引擎状态桥接（GpuStatusWidget.status_changed 信号）
        self.gpu_status.status_changed.connect(self._on_gpu_status_changed)

        layout.addWidget(toolbar_container)

        # 进度条区域（默认隐藏）
        self.progress_widget = QWidget()
        progress_layout = QHBoxLayout(self.progress_widget)
        progress_layout.setContentsMargins(0, 0, 0, 0)
        self.progress_bar = ProgressBar()
        self.progress_bar.setFixedHeight(4)
        self.progress_label = BodyLabel("")
        progress_layout.addWidget(self.progress_bar, 1)
        progress_layout.addWidget(self.progress_label)
        self.progress_widget.setVisible(False)
        layout.addWidget(self.progress_widget)

        # ── 主内容区：单层水平布局（左 CollapsiblePanel | 中央工作区 | 右 SlidablePanel） ──
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        ui = _get_ui_components()

        # 左侧面板（可折叠 240 ↔ 48，内容为现有 FileListPanel）
        self.left_panel = CollapsiblePanel(expanded_width=240, collapsed_width=48)
        self.file_panel = ui.FileListPanel()
        self.left_panel.set_content(self.file_panel)
        # P6 签名：Rapid 卡片阴影（构造期 design 尚未切换，按类属性判断）
        if self.DESIGN == 'rapid':
            ThemeManager.apply_card_shadow(self.left_panel)
        content_layout.addWidget(self.left_panel)

        # 中央工作区
        self.workspace = QWidget()
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        # 图像预处理工具栏
        self.preprocess_toolbar = ui.ImagePreprocessToolbar()
        self.preprocess_toolbar.setEnabled(False)
        self.preprocess_toolbar.image_changed.connect(self._on_preprocess_changed)
        self.preprocess_toolbar.apply_to_all.connect(self._on_preprocess_apply_to_all)
        self.preprocess_toolbar.reset_requested.connect(self._on_preprocess_reset)
        self.preprocess_toolbar.apply_auto_contrast.connect(self._on_preprocess_auto_contrast)
        self.preprocess_toolbar.apply_sharpen.connect(self._on_preprocess_sharpen)
        workspace_layout.addWidget(self.preprocess_toolbar)

        # PDF 画布
        canvas_area = QWidget()
        canvas_area_layout = QHBoxLayout(canvas_area)
        canvas_area_layout.setContentsMargins(0, 0, 0, 0)
        canvas_area_layout.setSpacing(0)

        self.pdf_canvas = ui.PdfCanvas()
        canvas_area_layout.addWidget(self.pdf_canvas, 1)

        workspace_layout.addWidget(canvas_area, 1)

        # 底部状态栏
        status_bar = self._create_status_bar()
        workspace_layout.addWidget(status_bar)

        content_layout.addWidget(self.workspace, 1)

        # 右侧面板（可滑动 320，内容 = 模板信息 + 字段面板）
        self.right_panel = SlidablePanel(panel_width=320)
        self._right_title = self.right_panel.title_label
        self._right_title.setText("字段配置")

        right_content = QWidget()
        right_content_layout = QVBoxLayout(right_content)
        right_content_layout.setContentsMargins(0, 0, 0, 0)
        right_content_layout.setSpacing(4)

        # 模板信息区域
        self._template_info_widget = QWidget()
        template_info_layout = QVBoxLayout(self._template_info_widget)
        template_info_layout.setContentsMargins(8, 8, 8, 8)
        template_info_layout.setSpacing(4)

        # 模板名称标签（颜色经 ThemeManager 获取）
        self.template_name_label = BodyLabel("当前模板: 未配置")
        self.template_name_label.setStyleSheet(
            f"font-weight: bold; color: {ThemeManager.get_color('primary')};")
        template_info_layout.addWidget(self.template_name_label)

        # 设为默认模板按钮
        self.btn_set_default = PushButton("设为默认模板")
        self.btn_set_default.setToolTip("将当前字段配置设为默认模板，新加载的PDF将自动应用此配置")
        self.btn_set_default.clicked.connect(self._on_set_as_default_template)
        template_info_layout.addWidget(self.btn_set_default)

        # 分隔线
        from qfluentwidgets import HorizontalSeparator
        line = HorizontalSeparator(self)
        template_info_layout.addWidget(line)

        right_content_layout.addWidget(self._template_info_widget)

        # 字段面板（模板框选模式）
        self.field_panel = ui.FieldPanel()
        self.field_panel.setMinimumWidth(320)
        right_content_layout.addWidget(self.field_panel, 1)

        self.right_panel.set_content(right_content)
        if self.DESIGN == 'rapid':
            ThemeManager.apply_card_shadow(self.right_panel)
        content_layout.addWidget(self.right_panel)

        layout.addWidget(content, 1)

        return page

    # ── 信号接线 / 焦点跟踪（P3b 机械迁移） ──────────────────────

    def _connect_signals(self):
        self.file_panel.upload_requested.connect(self.on_upload)
        self.file_panel.file_selected.connect(self.on_file_selected)
        self.file_panel.files_cleared.connect(self._on_files_cleared)
        self.file_panel.file_removed.connect(self._on_file_removed)
        self.pdf_canvas.region_drawn.connect(self._on_region_drawn)
        self.pdf_canvas.region_updated.connect(self._on_region_updated_with_history)
        self.pdf_canvas.region_selected.connect(self._on_region_selected)
        self.field_panel.region_changed.connect(self.pdf_canvas.update_regions)
        self.field_panel.region_deleted.connect(self._on_region_deleted)
        self.field_panel.current_cleared.connect(self.on_clear_current_pdf_fields)
        self.field_panel.all_cleared.connect(self.on_clear_all_pdf_fields)
        self.field_panel.field_name_changed.connect(self.on_field_name_changed)
        self.field_panel.set_as_default_template.connect(self._on_set_as_default_template)

    def _connect_focus_tracking(self):
        """接线焦点跟踪：文件列表/画布/字段面板获得焦点时更新状态栏快捷键提示"""
        from PyQt6.QtWidgets import QApplication
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, _old: QWidget, new: QWidget):
        """应用焦点变化 → 状态栏快捷键提示区域"""
        area = 'global'
        if new is not None:
            if self.file_panel.isAncestorOf(new):
                area = 'file_list'
            elif self.pdf_canvas.isAncestorOf(new):
                area = 'pdf_preview'
            elif self.field_panel.isAncestorOf(new):
                area = 'field_panel'
        status_bar = getattr(self, 'status_bar', None)
        if status_bar is not None:
            status_bar.set_focus_area(area)

    # ── 文件/框选/模板/预处理处理（P3b 机械迁移） ─────────────────

    def _on_files_cleared(self):
        """文件列表清空时清理预览区域和所有配置"""
        self._current_pdf = None
        self._current_preview_result = None
        self._current_preprocessor = None
        self._pdf_overrides.clear()
        self._pdf_preprocessors.clear()
        self._pdf_preview_results.clear()
        self._default_template = None
        self.pdf_canvas.clear()
        self.field_panel.clear_all()
        self._set_template_name("未配置", is_default=False)
        self.preprocess_toolbar.setEnabled(False)
        self.status_label.setText("请上传PDF文件")

    def _on_file_removed(self, removed_path: str):
        """单个文件移除时的处理"""
        if removed_path in self._pdf_overrides:
            del self._pdf_overrides[removed_path]
        if removed_path in self._pdf_preprocessors:
            del self._pdf_preprocessors[removed_path]
        if removed_path in self._pdf_preview_results:
            del self._pdf_preview_results[removed_path]

        if removed_path == self._current_pdf:
            if self.file_panel.files:
                self.on_file_selected(self.file_panel.files[0])
            else:
                self._current_pdf = None
                self._current_preview_result = None
                self._current_preprocessor = None
                self.pdf_canvas.clear()
                self.field_panel.clear_all()
                self._set_template_name("未配置", is_default=False)
                self.preprocess_toolbar.setEnabled(False)
                self.status_label.setText("请上传PDF文件")

    def _on_region_drawn(self, region: Region):
        """区域绘制完成 - 添加到命令历史"""
        def add_region(r):
            self.field_panel.add_region(r)
            self.pdf_canvas.regions_data[r.id] = r

        def remove_region(rid):
            if rid in self.pdf_canvas.regions_data:
                del self.pdf_canvas.regions_data[rid]
            self.field_panel._delete(rid)

        ui = _get_ui_components()
        command = ui.AddRegionCommand(region, add_region, remove_region)
        self.command_history.execute(command)
        self._save_current_pdf_config()

    def _on_region_updated_with_history(self, region_id: str, new_region: Region):
        """区域更新 - 记录到命令历史"""
        if region_id not in self.field_panel.regions:
            return

        old_region = self.field_panel.regions[region_id]

        def update_region(r):
            self.field_panel.regions[r.id] = r
            self.pdf_canvas.regions_data[r.id] = r
            self.pdf_canvas.update_regions(list(self.field_panel.regions.values()))

        ui = _get_ui_components()
        command = ui.UpdateRegionCommand(region_id, old_region, new_region, update_region)
        self.command_history.execute(command)
        self._save_current_pdf_config()
        self.status_label.setText(f"区域已更新: {new_region.field_name}")

    def _on_region_deleted(self, region_id: str):
        """区域删除 - 同步删除画布上的框线并支持撤销"""
        region = self.pdf_canvas.regions_data.get(region_id)
        if region is None:
            return

        from copy import deepcopy
        ui = _get_ui_components()
        region_copy = deepcopy(region)

        def remove_region(rid):
            if rid in self.pdf_canvas.regions_data:
                del self.pdf_canvas.regions_data[rid]
            self.pdf_canvas.remove_region(rid)
            self._save_current_pdf_config()

        def add_region_back(r):
            self.field_panel.add_region(r)
            self.pdf_canvas.regions_data[r.id] = r
            self.pdf_canvas.update_regions([r])
            self._save_current_pdf_config()

        command = ui.RemoveRegionCommand(region_copy, remove_region, add_region_back)
        self.command_history.execute(command)

    def _on_region_selected(self, region_id: str):
        """区域被选中 - 同步选中表格行"""
        for row in range(self.field_panel.table.rowCount()):
            item = self.field_panel.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.field_panel.table.selectRow(row)
                break

    def _undo(self):
        """撤销操作"""
        if self.command_history.undo():
            self._refresh_canvas_and_panel()
            self.status_label.setText("已撤销 (Ctrl+Y 重做)")
        else:
            self.status_label.setText("没有可撤销的操作")

    def _redo(self):
        """重做操作"""
        if self.command_history.redo():
            self._refresh_canvas_and_panel()
            self.status_label.setText("已重做 (Ctrl+Z 撤销)")
        else:
            self.status_label.setText("没有可重做的操作")

    def _refresh_canvas_and_panel(self):
        """刷新画布和面板显示"""
        regions = list(self.field_panel.regions.values())
        self.pdf_canvas.update_regions(regions)
        template = self.field_panel.build_template()
        self.field_panel.load_template(template)
        self._save_current_pdf_config()

    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_panel.add_files(files)
            self.status_label.setText(f"已加载 {len(files)} 个文件 - 请框选识别区域")

    def _get_effective_template(self, pdf_path: str = None):
        """获取指定PDF的有效模板配置（覆盖配置 > 默认模板）"""
        if pdf_path and pdf_path in self._pdf_overrides:
            return self._pdf_overrides[pdf_path]
        return self._default_template

    def _save_current_pdf_config(self):
        """保存当前PDF的配置"""
        if self._current_pdf is None:
            return
        template = self.field_panel.build_template()

        if template.regions:
            self._pdf_overrides[self._current_pdf] = template
            if self._default_template and not self._is_template_different(template, self._default_template):
                self._set_template_name("默认模板", is_default=True)
            else:
                self._set_template_name("自定义配置", is_default=False)
        else:
            self._set_template_name("未配置", is_default=False)

        self._current_preview_result = None
        if self._current_pdf and self._current_pdf in self._pdf_preview_results:
            del self._pdf_preview_results[self._current_pdf]

        self._update_file_list_status()

    def _update_file_list_status(self):
        """更新文件列表中各PDF的配置状态"""
        for pdf_path in self.file_panel.files:
            if pdf_path in self._pdf_overrides:
                self.file_panel.set_pdf_config_status(pdf_path, "custom")
            elif self._default_template is not None:
                self.file_panel.set_pdf_config_status(pdf_path, "default")
            else:
                self.file_panel.set_pdf_config_status(pdf_path, "empty")

    def _set_template_name(self, name: str, is_default: bool = False):
        """设置当前模板名称显示"""
        self._template_is_default = is_default
        if is_default:
            self.template_name_label.setText(f"当前模板: 默认")
            self.template_name_label.setStyleSheet(
                f"font-weight: bold; color: {ThemeManager.get_color('success')};")
            self.btn_set_default.setEnabled(False)
            self.btn_set_default.setText("设为默认")
        else:
            self.template_name_label.setText(f"当前模板: {name}")
            self.template_name_label.setStyleSheet(
                f"font-weight: bold; color: {ThemeManager.get_color('primary')};")
            self.btn_set_default.setEnabled(True)
            self.btn_set_default.setText("设为默认模板")
        self.field_panel.set_template_name(name, is_default)

    def _on_set_as_default_template(self):
        """将当前配置设为默认模板"""
        template = self.field_panel.build_template()
        if not template.regions:
            InfoBar.warning(
                title="提示",
                content="当前没有字段配置，无法设为默认模板",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        if self._pdf_overrides:
            from qfluentwidgets import MessageBox
            msg = MessageBox(
                "确认设置默认模板",
                f"当前有 {len(self._pdf_overrides)} 个PDF文件使用了自定义配置。\n"
                "设为默认模板后，所有自定义配置将被丢弃。\n\n"
                "确定要继续吗？",
                self
            )
            msg.yesButton.setText("确认")
            msg.cancelButton.setText("取消")
            if not msg.exec():
                return

        self._default_template = template
        self._pdf_overrides.clear()
        self._set_template_name("默认模板", is_default=True)
        self._update_file_list_status()

        InfoBar.success(
            title="成功",
            content="已将当前配置设为默认模板",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def _is_template_different(self, t1, t2):
        """比较两个模板是否不同"""
        if len(t1.regions) != len(t2.regions):
            return True
        for r1, r2 in zip(t1.regions, t2.regions):
            if (r1.field_name != r2.field_name or
                r1.field_type != r2.field_type or
                r1.x != r2.x or r1.y != r2.y or
                r1.w != r2.w or r1.h != r2.h):
                return True
        return False

    def on_file_selected(self, pdf_path: str):
        # 保存当前PDF的配置和试识别结果
        self._save_current_pdf_config()

        if self._current_pdf and self._current_preprocessor:
            self._pdf_preprocessors[self._current_pdf] = self._current_preprocessor.get_params()

        if self._current_pdf and self._current_preview_result:
            self._pdf_preview_results[self._current_pdf] = self._current_preview_result

        self._current_pdf = pdf_path

        # 加载新 PDF 预览（自动保留已有的框选区域）
        try:
            image = self.pdf_loader.render_page(pdf_path)
        except Exception as e:
            InfoBar.error(
                title="PDF加载失败",
                content=f"无法渲染PDF文件: {e}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self
            )
            self.status_label.setText("PDF加载失败")
            self._current_pdf = None
            return

        from app.utils.image_preprocessor import ImagePreprocessor
        if pdf_path in self._pdf_preprocessors:
            params = self._pdf_preprocessors[pdf_path]
            self._current_preprocessor = ImagePreprocessor(image)
            self._current_preprocessor.set_params(params)
            self.preprocess_toolbar.set_params(params)
        else:
            self._current_preprocessor = ImagePreprocessor(image)
            self.preprocess_toolbar.set_params({
                'rotation': 0,
                'brightness': 1.0,
                'contrast': 1.0,
                'threshold': None,
                'auto_contrast_applied': False,
                'sharpen_applied': False,
            })

        self._current_page_image = self._current_preprocessor.get_current_image()

        self.pdf_canvas.load_image(self._current_page_image)
        self.preprocess_toolbar.setEnabled(True)

        template = self._get_effective_template(pdf_path)
        if template and template.regions:
            self.field_panel.load_template(template)
            self.pdf_canvas.update_regions(template.regions)
            if pdf_path in self._pdf_overrides:
                self._set_template_name("自定义配置", is_default=False)
            else:
                self._set_template_name("默认模板", is_default=True)
        else:
            self.field_panel.clear_all()
            self._set_template_name("未配置", is_default=False)

        preview_result = self._pdf_preview_results.get(pdf_path)
        if preview_result:
            self._current_preview_result = preview_result
            self.field_panel.show_preview_result(self._current_preview_result)
        else:
            self._current_preview_result = None
            self.field_panel._preview_results.clear()

        from pathlib import Path
        self.status_label.setText(f"当前: {Path(pdf_path).name} - 在画布上拖拽框选区域")

        try:
            self.file_panel.set_page_count(
                pdf_path, self.pdf_loader.page_count(pdf_path))
        except Exception:
            pass

    # ── 图像预处理 ──────────────────────────────────────────────

    def _on_preprocess_changed(self):
        """图像预处理参数改变"""
        if self._current_preprocessor:
            params = self.preprocess_toolbar.get_params()
            self._current_preprocessor.set_params(params)
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

    def _on_preprocess_apply_to_all(self):
        """将当前预处理应用到所有文件"""
        if self._current_preprocessor and self._current_pdf:
            params = self._current_preprocessor.get_params()
            for pdf_path in self.file_panel.files:
                if pdf_path == self._current_pdf:
                    continue
                self._pdf_preprocessors[pdf_path] = params.copy()
            InfoBar.success(
                title="成功",
                content=f"已将当前图像处理设置应用到 {len(self.file_panel.files)} 个文件",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )

    def _on_preprocess_reset(self):
        """重置图像预处理"""
        if self._current_preprocessor:
            self._current_preprocessor.reset()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

    def _on_preprocess_auto_contrast(self):
        """应用自动对比度"""
        if self._current_preprocessor:
            self._current_preprocessor.auto_contrast()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

    def _on_preprocess_sharpen(self):
        """应用锐化"""
        if self._current_preprocessor:
            self._current_preprocessor.sharpen()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

    # ── 试识别 / 批量识别（P3b 机械迁移） ────────────────────────

    def on_try_ocr(self):
        # 检查OCR引擎是否已初始化且 BatchProcessor 已创建
        if not self.ocr_engine.is_ready or self.processor is None:
            error_msg = self.ocr_engine.init_error
            if error_msg:
                InfoBar.error(
                    title="错误",
                    content=f"OCR引擎初始化失败: {error_msg}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
            else:
                InfoBar.warning(
                    title="提示",
                    content="OCR引擎正在加载中，请稍后再试",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            return

        template = self.field_panel.build_template()
        current_pdf = self.file_panel.current_file()
        if not current_pdf or not template.regions:
            InfoBar.warning(
                title="提示",
                content="请先上传PDF并框选区域",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        self.status_label.setText("正在试识别...")
        import threading

        def _do_try_ocr():
            try:
                result = self.processor.process_one(current_pdf, template)
                def _on_done():
                    self.field_panel.show_preview_result(result)
                    self._current_preview_result = result
                    self._pdf_preview_results[current_pdf] = result
                    self.status_label.setText(f"试识别完成 - 共 {len(template.regions)} 个字段")
                QTimer.singleShot(0, _on_done)
            except Exception as e:
                def _on_error():
                    InfoBar.error(
                        title="试识别失败",
                        content=str(e),
                        orient=Qt.Orientation.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=5000,
                        parent=self
                    )
                    self.status_label.setText("试识别失败")
                QTimer.singleShot(0, _on_error)

        threading.Thread(target=_do_try_ocr, daemon=True, name="TryOCR").start()

    def on_batch_run(self):
        # 防止重复点击启动多个 Worker
        if self.worker and self.worker.isRunning():
            InfoBar.warning(title="提示", content="批量识别正在进行中，请等待完成",
                            orient=Qt.Orientation.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2000, parent=self)
            return
        # 互斥守卫：关键字提取进行中不允许启动模板批量识别
        if getattr(self, '_keyword_worker', None) and self._keyword_worker.isRunning():
            InfoBar.warning(title="提示", content="关键字提取进行中，请等待完成",
                            orient=Qt.Orientation.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=2000, parent=self)
            return
        # 检查OCR引擎是否已初始化且 BatchProcessor 已创建
        if not self.ocr_engine.is_ready or self.processor is None:
            error_msg = self.ocr_engine.init_error
            if error_msg:
                InfoBar.error(
                    title="错误",
                    content=f"OCR引擎初始化失败: {error_msg}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
                    parent=self
                )
            else:
                InfoBar.warning(
                    title="提示",
                    content="OCR引擎正在加载中，请稍后再试",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=2000,
                    parent=self
                )
            return

        template = self.field_panel.build_template()
        files = self.file_panel.all_files()
        if not files or not template.regions:
            InfoBar.warning(
                title="提示",
                content="请先上传PDF并设置字段",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        self.progress_widget.setVisible(True)

        templates = []
        for f in files:
            t = self._get_effective_template(f)
            if t and t.regions:
                templates.append(t)
            else:
                templates.append(template)

        self._create_progress_dialog(files)

        ui = _get_ui_components()
        self.worker = ui.BatchWorker(self.processor, files, templates)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_batch_done)
        self.worker.cancelled.connect(self._on_batch_cancelled)
        self.worker.start()
        self.status_label.setText("批量识别进行中...")
        self.worker.finished_all.connect(self._clear_worker)
        self.worker.cancelled.connect(self._clear_worker)

    def _create_progress_dialog(self, files):
        """创建批量识别进度对话框"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QHBoxLayout

        self.progress_dialog = QDialog(self)
        self.progress_dialog.setWindowTitle("批量识别进度")
        self.progress_dialog.setFixedSize(400, 180)
        self.progress_dialog.setModal(False)

        layout = QVBoxLayout(self.progress_dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.progress_status_label = QLabel(f"正在处理: 0/{len(files)}")
        layout.addWidget(self.progress_status_label)

        self.progress_file_label = QLabel("准备开始...")
        self.progress_file_label.setStyleSheet("color: #666;")
        layout.addWidget(self.progress_file_label)

        self.progress_bar_dialog = QProgressBar()
        self.progress_bar_dialog.setRange(0, len(files))
        self.progress_bar_dialog.setValue(0)
        self.progress_bar_dialog.setTextVisible(True)
        layout.addWidget(self.progress_bar_dialog)

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.clicked.connect(self._cancel_batch)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        self.progress_dialog.show()

    def _cancel_batch(self):
        """取消批量识别"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.status_label.setText("正在取消批量识别...")

    def _on_batch_cancelled(self):
        """批量识别被取消时的处理 - 增强版，支持保存进度"""
        self.status_label.setText("批量识别已取消")

        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.progress_widget.setVisible(False)

        if not self.results and self.worker and hasattr(self.worker, '_completed_results'):
            self.results = self.worker._completed_results

        if self.results:
            completed = len(self.results)
            success = sum(1 for r in self.results if r.success)
            failed = completed - success
            total = len(self.file_panel.all_files())

            all_files = self.file_panel.all_files()
            remaining_files = all_files[completed:]

            from app.ui.widgets.cancel_result_dialog import CancelResultDialog
            dialog = CancelResultDialog(
                completed, success, failed, total,
                pending_files=remaining_files,
                results=self.results,
                parent=self
            )
            result = dialog.exec()

            if result == CancelResultDialog.VIEW_RESULTS:
                self.result_table.load_results(self.results)
                self.switchTo(self.result_page)
            elif result == CancelResultDialog.EXPORT:
                self.result_table.load_results(self.results)
                self.on_export()
            elif result == CancelResultDialog.CONTINUE:
                if remaining_files:
                    self.on_batch_run()
            elif result == CancelResultDialog.SAVE_AND_EXIT:
                InfoBar.success(
                    title="进度已保存",
                    content="下次启动时可恢复未完成的任务",
                    duration=3000,
                    parent=self
                )
                self.result_table.load_results(self.results)
                self.switchTo(self.result_page)
        else:
            InfoBar.warning(
                title="提示",
                content="批量识别已取消，尚未完成任何文件的识别",
                duration=3000,
                parent=self
            )

    def _on_progress(self, done, total, current_file):
        # 更新进度条
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done}/{total}")
        from pathlib import Path
        self.status_label.setText(f"处理中: {Path(current_file).name} ({done}/{total})")

        if current_file:
            self.file_panel.set_parse_status(current_file, 'parsing')

        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_bar_dialog.setValue(done)
            self.progress_status_label.setText(f"正在处理: {done}/{total}")
            self.progress_file_label.setText(f"当前文件: {Path(current_file).name}")

    def _clear_worker(self):
        """清理 worker 引用，避免内存泄漏"""
        self.worker = None

    def _on_batch_done(self, results):
        # 隐藏进度条
        self.progress_widget.setVisible(False)

        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.results = results
        self.result_table.load_results(results)

        for r in results:
            sf = getattr(r, 'source_file', None)
            if sf:
                self.file_panel.set_parse_status(
                    sf, 'success' if r.success else 'failed')

        self.history_manager.add_record(results)

        total = len(results)
        success = sum(1 for r in results if r.success)
        fail = total - success
        self.stat_total.setText(f"共 {total} 个文件")
        self.stat_success.setText(f"成功: {success}")
        self.stat_fail.setText(f"失败: {fail}")

        self.filter_field_combo.clear()
        self.filter_field_combo.addItem("全部字段")
        if results:
            field_names = []
            for r in results:
                for fn in r.fields:
                    if fn not in field_names:
                        field_names.append(fn)
            self.filter_field_combo.addItems(field_names)

        self.switchTo(self.result_page)
        self.navigationInterface.setCurrentItem('result')
        self.status_label.setText(f"批量识别完成 - 成功 {success}/{total}")

        self._pdf_preview_results.clear()
        self._current_preview_result = None

        InfoBar.success(
            title="完成",
            content=f"共处理 {len(results)} 个文件，成功 {success} 个",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=3000,
            parent=self
        )

    # ── 模板保存/加载/字段操作（P3b 机械迁移） ───────────────────

    def on_save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "", "JSON (*.json)")
        if path:
            template = self.field_panel.build_template()
            self.template_mgr.save(template, path)
            InfoBar.success(
                title="成功",
                content=f"模板已保存到 {path}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

    def on_load_template(self):
        """加载模板 - 增强版，支持预览"""
        path, _ = QFileDialog.getOpenFileName(self, "加载模板", "", "JSON (*.json)")
        if path:
            try:
                template = self.template_mgr.load(path)

                from app.ui.widgets.template_preview_dialog import TemplatePreviewDialog
                from pathlib import Path
                template_name = Path(path).stem

                preview_dialog = TemplatePreviewDialog(
                    template_name,
                    template.to_dict(),
                    self
                )

                if preview_dialog.exec() == QDialog.DialogCode.Accepted:
                    self.field_panel.load_template(template)
                    self.pdf_canvas.update_regions(template.regions)
                    InfoBar.success(
                        title="成功",
                        content=f"模板 '{template_name}' 已加载",
                        orient=Qt.Orientation.Horizontal,
                        isClosable=True,
                        position=InfoBarPosition.TOP,
                        duration=2000,
                        parent=self
                    )
            except Exception as e:
                InfoBar.error(
                    title="加载失败",
                    content=str(e),
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )

    def on_clear_current_pdf_fields(self):
        """清空当前PDF的字段配置，用户手动添加的配置将作为特殊配置"""
        if self._current_pdf is None:
            InfoBar.warning(
                title="提示",
                content="请先选择一个PDF文件",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        regions = list(self.field_panel.regions.values())

        def clear_regions():
            self.field_panel.clear_all()
            self.pdf_canvas.update_regions([])

        def restore_regions(saved_regions):
            self.field_panel.clear_all()
            for r in saved_regions:
                self.field_panel.add_region(r)
            self.pdf_canvas.update_regions(saved_regions)

        ui = _get_ui_components()
        command = ui.ClearAllCommand(regions, clear_regions, restore_regions)
        self.command_history.execute(command)

        from app.models.template import Template
        self._pdf_overrides[self._current_pdf] = Template(name="empty", regions=[])

        InfoBar.success(
            title="成功",
            content="已清空当前PDF的字段配置，可手动添加特殊配置",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_clear_all_pdf_fields(self):
        """清空所有PDF的字段配置"""
        regions = list(self.field_panel.regions.values())

        def clear_all():
            self._default_template = None
            self._pdf_overrides.clear()
            self._pdf_preview_results.clear()
            self.field_panel.clear_all()
            self.pdf_canvas.update_regions([])
            self._current_preview_result = None
            self.command_history.clear()

        def restore_all(saved_regions):
            for r in saved_regions:
                self.field_panel.add_region(r)
            self.pdf_canvas.update_regions(saved_regions)

        ui = _get_ui_components()
        command = ui.ClearAllCommand(regions, clear_all, restore_all)
        self.command_history.execute(command)

        InfoBar.success(
            title="成功",
            content="已清空所有PDF的字段配置",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def on_field_name_changed(self, region_id: str, old_name: str, new_name: str):
        """字段名变更处理 - 使用 region_id 精确定位"""
        if self._current_pdf is None:
            return

        if region_id is None or region_id not in self.field_panel.regions:
            return

        from app.utils.command_history import UpdateFieldNameCommand

        def update_field_name(rid, name):
            if rid in self.field_panel.regions:
                self.field_panel.regions[rid].field_name = name
                for row in range(self.field_panel.table.rowCount()):
                    item = self.field_panel.table.item(row, 0)
                    if item and item.data(Qt.ItemDataRole.UserRole) == rid:
                        item.setText(name)
                        break
                self.pdf_canvas.regions_data[rid].field_name = name

        command = UpdateFieldNameCommand(region_id, old_name, new_name, update_field_name)
        self.command_history.execute(command)

        template = self.field_panel.build_template()

        if self._current_pdf in self._pdf_overrides:
            self._pdf_overrides[self._current_pdf] = template
        elif self._default_template is not None:
            if self._is_template_different(template, self._default_template):
                self._pdf_overrides[self._current_pdf] = template
            else:
                self._default_template = template
        else:
            self._default_template = template

        if self._current_preview_result and old_name in self._current_preview_result.fields:
            field_result = self._current_preview_result.fields.pop(old_name)
            field_result.field_name = new_name
            self._current_preview_result.fields[new_name] = field_result

        self.status_label.setText(f"字段名已更新: {old_name} -> {new_name}")

    # ── 工具栏设置（引擎选择/热切换已在 P4 删除：单会话一引擎） ──

    def _on_gpu_status_changed(self, engine: str, status: str):
        """引擎状态变化记录 + 桥接到状态栏"""
        self._last_engine_status = (engine, status)
        status_bar = getattr(self, 'status_bar', None)
        if status_bar is not None:
            status_bar.set_engine_status(engine, status)

    def _on_settings_clicked(self):
        """打开 Rapid 设置对话框（P7：仅外观动画开关）"""
        from app.ui.widgets.rapid_settings_dialog import RapidSettingsDialog

        dialog = RapidSettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            patch = dialog.get_config_patch()
            self._merge_config_patch(self.config, patch)

            try:
                import yaml
                from pathlib import Path
                config_path = Path(__file__).parent.parent / "config.yaml"
                with open(config_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(self.config, f, allow_unicode=True, default_flow_style=False)

                InfoBar.success(
                    title="设置已保存",
                    content="配置已更新，下次启动时生效",
                    duration=3000,
                    parent=self
                )
            except Exception as e:
                logging.getLogger("PDFOCR").error(f"保存设置失败: {e}")
                InfoBar.error(
                    title="保存失败",
                    content=f"无法保存设置: {e}",
                    duration=5000,
                    parent=self
                )

    # ── 快捷键 / 面板切换（P3b 机械迁移） ────────────────────────

    def _setup_shortcuts(self):
        """设置快捷键（工作区子集）"""
        from PyQt6.QtGui import QShortcut, QKeySequence

        shortcut_upload = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_upload.setObjectName("Ctrl+O")
        shortcut_upload.activated.connect(self.on_upload)

        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.setObjectName("Ctrl+S")
        shortcut_save.activated.connect(self.on_save_template)

        shortcut_batch = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_batch.setObjectName("Ctrl+Return")
        shortcut_batch.activated.connect(self.on_batch_run)

        shortcut_try = QShortcut(QKeySequence("Ctrl+T"), self)
        shortcut_try.setObjectName("Ctrl+T")
        shortcut_try.activated.connect(self.on_try_ocr)

        shortcut_delete = QShortcut(QKeySequence("Delete"), self.field_panel)
        shortcut_delete.setObjectName("Delete")
        shortcut_delete.activated.connect(self._delete_selected_field)

        shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        shortcut_undo.setObjectName("Ctrl+Z")
        shortcut_undo.activated.connect(self._undo)

        shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        shortcut_redo.setObjectName("Ctrl+Y")
        shortcut_redo.activated.connect(self._redo)

        shortcut_left = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        shortcut_left.setObjectName("Ctrl+Shift+L")
        shortcut_left.activated.connect(self.left_panel.toggle)

        shortcut_right = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        shortcut_right.setObjectName("Ctrl+Shift+R")
        shortcut_right.activated.connect(self._toggle_right_panel)

        shortcut_new = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        shortcut_new.setObjectName("Ctrl+Shift+N")
        shortcut_new.activated.connect(self._on_new_template)

        shortcut_preview = QShortcut(QKeySequence("Space"), self)
        shortcut_preview.setObjectName("Space")
        shortcut_preview.activated.connect(self._on_quick_preview)

    def _toggle_right_panel(self):
        """Ctrl+Shift+R: 切换右侧面板"""
        if self.right_panel.is_visible():
            self.right_panel.slide_out()
        else:
            self.right_panel.slide_in()

    def _on_new_template(self):
        """Ctrl+Shift+N: 新建模板（清空当前字段配置，支持撤销）"""
        regions = list(self.field_panel.regions.values())
        ui = _get_ui_components()

        def clear_regions():
            self.field_panel.clear_all()
            self.pdf_canvas.update_regions([])

        def restore_regions(saved_regions):
            self.field_panel.clear_all()
            for r in saved_regions:
                self.field_panel.add_region(r)
            self.pdf_canvas.update_regions(saved_regions)

        command = ui.ClearAllCommand(regions, clear_regions, restore_regions)
        self.command_history.execute(command)
        self._current_preview_result = None
        self._default_template = None
        if self._current_pdf:
            from app.models.template import Template
            self._pdf_overrides[self._current_pdf] = Template(name="empty", regions=[])
        self._update_file_list_status()
        self._set_template_name("未配置", is_default=False)
        self.status_label.setText("已新建空白模板 - 在画布上拖拽框选区域")
        InfoBar.success(
            title="新建模板",
            content="已创建空白模板，请框选识别区域",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=2000,
            parent=self
        )

    def _on_quick_preview(self):
        """Space: 快速预览当前PDF（已有试识别结果则展示，否则给出提示）"""
        if not self._current_pdf:
            InfoBar.warning(
                title="提示",
                content="请先加载PDF文件",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        from pathlib import Path
        if self._current_preview_result:
            self.field_panel.show_preview_result(self._current_preview_result)
            self.status_label.setText(f"快速预览: {Path(self._current_pdf).name} - 试识别结果")
        else:
            self.status_label.setText(f"快速预览: {Path(self._current_pdf).name} - 按 Ctrl+T 试识别")

    def _delete_selected_field(self):
        """删除当前选中的字段"""
        current_row = self.field_panel.table.currentRow()
        if current_row >= 0:
            item = self.field_panel.table.item(current_row, 0)
            if item:
                region_id = item.data(Qt.ItemDataRole.UserRole)
                self._on_region_deleted(region_id)
