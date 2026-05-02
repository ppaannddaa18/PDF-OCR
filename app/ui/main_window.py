"""
主窗口 - 性能优化版
- 延迟导入重型UI组件
- 异步初始化核心组件
"""
# 核心导入（必须同步加载）
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QStackedWidget, QSplitter, QDialog
)
from PyQt6.QtCore import Qt, QSize, QTimer
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition,
    TransparentToolButton, TransparentPushButton, SubtitleLabel,
    StrongBodyLabel, BodyLabel, InfoBar, InfoBarPosition,
    setTheme, Theme, ProgressBar, PushButton
)

# 延迟导入标记（实际导入在函数内部）
qta = None  # qtawesome 延迟加载

# UI组件延迟导入缓存
_UiComponents = None


def _get_ui_components():
    """获取UI组件（延迟加载）"""
    global _UiComponents
    if _UiComponents is None:
        from app.ui.widgets.pdf_canvas import PdfCanvas
        from app.ui.widgets.file_list_panel import FileListPanel
        from app.ui.widgets.field_panel import FieldPanel
        from app.ui.widgets.result_table import ResultTable
        from app.ui.widgets.history_panel import HistoryPanel
        from app.ui.widgets.preprocess_toolbar import ImagePreprocessToolbar
        from app.ui.widgets.loading_overlay import LoadingOverlay
        from app.workers.batch_worker import BatchWorker
        from app.utils.command_history import AddRegionCommand, RemoveRegionCommand, UpdateRegionCommand, ClearAllCommand

        _UiComponents = type('UiComponents', (), {
            'PdfCanvas': PdfCanvas,
            'FileListPanel': FileListPanel,
            'FieldPanel': FieldPanel,
            'ResultTable': ResultTable,
            'HistoryPanel': HistoryPanel,
            'ImagePreprocessToolbar': ImagePreprocessToolbar,
            'LoadingOverlay': LoadingOverlay,
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


def _icon(name: str, color: str = '#0078d4'):
    """获取图标（延迟加载qtawesome）"""
    return _ensure_qta().icon(name, color=color)


# 核心组件导入（轻量级）
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.core.batch_processor import BatchProcessor
from app.core.template_manager import TemplateManager
from app.core.exporter import Exporter
from app.utils.lru_cache import LRUCache
from app.utils.command_history import CommandHistory
from app.utils.history_manager import HistoryManager
from app.models.region import Region


class MainWindow(FluentWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(config["app"]["name"])
        self.resize(*config["app"]["window_size"])

        # 确保重型模块已加载
        _ensure_qta()

        # 设置主题（跟随系统）
        setTheme(Theme.AUTO)

        # 创建加载遮罩层（在创建其他组件之前）
        self._create_loading_overlay()

        # 核心组件
        self.pdf_loader = PdfLoader(dpi=config["pdf"]["render_dpi"])
        self.ocr_engine = OCREngine(
            lang=config["ocr"]["lang"],
            use_gpu=config["ocr"]["use_gpu"],
        )
        # 异步初始化OCR引擎
        self.ocr_engine.initialize_async(callback=self._on_ocr_ready)
        self.processor = BatchProcessor(
            self.pdf_loader, self.ocr_engine,
            max_workers=config["batch"]["max_workers"]
        )
        self.template_mgr = TemplateManager()
        self.exporter = Exporter()

        self.results = []
        self.worker = None
        self.state_tooltip = None

        # 字段配置存储：默认模板 + 特殊PDF的覆盖配置
        self._default_template = None  # 第一个PDF的字段配置作为默认
        self._pdf_overrides = {}       # pdf_path -> Template，仅存储有特殊配置的PDF
        self._current_pdf = None       # 当前选中的PDF
        self._current_preview_result = None  # 当前PDF的试识别结果
        self._pdf_preview_results = LRUCache(max_size=50)  # pdf_path -> FileResult，使用LRU缓存

        # 命令历史管理器
        self.command_history = CommandHistory(max_size=20)

        # 图像预处理
        self._current_preprocessor = None
        self._pdf_preprocessors = LRUCache(max_size=20)  # pdf_path -> ImagePreprocessor，使用LRU缓存

        # 历史记录管理器
        self.history_manager = HistoryManager()

        # 创建子页面
        self.template_page = self._create_template_page()
        self.result_page = self._create_result_page()
        self.history_page = self._create_history_page()

        # 初始化导航
        self._init_navigation()

        # 设置主内容区
        self.stackedWidget.addWidget(self.template_page)
        self.stackedWidget.addWidget(self.result_page)
        self.stackedWidget.addWidget(self.history_page)
        self.stackedWidget.setCurrentWidget(self.template_page)

        self._connect_signals()

        # 设置快捷键
        self._setup_shortcuts()

        # 检查是否有待恢复的任务
        QTimer.singleShot(500, self._check_pending_task)

    def _setup_shortcuts(self):
        """设置快捷键"""
        from PyQt6.QtGui import QShortcut, QKeySequence

        # Ctrl+O: 上传PDF
        shortcut_upload = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_upload.activated.connect(self.on_upload)

        # Ctrl+S: 保存模板
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.activated.connect(self.on_save_template)

        # Ctrl+Enter: 批量识别
        shortcut_batch = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_batch.activated.connect(self.on_batch_run)

        # Ctrl+T: 试识别
        shortcut_try = QShortcut(QKeySequence("Ctrl+T"), self)
        shortcut_try.activated.connect(self.on_try_ocr)

        # Delete: 删除选中字段（当字段表格有焦点时）
        shortcut_delete = QShortcut(QKeySequence("Delete"), self.field_panel)
        shortcut_delete.activated.connect(self._delete_selected_field)

        # Ctrl+Z: 撤销
        shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        shortcut_undo.activated.connect(self._undo)

        # Ctrl+Y: 重做
        shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        shortcut_redo.activated.connect(self._redo)

    def _delete_selected_field(self):
        """删除当前选中的字段"""
        # 获取当前选中的行
        current_row = self.field_panel.table.currentRow()
        if current_row >= 0:
            item = self.field_panel.table.item(current_row, 0)
            if item:
                region_id = item.data(Qt.ItemDataRole.UserRole)
                self._on_region_deleted(region_id)

    def _create_loading_overlay(self):
        """创建加载遮罩层"""
        ui = _get_ui_components()
        self.loading_overlay = ui.LoadingOverlay(self)
        self.loading_overlay.setGeometry(0, 0, self.width(), self.height())
        self.loading_overlay.show_loading()
        self.loading_overlay.raise_()
        self.loading_overlay.retry_requested.connect(self._on_ocr_retry)
        self.loading_overlay.use_cpu_mode_requested.connect(self._on_use_cpu_mode)

    def resizeEvent(self, event):
        """窗口大小改变时调整遮罩层大小"""
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(0, 0, self.width(), self.height())

    def _on_ocr_ready(self):
        """OCR引擎初始化完成回调"""
        if self.ocr_engine.is_ready:
            # 初始化成功，隐藏遮罩层
            self.loading_overlay.hide_overlay()
        else:
            # 初始化失败，显示错误面板
            error_msg = self.ocr_engine.init_error or "未知错误"
            self.loading_overlay.show_error(error_msg)

    def _on_ocr_retry(self):
        """OCR引擎重试初始化"""
        self.ocr_engine.initialize_async(callback=self._on_ocr_ready)

    def _on_use_cpu_mode(self):
        """切换到CPU模式并重试"""
        try:
            # 更新配置
            self.config["ocr"]["use_gpu"] = False
            # 重新创建OCR引擎
            self.ocr_engine = OCREngine(
                lang=self.config["ocr"]["lang"],
                use_gpu=False,
            )
            self.ocr_engine.initialize_async(callback=self._on_ocr_ready)
            # 更新批量处理器
            self.processor = BatchProcessor(
                self.pdf_loader, self.ocr_engine,
                max_workers=self.config["batch"]["max_workers"]
            )
            InfoBar.success(
                title="已切换到CPU模式",
                content="OCR引擎将以CPU模式运行，速度较慢但更稳定",
                duration=3000,
                parent=self
            )
        except Exception as e:
            InfoBar.error(
                title="切换失败",
                content=str(e),
                duration=3000,
                parent=self
            )

    def _check_pending_task(self):
        """检查是否有待恢复的批量任务"""
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog

        if CancelResultDialog.has_pending_task():
            task_data = CancelResultDialog.load_pending_task()
            if task_data:
                # 显示恢复提示
                from qfluentwidgets import MessageBox
                pending_count = len(task_data.get('pending_files', []))
                completed_count = task_data.get('completed', 0)

                msg = MessageBox(
                    "恢复待处理任务",
                    f"发现上次未完成的批量任务:\n"
                    f"已完成 {completed_count} 个文件\n"
                    f"剩余 {pending_count} 个文件待处理\n\n"
                    f"是否恢复该任务？",
                    self
                )
                msg.yesButton.setText("恢复任务")
                msg.cancelButton.setText("放弃任务")

                if msg.exec():
                    # 恢复任务
                    self._restore_pending_task(task_data)
                else:
                    # 放弃任务，清除文件
                    CancelResultDialog.clear_pending_task()

    def _restore_pending_task(self, task_data: dict):
        """恢复待处理的批量任务"""
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog

        pending_files = task_data.get('pending_files', [])
        if pending_files:
            # 添加待处理文件到列表
            self.file_panel.add_files(pending_files)

            InfoBar.success(
                title="任务已恢复",
                content=f"已加载 {len(pending_files)} 个待处理文件",
                duration=3000,
                parent=self
            )

            # 清除待恢复任务文件
            CancelResultDialog.clear_pending_task()

    def _init_navigation(self):
        """初始化侧边导航栏"""
        self.navigationInterface.addItem(
            routeKey='workspace',
            icon=_icon('fa5s.edit'),
            text='工作区',
            onClick=lambda: self.switchTo(self.template_page)
        )

        self.navigationInterface.addItem(
            routeKey='result',
            icon=_icon('fa5s.table'),
            text='识别结果',
            onClick=lambda: self.switchTo(self.result_page)
        )

        self.navigationInterface.addItem(
            routeKey='history',
            icon=_icon('fa5s.history'),
            text='历史记录',
            onClick=lambda: self.switchTo(self.history_page)
        )

        # 隐藏返回按钮
        self.navigationInterface.setReturnButtonVisible(False)

    def _create_template_page(self) -> QWidget:
        """创建模板编辑页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部工具栏
        toolbar = self._create_toolbar()
        layout.addWidget(toolbar)

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

        # 主内容区（三栏布局）
        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 使用 QSplitter 实现可拖拽调整
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # 左栏：文件列表（包含标题）
        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(4)

        from qfluentwidgets import SubtitleLabel
        ui = _get_ui_components()
        file_title = SubtitleLabel("文件列表")
        left_layout.addWidget(file_title)

        self.file_panel = ui.FileListPanel()
        self.file_panel.setMinimumWidth(220)
        self.file_panel.setMaximumWidth(400)
        left_layout.addWidget(self.file_panel, 1)

        # 中栏：PDF 画布
        canvas_container = QWidget()
        canvas_layout = QVBoxLayout(canvas_container)
        canvas_layout.setContentsMargins(0, 0, 0, 0)
        canvas_layout.setSpacing(4)

        canvas_title = SubtitleLabel("PDF 预览")
        canvas_layout.addWidget(canvas_title)

        # 图像预处理工具栏
        self.preprocess_toolbar = ui.ImagePreprocessToolbar()
        self.preprocess_toolbar.setEnabled(False)
        self.preprocess_toolbar.image_changed.connect(self._on_preprocess_changed)
        self.preprocess_toolbar.apply_to_all.connect(self._on_preprocess_apply_to_all)
        self.preprocess_toolbar.reset_requested.connect(self._on_preprocess_reset)
        self.preprocess_toolbar.apply_auto_contrast.connect(self._on_preprocess_auto_contrast)  # [修复]
        self.preprocess_toolbar.apply_sharpen.connect(self._on_preprocess_sharpen)  # [修复]
        canvas_layout.addWidget(self.preprocess_toolbar)

        self.pdf_canvas = ui.PdfCanvas()
        canvas_layout.addWidget(self.pdf_canvas, 1)

        # 右栏：字段配置（包含标题）
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)
        right_layout.setSpacing(4)

        field_title = SubtitleLabel("字段配置")
        right_layout.addWidget(field_title)

        # 模板信息区域（移到字段配置标题下方）
        template_info_widget = QWidget()
        template_info_layout = QVBoxLayout(template_info_widget)
        template_info_layout.setContentsMargins(8, 8, 8, 8)
        template_info_layout.setSpacing(4)

        # 模板名称标签
        self.template_name_label = BodyLabel("当前模板: 未配置")
        self.template_name_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        template_info_layout.addWidget(self.template_name_label)

        # 设为默认模板按钮
        self.btn_set_default = PushButton("设为默认模板")
        self.btn_set_default.setToolTip("将当前字段配置设为默认模板，新加载的PDF将自动应用此配置")
        self.btn_set_default.clicked.connect(self._on_set_as_default_template)
        template_info_layout.addWidget(self.btn_set_default)

        # 分隔线
        from PyQt6.QtWidgets import QFrame
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #e0e0e0;")
        line.setFixedHeight(1)
        template_info_layout.addWidget(line)

        right_layout.addWidget(template_info_widget)

        self.field_panel = ui.FieldPanel()
        self.field_panel.setMinimumWidth(320)
        self.field_panel.setMaximumWidth(450)
        right_layout.addWidget(self.field_panel, 1)

        # 添加到 splitter
        splitter.addWidget(left_panel)
        splitter.addWidget(canvas_container)
        splitter.addWidget(right_panel)

        # 设置初始比例 (左:中:右 = 1:4:1.5)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 4)
        splitter.setStretchFactor(2, 2)

        # 设置初始大小
        total_width = self.width()
        left_width = max(220, int(total_width * 0.15))
        right_width = max(300, int(total_width * 0.22))
        middle_width = total_width - left_width - right_width - 20
        splitter.setSizes([left_width, middle_width, right_width])

        content_layout.addWidget(splitter, 1)
        layout.addWidget(content, 1)

        # 底部状态栏
        status_bar = self._create_status_bar()
        layout.addWidget(status_bar)

        return page

    def _create_result_page(self) -> QWidget:
        """创建结果页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 顶部统计卡片
        stats_widget = self._create_stats_widget()
        layout.addWidget(stats_widget)

        # 筛选和工具栏
        toolbar = self._create_result_toolbar()
        layout.addWidget(toolbar)

        # 结果表格
        ui = _get_ui_components()
        self.result_table = ui.ResultTable()
        self.result_table.data_changed.connect(self._on_result_data_changed)
        layout.addWidget(self.result_table, 1)

        return page

    def _create_history_page(self) -> QWidget:
        """创建历史记录页面"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 历史记录面板
        ui = _get_ui_components()
        self.history_panel = ui.HistoryPanel(self.history_manager)
        self.history_panel.record_restored.connect(self._on_history_record_restored)
        layout.addWidget(self.history_panel)

        return page

    def _on_history_record_restored(self, record_id: str):
        """从历史记录恢复结果"""
        results = self.history_manager.restore_results(record_id)
        if results:
            self.results = results
            self.result_table.load_results(results)

            # 更新统计信息
            total = len(results)
            success = sum(1 for r in results if r.success)
            fail = total - success
            self.stat_total.setText(f"共 {total} 个文件")
            self.stat_success.setText(f"成功: {success}")
            self.stat_fail.setText(f"失败: {fail}")

            # 切换到结果页面
            self.switchTo(self.result_page)
            self.navigationInterface.setCurrentItem('result')

            InfoBar.success(
                title="成功",
                content=f"已恢复历史记录，共 {total} 个文件",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

    def _create_result_toolbar(self) -> QWidget:
        """创建结果页面工具栏"""
        from PyQt6.QtWidgets import QHBoxLayout
        from qfluentwidgets import LineEdit, ComboBox, PushButton

        toolbar = QWidget()
        layout = QHBoxLayout(toolbar)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(6)

        # 筛选输入框
        self.filter_edit = LineEdit()
        self.filter_edit.setPlaceholderText("筛选结果...")
        self.filter_edit.setMinimumWidth(180)
        self.filter_edit.setMaximumWidth(300)
        self.filter_edit.textChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_edit)

        # 字段筛选下拉框
        self.filter_field_combo = ComboBox()
        self.filter_field_combo.setMinimumWidth(100)
        self.filter_field_combo.addItem("全部字段")
        self.filter_field_combo.currentIndexChanged.connect(self._on_filter_changed)
        layout.addWidget(self.filter_field_combo)

        layout.addStretch()

        # 重置按钮
        btn_reset = PushButton("重置所有修改")
        btn_reset.setToolTip("将所有数据恢复为识别结果")
        btn_reset.setMinimumWidth(115)
        btn_reset.clicked.connect(self._on_reset_all_results)
        layout.addWidget(btn_reset)

        # 低置信度筛选按钮
        self.btn_low_conf = PushButton("显示低置信度")
        self.btn_low_conf.setToolTip("仅显示置信度低于70%的单元格")
        self.btn_low_conf.setMinimumWidth(110)
        self.btn_low_conf.clicked.connect(self._on_toggle_low_confidence)
        self._low_confidence_mode = False  # 低置信度筛选模式状态
        layout.addWidget(self.btn_low_conf)

        return toolbar

    def _on_result_data_changed(self):
        """结果数据变更处理"""
        modified = self.result_table.get_modified_count()
        if modified > 0:
            self.status_label.setText(f"已修改 {modified} 个单元格")

    def _on_filter_changed(self):
        """[修复] 筛选条件变更 - 支持全部字段筛选"""
        keyword = self.filter_edit.text()
        field_idx = self.filter_field_combo.currentIndex()

        if field_idx == 0:
            # 全部字段
            self.result_table.filter_by_field("全部字段", keyword)
        else:
            field_name = self.filter_field_combo.currentText()
            self.result_table.filter_by_field(field_name, keyword)

    def _on_reset_all_results(self):
        """重置所有结果"""
        self.result_table.reset_all()
        self.status_label.setText("已重置所有数据为识别结果")

    def _on_toggle_low_confidence(self):
        """切换低置信度筛选模式"""
        if self._low_confidence_mode:
            # 当前是低置信度模式，切换回显示全部
            self.result_table.show_all_rows()
            self._low_confidence_mode = False
            self.btn_low_conf.setText("显示低置信度")
            total_count = self.result_table.rowCount()
            self.status_label.setText(f"显示全部 {total_count} 个结果")
        else:
            # 当前是显示全部模式，切换到低置信度筛选
            self.result_table.filter_low_confidence(threshold=0.7)
            self._low_confidence_mode = True
            self.btn_low_conf.setText("显示全部")
            visible_count = sum(1 for row in range(self.result_table.rowCount())
                               if not self.result_table.isRowHidden(row))
            self.status_label.setText(f"显示 {visible_count} 个低置信度项（置信度<70%）")

    def _create_stats_widget(self) -> QWidget:
        """创建统计信息卡片"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(4, 2, 4, 2)
        layout.setSpacing(12)

        # 总数
        self.stat_total = StrongBodyLabel("共 0 个文件")
        layout.addWidget(self.stat_total)

        # 成功数
        self.stat_success = BodyLabel("成功: 0")
        self.stat_success.setStyleSheet("color: #107c10;")
        layout.addWidget(self.stat_success)

        # 失败数
        self.stat_fail = BodyLabel("失败: 0")
        self.stat_fail.setStyleSheet("color: #d13438;")
        layout.addWidget(self.stat_fail)

        layout.addStretch()

        # 导出按钮
        btn_export = TransparentPushButton("导出 Excel", self)
        btn_export.setIcon(_icon('fa5s.file-excel'))
        btn_export.setMinimumWidth(105)
        btn_export.clicked.connect(self.on_export)
        layout.addWidget(btn_export)

        return widget

    def _create_status_bar(self) -> QWidget:
        """创建底部状态栏"""
        bar = QWidget()
        bar.setFixedHeight(28)
        layout = QHBoxLayout(bar)
        layout.setContentsMargins(5, 0, 5, 0)

        self.status_label = BodyLabel("就绪 - 请上传 PDF 文件开始")
        layout.addWidget(self.status_label)
        layout.addStretch()

        # 快捷键提示
        shortcut_label = BodyLabel("Ctrl+O 上传 | Ctrl+S 保存模板 | Ctrl+T 试识别 | Ctrl+Enter 批量识别 | Delete 删除字段 | Ctrl+Z 撤销 | Ctrl+Y 重做")
        shortcut_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(shortcut_label)

        return bar

    def _create_toolbar(self) -> QWidget:
        """创建 Fluent 风格工具栏"""
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(4, 3, 4, 3)
        toolbar_layout.setSpacing(6)

        # 上传按钮（带文字）
        btn_upload = TransparentPushButton("上传 PDF", self)
        btn_upload.setIcon(_icon('fa5s.file-upload'))
        btn_upload.setMinimumWidth(105)
        btn_upload.setToolTip("上传PDF文件 (Ctrl+O)")
        btn_upload.clicked.connect(self.on_upload)
        toolbar_layout.addWidget(btn_upload)

        toolbar_layout.addSpacing(4)

        # 试识别按钮
        btn_try = TransparentPushButton("试识别", self)
        btn_try.setIcon(_icon('fa5s.search'))
        btn_try.setMinimumWidth(85)
        btn_try.setToolTip("试识别当前文件 (Ctrl+T)")
        btn_try.clicked.connect(self.on_try_ocr)
        toolbar_layout.addWidget(btn_try)

        # 批量识别按钮
        btn_batch = TransparentPushButton("批量识别", self)
        btn_batch.setIcon(_icon('fa5s.play', color='#107c10'))
        btn_batch.setMinimumWidth(95)
        btn_batch.setToolTip("批量识别所有文件 (Ctrl+Enter)")
        btn_batch.clicked.connect(self.on_batch_run)
        toolbar_layout.addWidget(btn_batch)

        toolbar_layout.addSpacing(8)

        # 分隔线
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setFixedHeight(20)
        sep.setStyleSheet("background: #e0e0e0;")
        toolbar_layout.addWidget(sep)

        toolbar_layout.addSpacing(8)

        # 保存模板按钮
        btn_save = TransparentPushButton("保存模板", self)
        btn_save.setIcon(_icon('fa5s.save'))
        btn_save.setMinimumWidth(95)
        btn_save.setToolTip("保存当前字段配置 (Ctrl+S)")
        btn_save.clicked.connect(self.on_save_template)
        toolbar_layout.addWidget(btn_save)

        # 加载模板按钮
        btn_load = TransparentPushButton("加载模板", self)
        btn_load.setIcon(_icon('fa5s.folder-open'))
        btn_load.setMinimumWidth(95)
        btn_load.setToolTip("加载已保存的模板")
        btn_load.clicked.connect(self.on_load_template)
        toolbar_layout.addWidget(btn_load)

        toolbar_layout.addStretch()
        return toolbar

    def _connect_signals(self):
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

    def _on_files_cleared(self):
        """文件列表清空时清理预览区域和所有配置"""
        self._current_pdf = None
        self._current_preview_result = None
        self._current_preprocessor = None
        # 清空所有PDF的配置信息
        self._pdf_overrides.clear()
        self._pdf_preprocessors.clear()
        self._pdf_preview_results.clear()
        self._default_template = None
        # 清空画布和字段面板
        self.pdf_canvas.clear()
        self.field_panel.clear_all()
        self._set_template_name("未配置", is_default=False)
        self.preprocess_toolbar.setEnabled(False)
        self.status_label.setText("请上传PDF文件")

    def _on_file_removed(self, removed_path: str):
        """单个文件移除时的处理"""
        # 清理该文件的相关缓存
        if removed_path in self._pdf_overrides:
            del self._pdf_overrides[removed_path]
        if removed_path in self._pdf_preprocessors:
            del self._pdf_preprocessors[removed_path]
        if removed_path in self._pdf_preview_results:
            del self._pdf_preview_results[removed_path]

        # 如果移除的是当前显示的文件，检查是否还有其他文件
        if removed_path == self._current_pdf:
            if self.file_panel.files:
                # 还有其他文件，切换到第一个
                self.on_file_selected(self.file_panel.files[0])
            else:
                # 没有其他文件，恢复初始状态
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
            self.field_panel._delete(rid)
            if rid in self.pdf_canvas.regions_data:
                del self.pdf_canvas.regions_data[rid]

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
        # 从画布数据中获取区域
        region = self.pdf_canvas.regions_data.get(region_id)
        if region is None:
            return

        # 保存区域副本用于撤销
        from copy import deepcopy
        ui = _get_ui_components()
        region_copy = deepcopy(region)

        def remove_region(rid):
            # 删除画布上的区域
            if rid in self.pdf_canvas.regions_data:
                del self.pdf_canvas.regions_data[rid]
            self.pdf_canvas.remove_region(rid)
            # 从字段面板删除
            self.field_panel._delete(rid)
            self._save_current_pdf_config()

        def add_region_back(r):
            # 恢复区域
            self.field_panel.add_region(r)
            self.pdf_canvas.regions_data[r.id] = r
            self.pdf_canvas.update_regions([r])
            self._save_current_pdf_config()

        # 使用命令模式支持撤销
        command = ui.RemoveRegionCommand(region_copy, remove_region, add_region_back)
        self.command_history.execute(command)

    def _on_region_selected(self, region_id: str):
        """区域被选中 - 同步选中表格行"""
        # 在字段面板中选中对应的行
        for row in range(self.field_panel.table.rowCount()):
            item = self.field_panel.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.field_panel.table.selectRow(row)
                break

    def on_region_updated(self, region_id: str, region: Region):
        """区域更新处理（拖拽移动或调整大小后）"""
        # 更新字段面板中的区域数据
        if region_id in self.field_panel.regions:
            old_region = self.field_panel.regions[region_id]
            self.field_panel.regions[region_id] = region
            # 更新当前PDF的模板配置
            self._save_current_pdf_config()
            self.status_label.setText(f"区域已更新: {region.field_name}")

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

    def switchTo(self, page: QWidget):
        """切换到指定页面"""
        self.stackedWidget.setCurrentWidget(page)

    # ---------- 事件处理 ----------
    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_panel.add_files(files)
            # 将首份作为模板
            self.on_file_selected(files[0])
            self.status_label.setText(f"已加载 {len(files)} 个文件 - 请框选识别区域")

    def _get_effective_template(self, pdf_path: str = None):
        """获取指定PDF的有效模板配置

        优先级：
        1. 如果PDF在_pdf_overrides中，使用覆盖配置（即使是空的）
        2. 否则使用默认模板
        """
        if pdf_path and pdf_path in self._pdf_overrides:
            return self._pdf_overrides[pdf_path]
        return self._default_template

    def _save_current_pdf_config(self):
        """保存当前PDF的配置"""
        if self._current_pdf is None:
            return
        template = self.field_panel.build_template()

        # 如果有字段配置，保存为当前PDF的特殊配置（自定义配置）
        if template.regions:
            self._pdf_overrides[self._current_pdf] = template
            # 判断是否与默认模板相同
            if self._default_template and not self._is_template_different(template, self._default_template):
                self._set_template_name("默认模板", is_default=True)
            else:
                self._set_template_name("自定义配置", is_default=False)
        else:
            # 当前没有字段配置
            self._set_template_name("未配置", is_default=False)

        # 更新文件列表中的配置状态显示
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
        """设置当前模板名称显示（在主窗口中）"""
        if is_default:
            self.template_name_label.setText(f"当前模板: 默认")
            self.template_name_label.setStyleSheet("font-weight: bold; color: #107c10;")
            self.btn_set_default.setEnabled(False)
            self.btn_set_default.setText("设为默认")
        else:
            self.template_name_label.setText(f"当前模板: {name}")
            self.template_name_label.setStyleSheet("font-weight: bold; color: #0078d4;")
            self.btn_set_default.setEnabled(True)
            self.btn_set_default.setText("设为默认模板")
        # 同时更新field_panel中的记录
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

        self._default_template = template
        # 清除所有特殊配置（因为现在都使用新的默认模板）
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

        # 保存当前PDF的预处理参数
        if self._current_pdf and self._current_preprocessor:
            self._pdf_preprocessors[self._current_pdf] = self._current_preprocessor.get_params()

        if self._current_pdf and self._current_preview_result:
            self._pdf_preview_results[self._current_pdf] = self._current_preview_result

        self._current_pdf = pdf_path

        # 加载新 PDF 预览（自动保留已有的框选区域）
        image = self.pdf_loader.render_page(pdf_path)

        # 初始化或恢复图像预处理器
        from app.utils.image_preprocessor import ImagePreprocessor
        if pdf_path in self._pdf_preprocessors:
            params = self._pdf_preprocessors[pdf_path]
            self._current_preprocessor = ImagePreprocessor(image)
            self._current_preprocessor.set_params(params)
            # 恢复预处理工具栏的参数显示
            self.preprocess_toolbar.set_params(params)
        else:
            self._current_preprocessor = ImagePreprocessor(image)
            # 重置预处理工具栏为默认值
            self.preprocess_toolbar.set_params({
                'rotation': 0,
                'brightness': 1.0,
                'contrast': 1.0,
                'threshold': None,
                'auto_contrast_applied': False,
                'sharpen_applied': False,
            })

        self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
        self.preprocess_toolbar.setEnabled(True)

        # 加载该PDF的字段配置（默认或特殊配置）
        template = self._get_effective_template(pdf_path)
        if template and template.regions:
            self.field_panel.load_template(template)
            self.pdf_canvas.update_regions(template.regions)
            # 更新模板名称显示
            if pdf_path in self._pdf_overrides:
                self._set_template_name("自定义配置", is_default=False)
            else:
                self._set_template_name("默认模板", is_default=True)
        else:
            # 没有配置时清空字段面板
            self.field_panel.clear_all()
            self._set_template_name("未配置", is_default=False)

        # 恢复该PDF的试识别结果（如果有）
        preview_result = self._pdf_preview_results.get(pdf_path)
        if preview_result:
            self._current_preview_result = preview_result
            self.field_panel.show_preview_result(self._current_preview_result)
        else:
            # 清空试识别结果
            self._current_preview_result = None
            self.field_panel._preview_results.clear()

        from pathlib import Path
        self.status_label.setText(f"当前: {Path(pdf_path).name} - 在画布上拖拽框选区域")

    def _on_preprocess_changed(self):
        """图像预处理参数改变"""
        if self._current_preprocessor:
            params = self.preprocess_toolbar.get_params()
            self._current_preprocessor.set_params(params)
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())

    def _on_preprocess_apply_to_all(self):
        """将当前预处理应用到所有文件"""
        if self._current_preprocessor and self._current_pdf:
            params = self._current_preprocessor.get_params()
            # 应用到所有已加载的PDF文件
            for pdf_path in self.file_panel.files:
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

    def _on_preprocess_auto_contrast(self):
        """[修复] 应用自动对比度"""
        if self._current_preprocessor:
            self._current_preprocessor.auto_contrast()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())

    def _on_preprocess_sharpen(self):
        """[修复] 应用锐化"""
        if self._current_preprocessor:
            self._current_preprocessor.sharpen()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())

    def on_try_ocr(self):
        # 检查OCR引擎是否已初始化
        if not self.ocr_engine.is_ready:
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
        result = self.processor.process_one(current_pdf, template)
        self.field_panel.show_preview_result(result)
        self._current_preview_result = result
        # 保存到持久化存储
        self._pdf_preview_results[current_pdf] = result
        self.status_label.setText(f"试识别完成 - 共 {len(template.regions)} 个字段")

    def on_batch_run(self):
        # 检查OCR引擎是否已初始化
        if not self.ocr_engine.is_ready:
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

        # 为每个文件准备对应的模板
        templates = []
        for f in files:
            t = self._get_effective_template(f)
            if t and t.regions:
                templates.append(t)
            else:
                templates.append(template)  # 使用当前界面上的配置

        # 创建并显示进度对话框
        self._create_progress_dialog(files)

        ui = _get_ui_components()
        self.worker = ui.BatchWorker(self.processor, files, templates)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_batch_done)
        self.worker.cancelled.connect(self._on_batch_cancelled)
        self.worker.start()
        self.status_label.setText("批量识别进行中...")

    def _create_progress_dialog(self, files):
        """创建批量识别进度对话框"""
        from PyQt6.QtWidgets import QDialog, QVBoxLayout, QProgressBar, QLabel, QPushButton, QHBoxLayout

        self.progress_dialog = QDialog(self)
        self.progress_dialog.setWindowTitle("批量识别进度")
        self.progress_dialog.setFixedSize(400, 180)
        self.progress_dialog.setModal(True)

        layout = QVBoxLayout(self.progress_dialog)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        # 状态标签
        self.progress_status_label = QLabel(f"正在处理: 0/{len(files)}")
        layout.addWidget(self.progress_status_label)

        # 当前文件名
        self.progress_file_label = QLabel("准备开始...")
        self.progress_file_label.setStyleSheet("color: #666;")
        layout.addWidget(self.progress_file_label)

        # 进度条
        self.progress_bar_dialog = QProgressBar()
        self.progress_bar_dialog.setRange(0, len(files))
        self.progress_bar_dialog.setValue(0)
        self.progress_bar_dialog.setTextVisible(True)
        layout.addWidget(self.progress_bar_dialog)

        # 按钮区域
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
            # 不在这里关闭进度对话框，等待 _on_batch_done 处理

    def _on_batch_cancelled(self):
        """批量识别被取消时的处理 - 增强版，支持保存进度"""
        self.status_label.setText("批量识别已取消")

        # 关闭进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        # 隐藏进度条
        self.progress_widget.setVisible(False)

        # 显示取消结果对话框
        if self.results:
            completed = len(self.results)
            success = sum(1 for r in self.results if r.success)
            failed = completed - success
            total = len(self.file_panel.all_files())

            # 计算剩余文件
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
                # 切换到结果页面
                self.result_table.load_results(self.results)
                self.switchTo(self.result_page)
            elif result == CancelResultDialog.EXPORT:
                # 导出已完成的结果
                self.result_table.load_results(self.results)
                self.on_export()
            elif result == CancelResultDialog.CONTINUE:
                # 继续识别剩余文件
                if remaining_files:
                    self.on_batch_run()
            elif result == CancelResultDialog.SAVE_AND_EXIT:
                # 保存进度并退出 - 进度已在对话框中保存
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

        # 更新进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_bar_dialog.setValue(done)
            self.progress_status_label.setText(f"正在处理: {done}/{total}")
            self.progress_file_label.setText(f"当前文件: {Path(current_file).name}")

    def _on_batch_done(self, results):
        # 隐藏进度条
        self.progress_widget.setVisible(False)

        # 关闭进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()
            self.progress_dialog = None

        self.results = results
        self.result_table.load_results(results)

        # 保存到历史记录
        self.history_manager.add_record(results)

        # 更新统计信息
        total = len(results)
        success = sum(1 for r in results if r.success)
        fail = total - success
        self.stat_total.setText(f"共 {total} 个文件")
        self.stat_success.setText(f"成功: {success}")
        self.stat_fail.setText(f"失败: {fail}")

        # 更新筛选下拉框
        self.filter_field_combo.clear()
        self.filter_field_combo.addItem("全部字段")
        if results:
            field_names = []
            for r in results:
                for fn in r.fields:
                    if fn not in field_names:
                        field_names.append(fn)
            self.filter_field_combo.addItems(field_names)

        # 切换到结果页面并更新导航选中状态
        self.switchTo(self.result_page)
        self.navigationInterface.setCurrentItem('result')
        self.status_label.setText(f"批量识别完成 - 成功 {success}/{total}")

        # 批量识别后清空所有试识别结果
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

    def on_export(self):
        if not self.results:
            InfoBar.warning(
                title="提示",
                content="尚无识别结果",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出Excel", "result.xlsx", "Excel (*.xlsx)")
        if path:
            # 如用户在表格里手动编辑过，需同步回 self.results
            self.results = self.result_table.collect_results()
            include_conf = self.config["export"]["include_confidence"]
            self.exporter.to_excel(self.results, path, include_conf)
            InfoBar.success(
                title="成功",
                content=f"已导出到 {path}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )

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

                # 显示预览对话框
                from app.ui.widgets.template_preview_dialog import TemplatePreviewDialog
                from pathlib import Path
                template_name = Path(path).stem

                preview_dialog = TemplatePreviewDialog(
                    template_name,
                    template.to_dict(),
                    self
                )

                if preview_dialog.exec() == QDialog.DialogCode.Accepted:
                    # 用户确认加载
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

        # 记录清空操作到历史
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

        # 将该PDF标记为需要特殊配置（空配置作为占位）
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
        # 记录清空操作到历史
        regions = list(self.field_panel.regions.values())

        def clear_all():
            # 清空默认配置
            self._default_template = None
            # 清空所有特殊配置
            self._pdf_overrides.clear()
            # 清空所有试识别结果
            self._pdf_preview_results.clear()
            # 清空当前显示
            self.field_panel.clear_all()
            self.pdf_canvas.update_regions([])
            # 清空试识别结果
            self._current_preview_result = None
            # 清空历史
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

    def on_field_name_changed(self, old_name: str, new_name: str):
        """字段名变更处理 - [修复] 使用命令模式记录到历史"""
        if self._current_pdf is None:
            return

        # 查找对应的 region_id
        region_id = None
        for rid, region in self.field_panel.regions.items():
            if region.field_name == new_name:
                region_id = rid
                break

        if region_id is None:
            return

        # [修复] 创建 UpdateFieldNameCommand 记录到历史
        from app.utils.command_history import UpdateFieldNameCommand

        def update_field_name(rid, name):
            if rid in self.field_panel.regions:
                self.field_panel.regions[rid].field_name = name
                # 更新表格显示
                for row in range(self.field_panel.table.rowCount()):
                    item = self.field_panel.table.item(row, 0)
                    if item and item.data(Qt.ItemDataRole.UserRole) == rid:
                        item.setText(name)
                        break
                self.pdf_canvas.regions_data[rid].field_name = name

        command = UpdateFieldNameCommand(region_id, old_name, new_name, update_field_name)
        self.command_history.execute(command)

        # 更新当前PDF的模板配置
        template = self.field_panel.build_template()

        # 判断是更新默认模板还是特殊配置
        if self._current_pdf in self._pdf_overrides:
            self._pdf_overrides[self._current_pdf] = template
        elif self._default_template is not None:
            if self._is_template_different(template, self._default_template):
                self._pdf_overrides[self._current_pdf] = template
            else:
                self._default_template = template
        else:
            self._default_template = template

        # 更新试识别结果中的字段名
        if self._current_preview_result and old_name in self._current_preview_result.fields:
            field_result = self._current_preview_result.fields.pop(old_name)
            field_result.field_name = new_name
            self._current_preview_result.fields[new_name] = field_result

        self.status_label.setText(f"字段名已更新: {old_name} -> {new_name}")

    def closeEvent(self, event):
        """窗口关闭时确保 worker 线程安全终止"""
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            self.worker.wait(3000)  # 等待最多3秒

        # 关闭进度对话框（如果存在）
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()

        event.accept()