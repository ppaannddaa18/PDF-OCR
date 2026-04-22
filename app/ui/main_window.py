from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QTabWidget, QToolBar
)
from PySide6.QtCore import Qt
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


class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(config["app"]["name"])
        self.resize(*config["app"]["window_size"])

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
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        central = QWidget()
        main_layout = QHBoxLayout(central)

        # 左栏：文件列表
        self.file_panel = FileListPanel()

        # 中栏：PDF 画布（含工具栏）
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        self.pdf_canvas = PdfCanvas()
        toolbar = self._create_toolbar()
        center_layout.addWidget(toolbar)
        center_layout.addWidget(self.pdf_canvas, 1)

        # 右栏：字段配置
        self.field_panel = FieldPanel()

        # 底部：结果表格（用 Tab 切换）
        self.tabs = QTabWidget()
        self.tabs.addTab(center_widget, "模板编辑")
        self.result_table = ResultTable()
        self.tabs.addTab(self.result_table, "识别结果")

        main_layout.addWidget(self.file_panel, 1)
        main_layout.addWidget(self.tabs, 4)
        main_layout.addWidget(self.field_panel, 2)

        self.setCentralWidget(central)

    def _create_toolbar(self):
        toolbar = QToolBar()
        toolbar.addAction("上传PDF", self.on_upload)
        toolbar.addAction("试识别", self.on_try_ocr)
        toolbar.addAction("批量识别", self.on_batch_run)
        toolbar.addAction("导出Excel", self.on_export)
        toolbar.addSeparator()
        toolbar.addAction("保存模板", self.on_save_template)
        toolbar.addAction("加载模板", self.on_load_template)
        return toolbar

    def _connect_signals(self):
        self.file_panel.file_selected.connect(self.on_file_selected)
        self.pdf_canvas.region_drawn.connect(self.field_panel.add_region)
        self.field_panel.region_changed.connect(self.pdf_canvas.update_regions)
        self.field_panel.region_deleted.connect(self.pdf_canvas.remove_region)

    # ---------- 事件处理 ----------
    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_panel.add_files(files)
            # 将首份作为模板
            self.on_file_selected(files[0])

    def on_file_selected(self, pdf_path: str):
        image = self.pdf_loader.render_page(pdf_path)
        self.pdf_canvas.load_image(image)

    def on_try_ocr(self):
        template = self.field_panel.build_template()
        current_pdf = self.file_panel.current_file()
        if not current_pdf or not template.regions:
            QMessageBox.warning(self, "提示", "请先上传PDF并框选区域")
            return
        result = self.processor.process_one(current_pdf, template)
        self.field_panel.show_preview_result(result)

    def on_batch_run(self):
        template = self.field_panel.build_template()
        files = self.file_panel.all_files()
        if not files or not template.regions:
            QMessageBox.warning(self, "提示", "请先上传PDF并设置字段")
            return

        self.worker = BatchWorker(self.processor, files, template)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_batch_done)
        self.worker.start()

    def _on_progress(self, done, total, current_file):
        self.statusBar().showMessage(f"处理中 {done}/{total}: {current_file}")

    def _on_batch_done(self, results):
        self.results = results
        self.result_table.load_results(results)
        self.tabs.setCurrentIndex(1)
        QMessageBox.information(self, "完成", f"共处理 {len(results)} 个文件")

    def on_export(self):
        if not self.results:
            QMessageBox.warning(self, "提示", "尚无识别结果")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出Excel", "result.xlsx", "Excel (*.xlsx)")
        if path:
            # 如用户在表格里手动编辑过，需同步回 self.results
            self.results = self.result_table.collect_results()
            include_conf = self.config["export"]["include_confidence"]
            self.exporter.to_excel(self.results, path, include_conf)
            QMessageBox.information(self, "成功", f"已导出到 {path}")

    def on_save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "", "JSON (*.json)")
        if path:
            template = self.field_panel.build_template()
            self.template_mgr.save(template, path)
            QMessageBox.information(self, "成功", f"模板已保存到 {path}")

    def on_load_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载模板", "", "JSON (*.json)")
        if path:
            template = self.template_mgr.load(path)
            self.field_panel.load_template(template)
            self.pdf_canvas.update_regions(template.regions)