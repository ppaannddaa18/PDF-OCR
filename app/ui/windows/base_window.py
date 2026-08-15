"""
AppBaseWindowMixin — 双窗口共享底座（Task P3a）

从旧 app/ui/main_window.py 机械提取共享逻辑（只搬不改逻辑），供
RapidMainWindow（本任务）与 GgufMainWindow（P4）复用。旧 main_window.py
已在 P7 统一删除，本文件为双窗口唯一共享底座。

──────────────────────── MRO 契约（硬性） ────────────────────────
类链：RapidMainWindow → AppBaseWindowMixin → MSFluentWindow
      → FluentWindowBase → ... → QWidget

构造协议（__init__ 内顺序固定）：
  1. self._init_app_base(config) —— 必须在 super().__init__() 之前调用。
     纯数据：config / engine_type / design 名 / 世代计数器 / shutting_down
     标志。FluentWindow/MSFluentWindow 构造期间会以事件过滤器身份回调本类
     （qfluentwidgets 内部机制），这些属性必须已存在。
  2. super().__init__() —— MSFluentWindow 构造（navigationInterface 为
     NavigationBar，stackedWidget 为 StackedWidget）。
  3. self._post_init_base() —— 必须在 super().__init__() 之后调用。
     UI 部件：LoadingOverlay / 页面构建 / 导航注册 / 引擎异步初始化。

属性可用性：
  pre-init（_init_app_base 内，super 之前）可用：
      config / engine_type / design / _init_gen / _ready_gen /
      _is_shutting_down / _shutdown_cleanup_thread
  post-init（_post_init_base 内，super 之后）可用：
      navigationInterface / stackedWidget / 页面对象 / loading_overlay /
      pdf_loader / ocr_engine / results 等全部 UI 与组件

引擎路径：本底座不假定引擎类型；engine_type 由子类在 _init_app_base
之前固化（RapidMainWindow 固定 'rapidocr'，去掉 gguf 分支逻辑）。
"""
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
)
from qfluentwidgets import (
    TransparentPushButton, StrongBodyLabel, BodyLabel,
    InfoBar, InfoBarPosition, PushButton,
    setTheme, Theme, setThemeColor,
)

# 核心组件导入（轻量级）
from app.ui.theme_manager import ThemeManager  # 主题管理器（设计 token 管道，P2）
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import get_ocr_engine
from app.core.batch_processor import BatchProcessor
from app.core.exporter import Exporter
from app.utils.history_manager import HistoryManager


# qtawesome 延迟加载（与旧 main_window.py 一致）
qta = None


def _icon(name: str, color: str = '#1E7B5C'):
    """获取图标（延迟加载 qtawesome）"""
    global qta
    if qta is None:
        import qtawesome
        qta = qtawesome
    return qta.icon(name, color=color)


