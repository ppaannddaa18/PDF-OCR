from PyQt6.QtWidgets import (
    QWidget, QHBoxLayout, QVBoxLayout, QFileDialog, QStackedWidget
)
from PyQt6.QtCore import Qt, QSize
from qfluentwidgets import (
    FluentWindow, NavigationItemPosition,
    TransparentToolButton, TransparentPushButton, SubtitleLabel,
    StrongBodyLabel, BodyLabel, InfoBar, InfoBarPosition,
    setTheme, Theme, ProgressBar
)
import qtawesome as qta

from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.widgets.file_list_panel import FileListPanel
from app.ui.widgets.field_panel import FieldPanel
from app.ui.widgets.result_table import ResultTable
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.core.batch_processor import BatchProcessor
from app.core.template_manager import TemplateManager
from app.core.exporter import Exporter
from app.workers.batch_worker import BatchWorker


class MainWindow(FluentWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(config["app"]["name"])
        self.resize(*config["app"]["window_size"])

        # 设置主题（跟随系统）
        setTheme(Theme.AUTO)

        # 核心组件
        self.pdf_loader = PdfLoader(dpi=config["pdf"]["render_dpi"])
        self.ocr_engine = OCREngine(
            lang=config["ocr"]["lang"],
            use_gpu=config["ocr"]["use_gpu"],
        )
        self.processor = BatchProcessor(self.pdf_loader, self.ocr_engine)
        self.template_mgr = TemplateManager()
        self.exporter = Exporter()

        self.results = []
        self.worker = None
        self.state_tooltip = None

        # 创建子页面
        self.template_page = self._create_template_page()
        self.result_page = self._create_result_page()

        # 初始化导航
        self._init_navigation()

        # 设置主内容区
        self.stackedWidget.addWidget(self.template_page)
        self.stackedWidget.addWidget(self.result_page)
        self.stackedWidget.setCurrentWidget(self.template_page)

        self._connect_signals()

    def _init_navigation(self):
        """初始化侧边导航栏"""
        self.navigationInterface.addItem(
            routeKey='workspace',
            icon=qta.icon('fa5s.edit', color='#0078d4'),
            text='工作区',
            onClick=lambda: self.switchTo(self.template_page)
        )

        self.navigationInterface.addItem(
            routeKey='result',
            icon=qta.icon('fa5s.table', color='#0078d4'),
            text='识别结果',
            onClick=lambda: self.switchTo(self.result_page),
            position=NavigationItemPosition.BOTTOM
        )

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
        content_layout.setSpacing(10)

        # 左栏：文件列表
        self.file_panel = FileListPanel()
        self.file_panel.setFixedWidth(200)
        content_layout.addWidget(self.file_panel)

        # 中栏：PDF 画布
        self.pdf_canvas = PdfCanvas()
        content_layout.addWidget(self.pdf_canvas, 4)

        # 右栏：字段配置
        self.field_panel = FieldPanel()
        self.field_panel.setFixedWidth(280)
        content_layout.addWidget(self.field_panel)

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

        # 结果表格
        self.result_table = ResultTable()
        layout.addWidget(self.result_table, 1)

        return page

    def _create_stats_widget(self) -> QWidget:
        """创建统计信息卡片"""
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(20)

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
        btn_export.setIcon(qta.icon('fa5s.file-excel', color='#0078d4'))
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
        shortcut_label = BodyLabel("Ctrl+O 上传 | Ctrl+S 保存模板 | Ctrl+Enter 批量识别")
        shortcut_label.setStyleSheet("color: #666; font-size: 11px;")
        layout.addWidget(shortcut_label)

        return bar

    def _create_toolbar(self) -> QWidget:
        """创建 Fluent 风格工具栏"""
        toolbar = QWidget()
        toolbar_layout = QHBoxLayout(toolbar)
        toolbar_layout.setContentsMargins(5, 5, 5, 5)
        toolbar_layout.setSpacing(4)

        # 上传按钮（带文字）
        btn_upload = TransparentPushButton("上传 PDF", self)
        btn_upload.setIcon(qta.icon('fa5s.file-upload', color='#0078d4'))
        btn_upload.clicked.connect(self.on_upload)
        toolbar_layout.addWidget(btn_upload)

        toolbar_layout.addSpacing(8)

        # 试识别按钮
        btn_try = TransparentPushButton("试识别", self)
        btn_try.setIcon(qta.icon('fa5s.search', color='#0078d4'))
        btn_try.clicked.connect(self.on_try_ocr)
        toolbar_layout.addWidget(btn_try)

        # 批量识别按钮
        btn_batch = TransparentPushButton("批量识别", self)
        btn_batch.setIcon(qta.icon('fa5s.play', color='#107c10'))
        btn_batch.clicked.connect(self.on_batch_run)
        toolbar_layout.addWidget(btn_batch)

        toolbar_layout.addSpacing(12)

        # 分隔线
        sep = QWidget()
        sep.setFixedWidth(1)
        sep.setFixedHeight(24)
        sep.setStyleSheet("background: #e0e0e0;")
        toolbar_layout.addWidget(sep)

        toolbar_layout.addSpacing(12)

        # 保存模板按钮
        btn_save = TransparentPushButton("保存模板", self)
        btn_save.setIcon(qta.icon('fa5s.save', color='#0078d4'))
        btn_save.clicked.connect(self.on_save_template)
        toolbar_layout.addWidget(btn_save)

        # 加载模板按钮
        btn_load = TransparentPushButton("加载模板", self)
        btn_load.setIcon(qta.icon('fa5s.folder-open', color='#0078d4'))
        btn_load.clicked.connect(self.on_load_template)
        toolbar_layout.addWidget(btn_load)

        toolbar_layout.addStretch()
        return toolbar

    def _connect_signals(self):
        self.file_panel.file_selected.connect(self.on_file_selected)
        self.pdf_canvas.region_drawn.connect(self.field_panel.add_region)
        self.field_panel.region_changed.connect(self.pdf_canvas.update_regions)
        self.field_panel.region_deleted.connect(self.pdf_canvas.remove_region)

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

    def on_file_selected(self, pdf_path: str):
        image = self.pdf_loader.render_page(pdf_path)
        self.pdf_canvas.load_image(image)
        self.status_label.setText(f"当前: {pdf_path.split('/')[-1]} - 在画布上拖拽框选区域")

    def on_try_ocr(self):
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
        self.status_label.setText(f"试识别完成 - 共 {len(template.regions)} 个字段")

    def on_batch_run(self):
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
        self.progress_bar.setRange(0, len(files))
        self.progress_bar.setValue(0)
        self.progress_label.setText(f"0/{len(files)}")

        self.worker = BatchWorker(self.processor, files, template)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_batch_done)
        self.worker.start()
        self.status_label.setText("批量识别进行中...")

    def _on_progress(self, done, total, current_file):
        self.progress_bar.setValue(done)
        self.progress_label.setText(f"{done}/{total}")
        self.status_label.setText(f"处理中: {current_file.split('/')[-1]} ({done}/{total})")

    def _on_batch_done(self, results):
        # 隐藏进度条
        self.progress_widget.setVisible(False)

        self.results = results
        self.result_table.load_results(results)

        # 更新统计信息
        total = len(results)
        success = sum(1 for r in results if r.success)
        fail = total - success
        self.stat_total.setText(f"共 {total} 个文件")
        self.stat_success.setText(f"成功: {success}")
        self.stat_fail.setText(f"失败: {fail}")

        self.switchTo(self.result_page)
        self.status_label.setText(f"批量识别完成 - 成功 {success}/{total}")

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
        path, _ = QFileDialog.getOpenFileName(self, "加载模板", "", "JSON (*.json)")
        if path:
            template = self.template_mgr.load(path)
            self.field_panel.load_template(template)
            self.pdf_canvas.update_regions(template.regions)
            InfoBar.success(
                title="成功",
                content="模板已加载",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=2000,
                parent=self
            )