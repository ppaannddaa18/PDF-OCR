"""
主窗口 - 性能优化版
- 延迟导入重型UI组件
- 异步初始化核心组件
"""
# 核心导入（必须同步加载）
from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QStackedWidget, QSplitter, QDialog
)
from PyQt6.QtCore import Qt, QSize, QTimer, QEvent
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
        from app.ui.widgets.result_panel import ResultPanel
        from app.ui.widgets.status_bar import StatusBar
        from app.workers.batch_worker import BatchWorker
        from app.workers.ocr_worker import ParseWorker
        from app.utils.command_history import AddRegionCommand, RemoveRegionCommand, UpdateRegionCommand, ClearAllCommand

        _UiComponents = type('UiComponents', (), {
            'PdfCanvas': PdfCanvas,
            'FileListPanel': FileListPanel,
            'FieldPanel': FieldPanel,
            'ResultTable': ResultTable,
            'HistoryPanel': HistoryPanel,
            'ImagePreprocessToolbar': ImagePreprocessToolbar,
            'LoadingOverlay': LoadingOverlay,
            'ResultPanel': ResultPanel,
            'StatusBar': StatusBar,
            'BatchWorker': BatchWorker,
            'ParseWorker': ParseWorker,
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
from app.ui.theme_manager import ThemeManager  # 主题管理器（Task 15：模块级，供各方法引用）
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import get_ocr_engine
from app.core.batch_processor import BatchProcessor
from app.core.template_manager import TemplateManager
from app.core.exporter import Exporter
from app.utils.lru_cache import LRUCache
from app.utils.command_history import CommandHistory
from app.utils.history_manager import HistoryManager
from app.models.region import Region


class MainWindow(FluentWindow):
    def __init__(self, config):
        # 先于 super().__init__() 初始化：FluentWindow 构造期间会以事件过滤器
        # 身份回调本类 eventFilter（qfluentwidgets 内部机制），属性必须已存在
        self._theme_mode = 'auto'
        super().__init__()
        self.config = config
        self.setWindowTitle(config["app"]["name"])
        self.resize(*config["app"]["window_size"])

        # 引擎类型检测
        engine_type = config.get("ocr", {}).get("engine", "gguf")
        self._gguf_device = config.get("ocr", {}).get("gguf", {}).get("device", "gpu")
        # GGUF 引擎支持热切换 GPU/CPU，不需要重启
        self._gguf_was_unloaded = False

        # 双模式状态
        self._current_mode = "auto" if self.config.get("ocr", {}).get("engine") == "gguf" else "manual"
        # 中面板（版面可视化）— VLM模式下显示
        self._layout_view = None  # QGraphicsView，延迟创建
        # 右面板 StackedWidget — 根据模式切换子面板
        self._result_stack = None  # QStackedWidget

        # 确保重型模块已加载
        _ensure_qta()

        # Task 15 启动接线：appearance.theme（默认 auto 跟随系统，兼容旧 app.theme）
        # + appearance.animations_enabled（默认 True），双轨应用 ThemeManager 与
        # qfluentwidgets 主题；在创建任何组件前执行，组件构造时即烘焙正确主题色
        from app.ui.theme_manager import ThemeManager
        from app.ui.animation_manager import AnimationManager
        theme_mode = (
            config.get("appearance", {}).get("theme")
            or config.get("app", {}).get("theme")
            or "auto"
        )
        if theme_mode not in ('light', 'dark', 'auto'):
            theme_mode = 'auto'
        self._apply_theme_mode(theme_mode)
        # F-3：仅当 config 显式声明 animations_enabled 时才覆盖系统 reduced-motion
        # 检测结果（模块级 _detect_system_animations_enabled）；appearance 节缺失或
        # 无该键时保留系统偏好（键存在性判断与 _on_settings_clicked 一致）
        appearance = config.get("appearance")
        if appearance is not None and "animations_enabled" in appearance:
            AnimationManager.set_enabled(bool(appearance["animations_enabled"]))
        # 跟随系统模式：监听系统主题变化。
        # 用 QApplication.paletteChanged 信号而非 installEventFilter：
        # 应用级事件过滤器挂在窗口上会在窗口中途销毁时悬垂，实测间歇性段错误
        # （access violation）；信号连接随接收者销毁自动断开，无生命周期风险。
        # 系统主题变化（Windows WM_SETTINGCHANGE → Qt 更新调色板）即触发本信号。
        from PyQt6.QtWidgets import QApplication
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.paletteChanged.connect(self._on_system_palette_changed)

        # 创建加载遮罩层（在创建其他组件之前）
        self._create_loading_overlay()

        # 核心组件
        self.pdf_loader = PdfLoader(dpi=config.get("pdf", {}).get("render_dpi", 200))
        self.ocr_engine = get_ocr_engine(self.config)
        self.processor = None  # 将在OCR引擎就绪后创建
        self._init_gen = 0  # 初始化世代计数器，防止竞态条件
        self._ready_gen = -1  # 当前就绪回调的世代号，-1=未初始化
        self._is_shutting_down = False  # 关闭中标志，防止重复触发
        self._shutdown_cleanup_thread = None  # 后台清理线程引用

        # 在后台线程中同步初始化（不阻塞UI）
        import threading
        import logging
        _logger = logging.getLogger("PDFOCR")
        self._init_gen += 1
        gen = self._init_gen
        ocr = self.ocr_engine  # 捕获引用，防止引擎切换后初始化错误对象
        def _init_ocr():
            if self._init_gen != gen:
                _logger.info(f"[OCR-Init] gen={gen} stale, skipping (current={self._init_gen})")
                return  # stale，引擎已被切换
            _logger.info(f"[OCR-Init] gen={gen} 开始初始化 {ocr.engine_name}...")
            try:
                ocr.initialize()
                if ocr.is_ready:
                    _logger.info(f"[OCR-Init] gen={gen} 初始化成功")
                else:
                    _logger.error(f"[OCR-Init] gen={gen} 初始化失败: {ocr.init_error}")
            except Exception as e:
                _logger.error(f"[OCR-Init] gen={gen} 初始化异常: {e}", exc_info=True)
            if self._init_gen == gen:
                self._ready_gen = gen
                QTimer.singleShot(0, self._on_ocr_ready)
        threading.Thread(target=_init_ocr, daemon=True, name="OCR-Init").start()
        self.template_mgr = TemplateManager()
        self.exporter = Exporter()

        self.results = []
        self.worker = None
        self._parse_worker = None  # 当前页VLM解析 worker（QThread）
        self.state_tooltip = None
        self._last_engine_status = ("", "unavailable")  # GpuStatusWidget.status_changed 最新值
        # 模板名称标签当前是否为默认态（apply_theme 重绘颜色时使用）
        self._template_is_default = False

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
        self._current_page_image = None  # 当前显示的PIL Image
        self._current_page_result = None  # VLM解析结果（PageResult）
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

        # Task 16: 焦点跟踪接线（状态栏快捷键提示区域跟随焦点切换）
        self._connect_focus_tracking()

        # 设置快捷键
        self._setup_shortcuts()

        # 检查是否有待恢复的任务
        QTimer.singleShot(500, self._check_pending_task)

        # 初始模式同步（引擎切换触发 UI 模式调整）
        QTimer.singleShot(100, lambda: self._switch_ui_mode(self._current_mode))

        # 财务字段处理器（引擎无关，复用实例）
        try:
            from app.core.finance_processor import FinanceProcessor
            self._finance_processor = FinanceProcessor(self.config)
        except ImportError:
            self._finance_processor = None

        # Task 15：注册自身主题刷新（子组件已在构造时注册，先于本行执行）
        ThemeManager.register_refresh_callback(self.apply_theme)

    # ── Task 15: 主题模式接线（ThemeManager + qfluentwidgets 双轨同步） ──

    def _apply_theme_mode(self, mode: str):
        """应用主题模式：'light' | 'dark' | 'auto'

        - qfluentwidgets：setTheme(Theme.DARK/LIGHT/AUTO) 同步，
          避免暗色系统下 qfluentwidgets 与 ThemeManager 明暗混用（Task 7 M-2）
        - ThemeManager：自研组件色板（'auto' 时解析系统主题后设置）
        顺序注意：先 setTheme（qfluentwidgets 重排会覆盖 qfluentwidgets 控件上
        的内嵌 QSS，如模板名标签/统计标签），后 set_theme（触发全局刷新回调，
        自研颜色最后烘焙、生效）。
        """
        self._theme_mode = mode
        fluent_theme = {
            'light': Theme.LIGHT,
            'dark': Theme.DARK,
            'auto': Theme.AUTO,
        }[mode]
        setTheme(fluent_theme)
        effective = ThemeManager.resolve_theme(mode)
        # set_theme 触发全部已注册组件的刷新回调（组件构造时已注册）
        ThemeManager.set_theme(effective)

    def eventFilter(self, watched, event):
        """事件过滤：窗口自过滤（qfluentwidgets BackgroundAnimationWidget 在
        FluentWindow 构造时 installEventFilter(self)），ApplicationPaletteChange
        会送达顶层窗口——与 paletteChanged 信号双路径监听系统主题变化。

        防御性设计：FluentWindow 构造期间（super().__init__ 内）本方法即会
        被回调，此时部分属性/控件尚未创建；事件对象可能处于失效状态，
        event.type() 访问需 try/except 保护，避免回调栈内抛异常导致
        qFatal 硬崩溃（PyQt6 默认行为）。
        """
        try:
            if event.type() == QEvent.Type.ApplicationPaletteChange:
                self._on_system_palette_changed()
        except RuntimeError:
            pass  # 事件对象已失效（C++ 对象销毁），安全跳过
        return super().eventFilter(watched, event)

    def _on_system_palette_changed(self):
        """系统调色板变化：'auto' 模式下重新解析系统主题并刷新 ThemeManager
        （qfluentwidgets AUTO 模式内部自监听；本回调仅驱动自研色板）。
        非 auto 模式直接忽略（手动主题不随系统变化）。
        """
        if self._theme_mode != 'auto':
            return
        effective = ThemeManager.resolve_theme('auto')
        if effective != ThemeManager.current_theme():
            ThemeManager.set_theme(effective)

    def apply_theme(self):
        """重建 MainWindow 自身内嵌 QSS（Task 15：ThemeManager.set_theme
        后经注册回调调用；覆盖模板名称标签与结果页统计标签的颜色）"""
        if hasattr(self, 'template_name_label'):
            if self._template_is_default:
                self.template_name_label.setStyleSheet(
                    f"font-weight: bold; color: {ThemeManager.get_color('success')};")
            else:
                self.template_name_label.setStyleSheet(
                    f"font-weight: bold; color: {ThemeManager.get_color('primary')};")
        if hasattr(self, 'stat_success'):
            self.stat_success.setStyleSheet(
                f"color: {ThemeManager.get_color('success')};")
            self.stat_fail.setStyleSheet(
                f"color: {ThemeManager.get_color('error')};")

    def _setup_shortcuts(self):
        """设置快捷键

        协调者裁决：每个 QShortcut 创建后调用 setObjectName('<快捷键字符串>')，
        对象名 = 快捷键字符串本身，供 Task 16 集成测试用
        findChild(QShortcut, 'Ctrl+Shift+L') 验证快捷键绑定。
        """
        from PyQt6.QtGui import QShortcut, QKeySequence

        # Ctrl+O: 上传PDF
        shortcut_upload = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_upload.setObjectName("Ctrl+O")
        shortcut_upload.activated.connect(self.on_upload)

        # Ctrl+S: 保存模板
        shortcut_save = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save.setObjectName("Ctrl+S")
        shortcut_save.activated.connect(self.on_save_template)

        # Ctrl+Enter: 批量识别
        shortcut_batch = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_batch.setObjectName("Ctrl+Return")
        shortcut_batch.activated.connect(self.on_batch_run)

        # Ctrl+T: 试识别
        shortcut_try = QShortcut(QKeySequence("Ctrl+T"), self)
        shortcut_try.setObjectName("Ctrl+T")
        shortcut_try.activated.connect(self.on_try_ocr)

        # Delete: 删除选中字段（当字段表格有焦点时）
        shortcut_delete = QShortcut(QKeySequence("Delete"), self.field_panel)
        shortcut_delete.setObjectName("Delete")
        shortcut_delete.activated.connect(self._delete_selected_field)

        # Ctrl+Z: 撤销
        shortcut_undo = QShortcut(QKeySequence("Ctrl+Z"), self)
        shortcut_undo.setObjectName("Ctrl+Z")
        shortcut_undo.activated.connect(self._undo)

        # Ctrl+Y: 重做
        shortcut_redo = QShortcut(QKeySequence("Ctrl+Y"), self)
        shortcut_redo.setObjectName("Ctrl+Y")
        shortcut_redo.activated.connect(self._redo)

        # Ctrl+Shift+L: 切换左侧面板
        shortcut_left = QShortcut(QKeySequence("Ctrl+Shift+L"), self)
        shortcut_left.setObjectName("Ctrl+Shift+L")
        shortcut_left.activated.connect(self.left_panel.toggle)

        # Ctrl+Shift+R: 切换右侧面板
        shortcut_right = QShortcut(QKeySequence("Ctrl+Shift+R"), self)
        shortcut_right.setObjectName("Ctrl+Shift+R")
        shortcut_right.activated.connect(self._toggle_right_panel)

        # Ctrl+Shift+N: 新建模板
        shortcut_new = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        shortcut_new.setObjectName("Ctrl+Shift+N")
        shortcut_new.activated.connect(self._on_new_template)

        # Space: 快速预览
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
        """Ctrl+Shift+N: 新建模板（清空当前字段配置，支持撤销）

        [I-1 修复] 与 on_clear_current_pdf_fields 一致：清空默认模板，并为当前
        PDF 写入空覆盖配置占位，防止切换文件再切回时旧区域/旧默认模板静默复活。
        """
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
        # 清空默认模板，并写入空覆盖配置占位（与 on_clear_current_pdf_fields 一致的持久化）
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
        import logging
        _logger = logging.getLogger("PDFOCR")
        # 防止过期回调（引擎已被切换）覆盖当前状态
        if hasattr(self, '_ready_gen') and self._ready_gen != self._init_gen:
            _logger.info(f"[_on_ocr_ready] stale callback (ready_gen={self._ready_gen}, init_gen={self._init_gen}), skipping")
            return
        _logger.info(f"[_on_ocr_ready] gen={self._ready_gen} is_ready={self.ocr_engine.is_ready} engine={self.ocr_engine.engine_name}")
        if self.ocr_engine.is_ready:
            # 初始化成功，隐藏遮罩层
            self.loading_overlay.hide_overlay()
            self.gpu_status.set_engine(self.ocr_engine)
            # 引擎就绪后才创建 BatchProcessor（避免引擎未就绪就被使用）
            self.processor = BatchProcessor(
                self.pdf_loader, self.ocr_engine, self.config,
                max_workers=self.config.get("batch", {}).get("max_workers", 4)
            )
        else:
            # 初始化失败，显示错误面板
            error_msg = self.ocr_engine.init_error or "未知错误"
            self.loading_overlay.show_error(error_msg)
            self.gpu_status.set_engine(self.ocr_engine)  # 更新GPU状态为加载失败

    def _on_ocr_retry(self):
        """OCR引擎重试初始化"""
        import threading
        if hasattr(self.ocr_engine, 'unload'):
            self.ocr_engine.unload()
        self._init_gen += 1
        gen = self._init_gen
        ocr = self.ocr_engine
        def _reinit():
            if self._init_gen != gen:
                return
            ocr.initialize()
            if self._init_gen == gen:
                self._ready_gen = gen
                QTimer.singleShot(0, self._on_ocr_ready)
        threading.Thread(target=_reinit, daemon=True, name="OCR-Retry").start()

    def _on_use_cpu_mode(self):
        """切换到CPU模式并重试"""
        try:
            self.config["ocr"]["engine"] = "rapidocr"
            if hasattr(self.ocr_engine, 'unload'):
                self.ocr_engine.unload()
            self.ocr_engine = get_ocr_engine(self.config)
            import threading
            self._init_gen += 1
            gen = self._init_gen
            ocr = self.ocr_engine
            def _reinit():
                if self._init_gen != gen:
                    return
                ocr.initialize()
                if self._init_gen == gen:
                    self._ready_gen = gen
                QTimer.singleShot(0, self._on_ocr_ready)
            threading.Thread(target=_reinit, daemon=True, name="OCR-CPU").start()
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
        """创建模板编辑页面

        Task 7 重构：单层水平布局替代嵌套 QSplitter
        （左 CollapsiblePanel | 中央工作区 | 右 SlidablePanel）
        """
        from PyQt6.QtWidgets import QPushButton
        from app.ui.widgets.collapsible_panel import CollapsiblePanel
        from app.ui.widgets.slidable_panel import SlidablePanel
        from app.ui.widgets.compact_toolbar import CompactToolbar
        from app.ui.widgets.layout_visualizer import LayoutVisualizer

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # ── 工具栏容器：CompactToolbar + VLM 解析按钮 ──
        toolbar_container = QWidget()
        toolbar_layout = QHBoxLayout(toolbar_container)
        toolbar_layout.setContentsMargins(0, 0, 0, 0)
        toolbar_layout.setSpacing(4)

        self.toolbar = CompactToolbar()
        self.toolbar.upload_clicked.connect(self.on_upload)
        self.toolbar.test_ocr_clicked.connect(self.on_try_ocr)
        self.toolbar.batch_ocr_clicked.connect(self.on_batch_run)
        self.toolbar.save_template_clicked.connect(self.on_save_template)
        self.toolbar.load_template_clicked.connect(self.on_load_template)
        self.toolbar.settings_clicked.connect(self._on_settings_clicked)
        self.toolbar.engine_changed.connect(self._on_toolbar_engine_changed)
        toolbar_layout.addWidget(self.toolbar, 1)

        # 解析按钮 — 仅 VLM 模式显示（CompactToolbar 之外的补充按钮）
        self._btn_parse = QPushButton("解析")
        self._btn_parse.setToolTip("解析当前页面 (VLM 模式)")
        self._btn_parse.setFixedHeight(28)
        self._btn_parse.clicked.connect(self._on_parse_current_page)
        self._btn_parse.hide()  # 默认隐藏，VLM模式显示
        toolbar_layout.addWidget(self._btn_parse)

        # 引擎/GPU 状态别名（兼容既有引用：_on_engine_switched / _on_ocr_ready / closeEvent）
        self.engine_combo = self.toolbar.engine_combo
        self.gpu_status = self.toolbar.engine_status

        # 根据当前配置同步引擎下拉框（防止初始化时触发切换）
        current_engine = self.config.get("ocr", {}).get("engine", "gguf")
        current_device = self.config.get("ocr", {}).get("gguf", {}).get("device", "gpu")
        if current_engine == "gguf" and current_device == "gpu":
            current_idx = 0
        elif current_engine == "gguf" and current_device == "cpu":
            current_idx = 1
        else:
            current_idx = 2
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(current_idx)
        self.engine_combo.blockSignals(False)

        # 定位 CompactToolbar 内部的试识别/批量识别按钮（模式切换时显示/隐藏）
        for btn in self.toolbar.findChildren(QPushButton):
            tip = btn.toolTip()
            if tip == '试识别 (Ctrl+T)' and not hasattr(self, '_btn_try'):
                self._btn_try = btn
            elif tip == '批量识别 (Ctrl+Enter)' and not hasattr(self, '_btn_batch'):
                self._btn_batch = btn

        # 引擎状态桥接（GpuStatusWidget.status_changed 信号：
        # _refresh 发小写 engine_name，set_engine_status 发显示名；
        # Task 13 状态栏重构时将消费该信号）
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
        content_layout.addWidget(self.left_panel)

        # 中央工作区
        self.workspace = QWidget()
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        # 图像预处理工具栏（Task 10 将重构）
        self.preprocess_toolbar = ui.ImagePreprocessToolbar()
        self.preprocess_toolbar.setEnabled(False)
        self.preprocess_toolbar.image_changed.connect(self._on_preprocess_changed)
        self.preprocess_toolbar.apply_to_all.connect(self._on_preprocess_apply_to_all)
        self.preprocess_toolbar.reset_requested.connect(self._on_preprocess_reset)
        self.preprocess_toolbar.apply_auto_contrast.connect(self._on_preprocess_auto_contrast)  # [修复]
        self.preprocess_toolbar.apply_sharpen.connect(self._on_preprocess_sharpen)  # [修复]
        workspace_layout.addWidget(self.preprocess_toolbar)

        # PDF 画布 + 版面可视化（VLM 模式 block 覆盖层；普通水平布局替代子 splitter）
        canvas_area = QWidget()
        canvas_area_layout = QHBoxLayout(canvas_area)
        canvas_area_layout.setContentsMargins(0, 0, 0, 0)
        canvas_area_layout.setSpacing(0)

        self.pdf_canvas = ui.PdfCanvas()
        canvas_area_layout.addWidget(self.pdf_canvas, 1)

        self._layout_view = LayoutVisualizer()
        self._layout_view.setMinimumWidth(200)
        self._layout_view.hide()  # 默认隐藏，VLM模式显示
        canvas_area_layout.addWidget(self._layout_view)

        # 滚动同步：pdf_canvas <-> layout_visualizer
        self.pdf_canvas.verticalScrollBar().valueChanged.connect(
            self._layout_view.scroll_to
        )
        self._layout_view.scrolled.connect(
            self.pdf_canvas.verticalScrollBar().setValue
        )

        workspace_layout.addWidget(canvas_area, 1)

        # 底部状态栏（Task 13 将重构为 StatusBar 组件）
        status_bar = self._create_status_bar()
        workspace_layout.addWidget(status_bar)

        content_layout.addWidget(self.workspace, 1)

        # 右侧面板（可滑动 320，内容 = 模板信息 + 字段/结果切换栈）
        self.right_panel = SlidablePanel(panel_width=320)
        self._right_title = self.right_panel.title_label
        self._right_title.setText("字段配置")

        right_content = QWidget()
        right_content_layout = QVBoxLayout(right_content)
        right_content_layout.setContentsMargins(0, 0, 0, 0)
        right_content_layout.setSpacing(4)

        # 模板信息区域（仅手动模式显示）
        self._template_info_widget = QWidget()
        template_info_layout = QVBoxLayout(self._template_info_widget)
        template_info_layout.setContentsMargins(8, 8, 8, 8)
        template_info_layout.setSpacing(4)

        # 模板名称标签（颜色经 ThemeManager 获取，明暗主题一致；Task 15 全局约束）
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

        # 使用 QStackedWidget 切换手动/自动面板
        self._right_content_stack = QStackedWidget()

        # 页0：字段面板（手动模式）
        self.field_panel = ui.FieldPanel()
        self.field_panel.setMinimumWidth(320)
        self._right_content_stack.addWidget(self.field_panel)

        # 页1：结果面板（自动模式）
        self._result_panel = ui.ResultPanel()
        self._right_content_stack.addWidget(self._result_panel)

        right_content_layout.addWidget(self._right_content_stack, 1)
        self.right_panel.set_content(right_content)
        content_layout.addWidget(self.right_panel)

        layout.addWidget(content, 1)

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
        """[修复] 筛选条件变更 - 支持全部字段筛选，重置低置信度模式"""
        keyword = self.filter_edit.text()
        field_idx = self.filter_field_combo.currentIndex()

        # 重置低置信度模式
        if self._low_confidence_mode:
            self._low_confidence_mode = False
            self.btn_low_conf.setText("显示低置信度")

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

        # 成功数 / 失败数（ThemeManager 色，主题切换时 apply_theme 重建）
        self.stat_success = BodyLabel("成功: 0")
        self.stat_success.setStyleSheet(
            f"color: {ThemeManager.get_color('success')};")
        layout.addWidget(self.stat_success)

        self.stat_fail = BodyLabel("失败: 0")
        self.stat_fail.setStyleSheet(
            f"color: {ThemeManager.get_color('error')};")
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
        """创建底部状态栏（Task 13: 独立 StatusBar 组件）

        StatusBar 提供 status_label 兼容属性（内部状态文本 QLabel），
        既有 25 处 self.status_label.setText(...) 调用无需逐个修改。
        """
        self.status_bar = _get_ui_components().StatusBar()
        self.status_label = self.status_bar.status_label
        # 回放已记录的引擎状态（引擎初始化可能早于状态栏创建完成）
        engine, status = self._last_engine_status
        self.status_bar.set_engine_status(engine, status)
        return self.status_bar

    def _on_toolbar_engine_changed(self, label: str):
        """CompactToolbar 引擎选择变更（信号携带显示名标签）→ 委托既有引擎切换逻辑"""
        index = {"GGUF (GPU)": 0, "GGUF (CPU)": 1, "RapidOCR (CPU)": 2}.get(label, -1)
        if index >= 0:
            self._on_engine_switched(index)

    def _on_gpu_status_changed(self, engine: str, status: str):
        """引擎状态变化记录 + 桥接到状态栏（GpuStatusWidget.status_changed 信号）

        注意：GpuStatusWidget._refresh 发射小写 engine_name（如 'gguf'），
        而 set_engine_status 发射显示名（如 'GGUF'），消费方需兼容两种形式。
        状态栏创建前信号可能先到（OCR 初始化线程早于 _create_template_page
        完成），故用 getattr 判空；_create_status_bar 会回放 _last_engine_status。
        """
        self._last_engine_status = (engine, status)
        status_bar = getattr(self, 'status_bar', None)
        if status_bar is not None:
            status_bar.set_engine_status(engine, status)

    def _connect_signals(self):
        # F-1: 文件面板空状态「上传 PDF」操作按钮 → 打开文件对话框（与工具栏同槽）
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

    # ── Task 16: 焦点跟踪（StatusBar.set_focus_area 四档 API 接线，Task 13 遗留） ──

    def _connect_focus_tracking(self):
        """接线焦点跟踪：文件列表/画布/字段面板获得焦点时更新状态栏快捷键提示

        方案选择：监听 QApplication.focusChanged 应用级信号而非 installEventFilter。
        focusChanged 携带实际获得焦点的控件（QListWidget / QTableWidget /
        QGraphicsView viewport 等真正持焦的子控件），按 isAncestorOf 归属判断
        映射到对应区域——不需要遍历/安装事件过滤器到每个子孙控件，且焦点移到
        面板之外（工具栏/下拉框等）或窗口失焦时自动回到 'global'。
        信号连接随接收者销毁自动断开（与 paletteChanged 同生命周期策略）。
        """
        from PyQt6.QtWidgets import QApplication
        app_inst = QApplication.instance()
        if app_inst is not None:
            app_inst.focusChanged.connect(self._on_focus_changed)

    def _on_focus_changed(self, _old: QWidget, new: QWidget):
        """应用焦点变化 → 状态栏快捷键提示区域（无焦点/面板外 → global）

        isAncestorOf 对自身返回 True（Qt 约定），故直接持焦的容器控件
        （如 canvas 的 viewport）与子孙控件均命中对应区域。
        """
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
            # 先从画布数据删除（否则 _on_region_deleted 信号会创建重复命令）
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
            self.file_panel.add_files(files)  # add_files 内部已触发 file_selected 信号
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

        # 清除缓存的预览结果（区域已变化，旧预览已失效）
        self._current_preview_result = None
        if self._current_pdf and self._current_pdf in self._pdf_preview_results:
            del self._pdf_preview_results[self._current_pdf]

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

        # 检查是否有自定义的per-file配置将被丢弃
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
        self._current_page_image = self._current_preprocessor.get_current_image()
        self.preprocess_toolbar.setEnabled(True)

        # 同步设置版面可视化背景图
        if self._layout_view is not None:
            self._layout_view.set_page_image_from_pil(self._current_page_image)

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
            self._current_page_image = self._current_preprocessor.get_current_image()

    def _on_preprocess_apply_to_all(self):
        """将当前预处理应用到所有文件"""
        if self._current_preprocessor and self._current_pdf:
            params = self._current_preprocessor.get_params()
            # 应用到所有已加载的PDF文件（跳过当前文件，因其已应用）
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
        """[修复] 应用自动对比度"""
        if self._current_preprocessor:
            self._current_preprocessor.auto_contrast()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

    def _on_preprocess_sharpen(self):
        """[修复] 应用锐化"""
        if self._current_preprocessor:
            self._current_preprocessor.sharpen()
            self.pdf_canvas.load_image(self._current_preprocessor.get_current_image())
            self._current_page_image = self._current_preprocessor.get_current_image()

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
                    # 保存到持久化存储
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

        # 显示进度条
        self.progress_widget.setVisible(True)

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
        # 批量识别完成后清理 worker 引用
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

        # 从 worker 获取已完成的结果（如果 results 为空）
        if not self.results and self.worker and hasattr(self.worker, '_completed_results'):
            self.results = self.worker._completed_results

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

    def _clear_worker(self):
        """清理 worker 引用，避免内存泄漏"""
        self.worker = None

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
            collected = self.result_table.collect_results()
            include_conf = self.config["export"]["include_confidence"]
            try:
                self.exporter.to_excel(collected, path, include_conf)
                self.results = collected
                InfoBar.success(
                    title="成功",
                    content=f"已导出到 {path}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=3000,
                    parent=self
                )
            except Exception as e:
                InfoBar.error(
                    title="导出失败",
                    content=f"导出Excel时出错: {e}",
                    orient=Qt.Orientation.Horizontal,
                    isClosable=True,
                    position=InfoBarPosition.TOP,
                    duration=5000,
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

    def on_field_name_changed(self, region_id: str, old_name: str, new_name: str):
        """字段名变更处理 - 使用 region_id 精确定位"""
        if self._current_pdf is None:
            return

        if region_id is None or region_id not in self.field_panel.regions:
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

    def _on_engine_switched(self, index: int):
        """引擎切换处理: RapidOCR 热切换, GGUF GPU↔CPU 需重启"""
        engine_names = ["gguf", "gguf", "rapidocr"]
        engine_devices = ["gpu", "cpu", None]
        engine_labels = ["GGUF (GPU)", "GGUF (CPU)", "RapidOCR (CPU)"]
        new_engine_type = engine_names[index]
        new_device = engine_devices[index]
        current_engine = self.config.get("ocr", {}).get("engine", "gguf")
        current_device = self.config.get("ocr", {}).get("gguf", {}).get("device", "gpu")

        # 计算当前索引
        if current_engine == "gguf" and current_device == "gpu":
            current_idx = 0
        elif current_engine == "gguf" and current_device == "cpu":
            current_idx = 1
        else:
            current_idx = 2

        if new_engine_type == current_engine and new_device == current_device:
            return

        # 防止批量识别进行中切换引擎
        if self.worker and self.worker.isRunning():
            InfoBar.warning(title="提示", content="批量识别进行中，请等待完成或取消后再切换引擎",
                            orient=Qt.Orientation.Horizontal, isClosable=True,
                            position=InfoBarPosition.TOP, duration=3000, parent=self)
            self.engine_combo.blockSignals(True)
            self.engine_combo.setCurrentIndex(current_idx)
            self.engine_combo.blockSignals(False)
            return

        def _revert_combo():
            self.engine_combo.blockSignals(True)
            self.engine_combo.setCurrentIndex(current_idx)
            self.engine_combo.blockSignals(False)

        # GGUF GPU↔CPU 切换需要重启（llama-server 参数不同）
        needs_restart = (
            new_engine_type == "gguf" and
            new_device != current_device and
            current_engine == "gguf"
        )
        if needs_restart:
            from qfluentwidgets import MessageBox
            extra_info = ""
            if new_device == "cpu":
                extra_info = "\nCPU模式: 质量与GPU一致，速度较慢(~10s/页)，0显存占用"
            else:
                extra_info = "\nGPU模式: 速度快(~2s/页)，需约6GB显存"

            msg = MessageBox(
                "重启切换引擎",
                f"切换到 {engine_labels[index]} 需要重启程序。"
                f"{extra_info}\n\n"
                "原因: GGUF 的 GPU/CPU 模式需要在启动时确定。\n\n"
                "是否立即重启？",
                self
            )
            msg.yesButton.setText("立即重启")
            msg.cancelButton.setText("取消")
            if not msg.exec():
                _revert_combo()
                return

            # 保存配置并重启
            self.config["ocr"]["engine"] = new_engine_type
            self.config["ocr"]["gguf"]["device"] = new_device
            self._restart_with_engine(new_engine_type, new_device)
            return

        # ── 以下为热切换路径 (RapidOCR ↔ GGUF 引擎) ──

        # RapidOCR → GGUF 引擎时确认提示
        if new_engine_type == "gguf":
            from qfluentwidgets import MessageBox
            extra = ""
            if new_device == "cpu":
                extra = "\n\nCPU模式: 质量与GPU一致，速度较慢(~10s/页)，但0显存占用"
            else:
                extra = "\n\nGPU模式: 速度快(~2s/页)，需约6GB显存"
            msg = MessageBox(
                "切换OCR引擎",
                f"切换到 {engine_labels[index]}？{extra}\n\n"
                "注意：切换引擎后需要重新识别，当前未保存的识别结果将丢失。",
                self
            )
            msg.yesButton.setText("确认切换")
            msg.cancelButton.setText("取消")
            if not msg.exec():
                _revert_combo()
                return

        # 更新配置
        self.config["ocr"]["engine"] = new_engine_type
        if new_device:
            self.config["ocr"]["gguf"]["device"] = new_device

        # 重新创建引擎（先卸载旧引擎+重置单例，确保新配置生效）
        if hasattr(self.ocr_engine, 'unload'):
            self.ocr_engine.unload()
        if hasattr(type(self.ocr_engine), 'reset_instance'):
            type(self.ocr_engine).reset_instance()
        # GGUF 被卸载后可以在同一进程中重新初始化
        if current_engine == "gguf":
            self._gguf_was_unloaded = True
        self.ocr_engine = get_ocr_engine(self.config)

        # 立即更新GPU状态组件（避免旧引擎僵尸引用导致一直"加载中"）
        self.gpu_status.set_engine(self.ocr_engine)

        # 异步初始化新引擎（带世代计数器防竞态）
        import threading
        import logging
        _logger = logging.getLogger("PDFOCR")
        self._init_gen += 1
        gen = self._init_gen
        ocr = self.ocr_engine
        def _reinit():
            if self._init_gen != gen:
                _logger.info(f"[OCR-Reinit] gen={gen} stale, skipping (current={self._init_gen})")
                return  # stale，引擎已被再次切换
            _logger.info(f"[OCR-Reinit] gen={gen} 开始初始化 {ocr.engine_name}...")
            try:
                ocr.initialize()
                if ocr.is_ready:
                    _logger.info(f"[OCR-Reinit] gen={gen} 初始化成功")
                else:
                    _logger.error(f"[OCR-Reinit] gen={gen} 初始化失败: {ocr.init_error}")
            except Exception as e:
                _logger.error(f"[OCR-Reinit] gen={gen} 初始化异常: {e}", exc_info=True)
            if self._init_gen == gen:
                self._ready_gen = gen
                QTimer.singleShot(0, self._on_ocr_ready)
        threading.Thread(target=_reinit, daemon=True, name="OCR-Reinit").start()

        # 清空旧结果（BatchProcessor 和 GpuStatus 由 _on_ocr_ready 统一更新）
        self._current_preview_result = None
        self._pdf_preview_results.clear()
        self.results = []
        self.result_table.load_results([])
        # 更新统计信息
        self.stat_total.setText("共 0 个文件")
        self.stat_success.setText("成功: 0")
        self.stat_fail.setText("失败: 0")

        engine_labels_short = ["GGUF (GPU)", "GGUF (CPU)", "RapidOCR (CPU)"]
        InfoBar.success(
            title="引擎已切换",
            content=f"当前引擎: {engine_labels_short[index]}",
            duration=3000,
            parent=self
        )

        # 判断新模式并切换UI
        new_mode = "auto" if new_engine_type == "gguf" else "manual"
        if new_mode != self._current_mode:
            self._current_mode = new_mode
            self._switch_ui_mode(new_mode)

        # 热切换成功后写入配置文件
        try:
            import yaml
            config_path = self.config.get("_config_path", "config.yaml")
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            _logger.warning(f"写入配置文件失败: {e}")

    def _on_settings_clicked(self):
        """打开 OCR 设置对话框"""
        from app.ui.widgets.ocr_settings_dialog import OcrSettingsDialog

        dialog = OcrSettingsDialog(self.config, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # 获取设置补丁
            patch = dialog.get_config_patch()

            # 合并到当前配置
            self._merge_config_patch(self.config, patch)

            # Task 15：外观设置立即生效（对话框内已即时应用，此处幂等兜底）
            from app.ui.animation_manager import AnimationManager
            appearance = self.config.get("appearance", {})
            if "theme" in appearance:
                self._apply_theme_mode(appearance["theme"])
            if "animations_enabled" in appearance:
                AnimationManager.set_enabled(bool(appearance["animations_enabled"]))

            # 保存配置
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
                _logger.error(f"保存设置失败: {e}")
                InfoBar.error(
                    title="保存失败",
                    content=f"无法保存设置: {e}",
                    duration=5000,
                    parent=self
                )

    def _merge_config_patch(self, config: dict, patch: dict):
        """递归合并配置补丁"""
        for key, value in patch.items():
            if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                self._merge_config_patch(config[key], value)
            else:
                config[key] = value

    def _restart_with_engine(self, engine_type: str, device: str = None):
        """写入配置并重启程序切换到指定引擎"""
        import subprocess
        import yaml
        from pathlib import Path

        # 写入 config.yaml（使用 app/config.yaml，与 load_config 一致）
        config_path = Path(__file__).parent.parent / "config.yaml"
        self.config["ocr"]["engine"] = engine_type
        if device and "gguf" in self.config.get("ocr", {}):
            self.config["ocr"]["gguf"]["device"] = device
        try:
            with open(config_path, "w", encoding="utf-8") as f:
                yaml.safe_dump(self.config, f, allow_unicode=True, default_flow_style=False)
        except Exception as e:
            import logging
            logging.getLogger("PDFOCR").error(f"保存配置失败: {e}")

        # 启动新进程并退出当前
        import sys
        subprocess.Popen([sys.executable, *sys.argv], close_fds=True)
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()

    def _switch_ui_mode(self, mode: str):
        """切换 UI 模式：auto(VLM) ↔ manual(RapidOCR)"""
        if mode == "auto":
            # 切换到结果面板
            if hasattr(self, '_right_content_stack') and self._right_content_stack is not None:
                self._right_content_stack.setCurrentIndex(1)
            # 更新标题
            if hasattr(self, '_right_title'):
                self._right_title.setText("解析结果")
            # 隐藏模板信息
            if hasattr(self, '_template_info_widget'):
                self._template_info_widget.hide()
            # 显示版面可视化面板
            if self._layout_view is not None:
                self._layout_view.show()
            # 禁用 PDF canvas 的框选功能
            if hasattr(self, 'pdf_canvas') and self.pdf_canvas:
                if hasattr(self.pdf_canvas, 'set_drawing_enabled'):
                    self.pdf_canvas.set_drawing_enabled(False)
            # 工具栏切换：隐藏手动OCR按钮，显示解析按钮
            if hasattr(self, '_btn_try'):
                self._btn_try.hide()
            if hasattr(self, '_btn_batch'):
                self._btn_batch.hide()
            if hasattr(self, '_btn_parse'):
                self._btn_parse.show()
        else:
            # 切换到字段面板
            if hasattr(self, '_right_content_stack') and self._right_content_stack is not None:
                self._right_content_stack.setCurrentIndex(0)
            # 更新标题
            if hasattr(self, '_right_title'):
                self._right_title.setText("字段配置")
            # 显示模板信息
            if hasattr(self, '_template_info_widget'):
                self._template_info_widget.show()
            # 隐藏版面可视化
            if self._layout_view is not None:
                self._layout_view.hide()
            # 启用框选
            if hasattr(self, 'pdf_canvas') and self.pdf_canvas:
                if hasattr(self.pdf_canvas, 'set_drawing_enabled'):
                    self.pdf_canvas.set_drawing_enabled(True)
            # 工具栏切换：显示手动OCR按钮，隐藏解析按钮
            if hasattr(self, '_btn_try'):
                self._btn_try.show()
            if hasattr(self, '_btn_batch'):
                self._btn_batch.show()
            if hasattr(self, '_btn_parse'):
                self._btn_parse.hide()

    def _on_parse_current_page(self):
        """点击'解析'按钮 — 触发当前页VLM解析"""
        # 防止重复点击启动多个 Worker
        if self._parse_worker and self._parse_worker.isRunning():
            InfoBar.warning(
                title="提示",
                content="解析正在进行中，请等待完成",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )
            return

        engine = self.ocr_engine
        if not hasattr(engine, 'recognize_page_auto'):
            InfoBar.error(
                title="错误",
                content="当前引擎不支持自动解析",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self
            )
            return

        # 获取当前页图片
        if self._current_page_image is None:
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

        self._btn_parse.setEnabled(False)
        self._btn_parse.setText("解析中...")
        self.status_label.setText("正在解析当前页面（最长等待 120 秒）...")

        # 在 QThread 中执行（避免阻塞UI）；图像在主线程先 copy，防止与主线程修改产生竞态
        ui = _get_ui_components()
        self._parse_worker = ui.ParseWorker(engine, self._current_page_image.copy())
        self._parse_worker.finished.connect(self._on_parse_worker_finished)
        self._parse_worker.error.connect(self._on_parse_worker_error)
        self._parse_worker.finished.connect(self._on_parse_worker_cleanup)
        self._parse_worker.error.connect(self._on_parse_worker_cleanup)
        self._parse_worker.start()

    def _on_parse_worker_finished(self, result):
        """解析成功（主线程槽）"""
        self._current_page_result = result
        self._on_page_parsed(result)

    def _on_parse_worker_error(self, error_msg):
        """解析失败（主线程槽）"""
        InfoBar.error(
            title="解析失败",
            content=str(error_msg),
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.TOP,
            duration=5000,
            parent=self
        )
        self.status_label.setText("解析失败")

    def _on_parse_worker_cleanup(self):
        """解析 worker 结束后的统一清理：恢复按钮、释放引用（参照 _clear_worker）"""
        self._btn_parse.setEnabled(True)
        self._btn_parse.setText("解析")
        self._parse_worker = None

    def _on_page_parsed(self, result):
        """解析完成回调"""
        # 更新版面可视化
        if self._layout_view is not None:
            if hasattr(self._layout_view, 'update_blocks'):
                self._layout_view.update_blocks(result.blocks)

        # 财务字段提取
        finance_result = None
        if result.blocks:
            try:
                if self._finance_processor is not None:
                    finance_result = self._finance_processor.process(result.blocks)
            except Exception:
                pass

        # 更新结果面板
        if hasattr(self, '_result_panel') and self._result_panel is not None:
            self._result_panel.load_result(result, finance_result)

        self.status_label.setText(
            f"解析完成 — 识别 {len(result.blocks)} 个元素, "
            f"耗时 {result.inference_time_ms:.0f}ms"
        )
        InfoBar.success(
            title="解析完成",
            content=f"识别 {len(result.blocks)} 个元素, 耗时 {result.inference_time_ms:.0f}ms",
            orient=Qt.Orientation.Horizontal,
            isClosable=True,
            position=InfoBarPosition.BOTTOM_RIGHT,
            duration=3000,
            parent=self
        )

    def closeEvent(self, event):
        """窗口关闭时异步执行清理，避免UI冻结"""
        # 防止重复触发
        if self._is_shutting_down:
            event.accept()
            return

        self._is_shutting_down = True

        # 0. 断开系统主题变化监听（paletteChanged；信号随对象销毁也会自动断开）
        from PyQt6.QtWidgets import QApplication as _QApp
        _app_inst = _QApp.instance()
        if _app_inst is not None:
            try:
                _app_inst.paletteChanged.disconnect(self._on_system_palette_changed)
            except (TypeError, RuntimeError):
                pass
            # Task 16: 焦点跟踪连接随窗口销毁自动断开，此处显式断开与主题一致
            try:
                _app_inst.focusChanged.disconnect(self._on_focus_changed)
            except (TypeError, RuntimeError):
                pass

        # 1. 立即接受关闭事件，隐藏窗口
        event.accept()
        self.hide()

        # 2. 显示关闭中的遮罩层
        if hasattr(self, 'loading_overlay') and self.loading_overlay:
            try:
                self.loading_overlay.status_label.setText("正在关闭应用，请稍候...")
                self.loading_overlay.desc_label.setText("正在停止 OCR 引擎...")
                self.loading_overlay.dots_label.setVisible(True)
                self.loading_overlay.progress_ring.setVisible(True)
                self.loading_overlay.error_widget.setVisible(False)
                self.loading_overlay.setVisible(True)
                self.loading_overlay.raise_()
                self.loading_overlay._animation_timer.start(300)
            except Exception:
                pass

        # 3. 取消运行中的worker（最多等3秒）
        if self.worker and self.worker.isRunning():
            self.worker.cancel()
            if self.results:
                try:
                    all_files = self.file_panel.all_files()
                    completed = len(self.results)
                    remaining_files = all_files[completed:] if completed < len(all_files) else []
                    if remaining_files:
                        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
                        import json
                        from datetime import datetime
                        CancelResultDialog.PENDING_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)
                        task_data = {
                            "timestamp": datetime.now().isoformat(),
                            "completed": completed,
                            "total": len(all_files),
                            "success": sum(1 for r in self.results if r.success),
                            "failed": completed - sum(1 for r in self.results if r.success),
                            "pending_files": remaining_files,
                            "results": [
                                {
                                    "source_file": r.source_file,
                                    "fields": {k: {"text": v.text, "confidence": v.confidence}
                                               for k, v in r.fields.items()}
                                }
                                for r in self.results
                            ]
                        }
                        with open(CancelResultDialog.PENDING_TASK_FILE, 'w', encoding='utf-8') as f:
                            json.dump(task_data, f, indent=2, ensure_ascii=False)
                except Exception:
                    pass
            self.worker.wait(3000)

        # 3.5 停止解析中的 worker（与批量 worker 保持一致：cancel + 最多等3秒）
        if self._parse_worker and self._parse_worker.isRunning():
            self._parse_worker.cancel()
            self._parse_worker.wait(3000)

        # 4. 关闭进度对话框
        if hasattr(self, 'progress_dialog') and self.progress_dialog:
            self.progress_dialog.close()

        # 5. 轻量级清理
        self.gpu_status.cleanup()
        self.pdf_loader.shutdown()
        self._save_current_pdf_config()

        # 6. 异步卸载OCR引擎（重量级操作，非daemon线程确保完成）
        def _on_cleanup_done():
            """清理完成后从主线程退出应用"""
            from PyQt6.QtWidgets import QApplication
            QApplication.quit()

        def _do_cleanup():
            """在后台线程中执行重量级清理"""
            import logging
            _logger = logging.getLogger("PDFOCR")
            try:
                if hasattr(self, 'ocr_engine') and self.ocr_engine:
                    _logger.info("[Shutdown] 开始卸载 OCR 引擎...")
                    try:
                        if hasattr(self.ocr_engine, 'terminate_async'):
                            import threading
                            done_event = threading.Event()
                            def _callback():
                                done_event.set()
                            self.ocr_engine.terminate_async(_callback)
                            done_event.wait(timeout=8)
                            if not done_event.is_set():
                                _logger.warning("[Shutdown] OCR引擎终止超时，强制退出")
                        else:
                            self.ocr_engine.unload()
                    except Exception as e:
                        _logger.warning(f"[Shutdown] OCR引擎卸载异常: {e}")
                _logger.info("[Shutdown] 清理完成")
            except Exception as e:
                _logger.error(f"[Shutdown] 清理过程异常: {e}")
            finally:
                # 确保在主线程中调用quit
                QTimer.singleShot(0, _on_cleanup_done)

        import threading
        self._shutdown_cleanup_thread = threading.Thread(
            target=_do_cleanup,
            daemon=False,  # 非daemon线程确保清理完成
            name="Shutdown-Cleanup"
        )
        self._shutdown_cleanup_thread.start()