class AppBaseWindowMixin:
    """双窗口共享底座：引擎生命周期 / 结果页 / 历史页 / 关闭清理 / 配置合并"""

    # 子类覆盖：窗口标题（None → config["app"]["name"]）与窗口图标
    WINDOW_TITLE = None
    WINDOW_ICON = None
    # 子类覆盖：design 名与强调色（P4 GgufMainWindow 覆盖为 'gguf'/#C9A227）
    DESIGN = 'rapid'
    ACCENT_COLOR = '#1E7B5C'
    # 子类覆盖：qfluentwidgets 主题（Rapid 固定浅色 / Gguf 固定深色）
    FLUENT_THEME = Theme.LIGHT

    # ── 构造协议（MRO 契约见文件顶部注释） ──────────────────────

    def _init_app_base(self, config: dict):
        """pre-super 纯数据初始化：必须在 super().__init__() 之前调用

        此处只做数据赋值，不得创建任何 UI 部件（MSFluentWindow 尚未构造）。
        可用属性：config / engine_type / design / 世代计数器 / shutting_down。
        """
        self.config = config
        self.engine_type = config.get("ocr", {}).get("engine", "rapidocr")
        self.design = self.DESIGN
        self._init_gen = 0  # 初始化世代计数器，防止竞态条件
        self._ready_gen = -1  # 当前就绪回调的世代号，-1=未初始化
        self._is_shutting_down = False  # 关闭中标志，防止重复触发
        self._shutdown_cleanup_thread = None  # 后台清理线程引用

    def _post_init_base(self):
        """post-super UI 初始化：必须在 super().__init__() 之后调用

        此时 navigationInterface / stackedWidget 已存在，可创建页面与导航。
        """
        # 窗口基础（标题/尺寸/图标）
        if self.WINDOW_TITLE:
            self.setWindowTitle(self.WINDOW_TITLE)
        else:
            self.setWindowTitle(self.config["app"]["name"])
        self.resize(*self.config["app"]["window_size"])
        if self.WINDOW_ICON:
            self.setWindowIcon(_icon(self.WINDOW_ICON, self.ACCENT_COLOR))

        # 创建加载遮罩层（在创建其他组件之前）
        self._create_loading_overlay()

        # 核心组件
        self.pdf_loader = PdfLoader(dpi=self.config.get("pdf", {}).get("render_dpi", 200))
        self.ocr_engine = get_ocr_engine(self.config)
        self.processor = None  # 将在OCR引擎就绪后创建
        self.exporter = Exporter()
        self.history_manager = HistoryManager()

        self.results = []
        self.worker = None

        # 创建子页面（工作区为子类扩展点，默认占位）
        self.workspace_page = self._create_workspace_page()
        self.result_page = self._create_result_page()
        self.history_page = self._create_history_page()

        # 注册顶部导航（子类可扩展/调整顺序）
        self._register_sub_interfaces()

        # 在后台线程中同步初始化 OCR 引擎（不阻塞UI）
        self._start_ocr_init()

        # 检查是否有待恢复的任务
        QTimer.singleShot(500, self._check_pending_task)

        # 注册自身主题刷新（子组件已在构造时注册，先于本行执行）
        ThemeManager.register_refresh_callback(self.apply_theme)

        # 应用设计（qfluentwidgets 先，ThemeManager.set_design 后；
        # 固定配色：窗口不监听 paletteChanged，不随系统主题变化）
        self._apply_design()

    # ── 页面构建（结果页/历史页从旧 main_window.py 机械提取） ────

    def _create_workspace_page(self) -> QWidget:
        """创建工作区页（默认占位；P3b Rapid 迁入真实工作区，P4 Gguf 同样覆盖）"""
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        label = BodyLabel("工作区")
        label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        layout.addWidget(label, alignment=Qt.AlignmentFlag.AlignCenter)
        return page

    def _register_sub_interfaces(self):
        """注册顶部导航（MSFluentWindow 要求 objectName 先设置）"""
        self.workspace_page.setObjectName('workspace')
        self.result_page.setObjectName('result')
        self.history_page.setObjectName('history')
        self.addSubInterface(self.workspace_page, _icon('fa5s.edit'), '工作区')
        self.addSubInterface(self.result_page, _icon('fa5s.table'), '识别结果')
        self.addSubInterface(self.history_page, _icon('fa5s.history'), '历史记录')
        self.switchTo(self.workspace_page)

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
        from app.ui.widgets.result_table import ResultTable
        self.result_table = ResultTable()
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
        from app.ui.widgets.history_panel import HistoryPanel
        self.history_panel = HistoryPanel(self.history_manager)
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
        from qfluentwidgets import LineEdit, ComboBox

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
        # RapidMainWindow 壳阶段无状态栏（工作区 P3b 迁入后可用），缺组件时跳过提示
        status_label = getattr(self, 'status_label', None)
        if modified > 0 and status_label is not None:
            status_label.setText(f"已修改 {modified} 个单元格")

    def _on_filter_changed(self):
        """[修复] 筛选条件变更 - 支持全部字段筛选，重置低置信度模式"""
        keyword = self.filter_edit.text()
        field_idx = self.filter_field_combo.currentIndex()
        status_label = getattr(self, 'status_label', None)  # 壳阶段无状态栏（P3b 迁入）

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
        status_label = getattr(self, 'status_label', None)  # 壳阶段无状态栏（P3b 迁入）
        if status_label is not None:
            status_label.setText("已重置所有数据为识别结果")

    def _on_toggle_low_confidence(self):
        """切换低置信度筛选模式"""
        status_label = getattr(self, 'status_label', None)  # 壳阶段无状态栏（P3b 迁入）
        if self._low_confidence_mode:
            # 当前是低置信度模式，切换回显示全部
            self.result_table.show_all_rows()
            self._low_confidence_mode = False
            self.btn_low_conf.setText("显示低置信度")
            total_count = self.result_table.rowCount()
            if status_label is not None:
                status_label.setText(f"显示全部 {total_count} 个结果")
        else:
            # 当前是显示全部模式，切换到低置信度筛选
            self.result_table.filter_low_confidence(threshold=0.7)
            self._low_confidence_mode = True
            self.btn_low_conf.setText("显示全部")
            visible_count = sum(1 for row in range(self.result_table.rowCount())
                               if not self.result_table.isRowHidden(row))
            if status_label is not None:
                status_label.setText(f"显示 {visible_count} 个低置信度项（置信度<70%）")

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

    # ── 主题应用（Task P3a：固定设计，不监听系统主题） ──────────

    def _apply_design(self):
        """应用设计：qfluentwidgets 先（重排会覆盖其控件内嵌 QSS），
        ThemeManager.set_design 后（自研色最后烘焙、生效）。"""
        setTheme(self.FLUENT_THEME)
        setThemeColor(self.ACCENT_COLOR)
        ThemeManager.set_design(self.DESIGN)
        # Win11 Mica/acrylic 是 DWM 合成材质（窗口背景为透明 + 系统云母层）。
        # 系统截图工具（Win+Shift+S）经 BitBlt 截屏时会破坏/无法合成该材质，
        # 透明区域回退为白色 → 深色界面"截图后变白"（自绘 QSS 部件不受影响）。
        # 禁用 DWM 材质：窗口背景改为自绘纯色，截图工具无法破坏。
        self.setMicaEffectEnabled(False)
        # 侧边导航（FluentWindow）用 NavigationInterface 支持 acrylic；
        # 顶部导航（MSFluentWindow）是 NavigationBar，无此 API
        if hasattr(self, 'navigationInterface') and hasattr(
                self.navigationInterface, 'setAcrylicEnabled'):
            self.navigationInterface.setAcrylicEnabled(False)

    def apply_theme(self):
        """重建窗口自身内嵌 QSS（ThemeManager.set_theme/set_design 后经
        注册回调调用；覆盖模板名称标签与结果页统计标签的颜色）"""
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
            # P6 签名：GGUF 深色操作台数字指标用等宽字体
            if ThemeManager.current_design() == 'gguf':
                for label in (self.stat_total, self.stat_success, self.stat_fail):
                    label.setFont(ThemeManager.get_font('mono'))

    # ── LoadingOverlay 创建/缩放（机械提取） ─────────────────────

    def _create_loading_overlay(self):
        """创建加载遮罩层"""
        from app.ui.widgets.loading_overlay import LoadingOverlay
        # 单会话一引擎（P4）：新窗口不再提供「使用CPU模式」复选框，
        # 设备切换走 GGUF 模型设置页（旧 MainWindow 默认仍保留该选项，P7 删除）
        self.loading_overlay = LoadingOverlay(self, show_cpu_fallback=False)
        self.loading_overlay.setGeometry(0, 0, self.width(), self.height())
        self.loading_overlay.show_loading()
        self.loading_overlay.raise_()
        self.loading_overlay.retry_requested.connect(self._on_ocr_retry)

    def resizeEvent(self, event):
        """窗口大小改变时调整遮罩层大小"""
        super().resizeEvent(event)
        if hasattr(self, 'loading_overlay'):
            self.loading_overlay.setGeometry(0, 0, self.width(), self.height())

    # ── 引擎异步初始化 + 世代计数器（机械提取 :145-173） ────────

    def _start_ocr_init(self):
        """在后台线程中同步初始化 OCR 引擎（不阻塞UI）"""
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

    # ── 就绪回调 / 重试（机械提取 :463-506） ─────────────────────

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
            # RapidMainWindow 壳阶段无 GPU 状态组件（工作区 P3b 迁入后可用）
            gpu_status = getattr(self, 'gpu_status', None)
            if gpu_status is not None:
                gpu_status.set_engine(self.ocr_engine)
            # 引擎就绪后才创建 BatchProcessor（避免引擎未就绪就被使用）
            self.processor = BatchProcessor(
                self.pdf_loader, self.ocr_engine, self.config,
                max_workers=self.config.get("batch", {}).get("max_workers", 4)
            )
            # 关键字处理器（KeywordBatchProcessor）仅 GGUF 窗口需要，
            # 由 GgufMainWindow._on_ocr_ready 创建（import 隔离约束）
        else:
            # 初始化失败，显示错误面板
            error_msg = self.ocr_engine.init_error or "未知错误"
            self.loading_overlay.show_error(error_msg)
            gpu_status = getattr(self, 'gpu_status', None)
            if gpu_status is not None:
                gpu_status.set_engine(self.ocr_engine)  # 更新GPU状态为加载失败

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

    # 注：_on_use_cpu_mode 已在 P4 删除（单会话一引擎；设备切换走 GGUF 设置页）

    def _create_status_bar(self) -> QWidget:
        """创建底部状态栏（StatusBar 提供 status_label 兼容属性）"""
        from app.ui.widgets.status_bar import StatusBar
        self.status_bar = StatusBar()
        self.status_label = self.status_bar.status_label
        # 回放已记录的引擎状态（引擎初始化可能早于状态栏创建完成）
        engine, status = getattr(self, '_last_engine_status', ("", "unavailable"))
        self.status_bar.set_engine_status(engine, status)
        return self.status_bar

    # ── pending task 恢复（机械提取 :541-588） ───────────────────

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
        if not pending_files:
            return
        # RapidMainWindow 壳阶段无文件面板（工作区 P3b 迁入后可用）；
        # 无面板时放弃恢复并清除待恢复任务（避免下次启动反复弹提示）
        file_panel = getattr(self, 'file_panel', None)
        if file_panel is None:
            CancelResultDialog.clear_pending_task()
            return
        # 添加待处理文件到列表
        file_panel.add_files(pending_files)

        InfoBar.success(
            title="任务已恢复",
            content=f"已加载 {len(pending_files)} 个待处理文件",
            duration=3000,
            parent=self
        )

        # 清除待恢复任务文件
        CancelResultDialog.clear_pending_task()

    # ── 配置持久化（机械提取 :2377-2383） ────────────────────────

    def _merge_config_patch(self, config: dict, patch: dict):
        """递归合并配置补丁"""
        for key, value in patch.items():
            if isinstance(value, dict) and key in config and isinstance(config[key], dict):
                self._merge_config_patch(config[key], value)
            else:
                config[key] = value

    # ── closeEvent 异步清理（机械提取 :2409-2534） ────────────────

    def closeEvent(self, event):
        """窗口关闭时异步执行清理，避免UI冻结"""
        # 防止重复触发
        if self._is_shutting_down:
            event.accept()
            return

        self._is_shutting_down = True

        # 0. 断开系统主题变化/焦点跟踪监听（Rapid 固定配色未接线；
        # 壳阶段无 _on_system_palette_changed/_on_focus_changed 时跳过）
        from PyQt6.QtWidgets import QApplication as _QApp
        _app_inst = _QApp.instance()
        if _app_inst is not None:
            on_palette = getattr(self, '_on_system_palette_changed', None)
            if on_palette is not None:
                try:
                    _app_inst.paletteChanged.disconnect(on_palette)
                except (TypeError, RuntimeError):
                    pass
            on_focus = getattr(self, '_on_focus_changed', None)
            if on_focus is not None:
                try:
                    _app_inst.focusChanged.disconnect(on_focus)
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
        worker = getattr(self, 'worker', None)
        if worker and worker.isRunning():
            worker.cancel()
            if self.results:
                try:
                    # RapidMainWindow 壳阶段无 file_panel（工作区 P3b
                    # 迁入后可用），缺组件时跳过任务快照保存
                    file_panel = getattr(self, 'file_panel', None)
                    if file_panel is not None:
                        all_files = file_panel.all_files()
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
            worker.wait(3000)

        # 4. 关闭进度对话框
        progress_dialog = getattr(self, 'progress_dialog', None)
        if progress_dialog:
            progress_dialog.close()

        # 5. 轻量级清理
        gpu_status = getattr(self, 'gpu_status', None)
        if gpu_status is not None:
            gpu_status.cleanup()
        self.pdf_loader.shutdown()
        save_config = getattr(self, '_save_current_pdf_config', None)
        if save_config is not None:
            save_config()

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
                # QApplication.quit() 线程安全，可直接在后台线程调用；
                # 原 QTimer.singleShot(0, 闭包) 从后台线程调用不执行，
                # 会导致清理完成后应用无法退出
                _on_cleanup_done()

        import threading
        self._shutdown_cleanup_thread = threading.Thread(
            target=_do_cleanup,
            daemon=False,  # 非daemon线程确保清理完成
            name="Shutdown-Cleanup"
        )
        self._shutdown_cleanup_thread.start()
