"""关键字汇总页 — 操作带 / 汇总树 / 核对面板 / 统计与进度

布局（frontend-design 确认）：操作带（关键字输入+提取+导出 | 集合+保存+管理）
→ 左汇总树 + 右核对面板（初始隐藏）→ 底部统计条 + 进度条 + 取消。
"""
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QLabel, QComboBox, QProgressBar,
                             QSplitter, QMessageBox)

from app.ui.widgets.keyword_summary_tree import KeywordSummaryTree
from app.ui.widgets.keyword_inspection_panel import KeywordInspectionPanel
from app.ui.widgets.keyword_set_dialog import KeywordSetDialog
from app.ui.widgets.button_style import primary_qss
from app.ui.theme_manager import ThemeManager

_KW_SPLIT_RE = re.compile(r"[,，、;；\n]+")


# qtawesome 延迟加载（避免启动开销与字体警告）
_qta = None


def _get_qta():
    """获取 qtawesome 实例（延迟加载）"""
    global _qta
    if _qta is None:
        import qtawesome
        _qta = qtawesome
    return _qta


class KeywordSummaryPage(QWidget):
    """关键字批量汇总页（主题核心）"""

    upload_requested = pyqtSignal()
    extract_requested = pyqtSignal(list)         # keywords
    export_requested = pyqtSignal()
    save_set_requested = pyqtSignal(str, list)   # name, keywords
    manage_sets_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, set_manager, parent=None, left_panel=None,
                 status_bar=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self._build_ui(left_panel=left_panel, status_bar=status_bar)
        self._refresh_sets()
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _build_ui(self, left_panel=None, status_bar=None):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ThemeManager.get_spacing('lg'),
                                  ThemeManager.get_spacing('md'),
                                  ThemeManager.get_spacing('lg'),
                                  ThemeManager.get_spacing('sm'))
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # Row1：上传 PDF + 关键字输入 + 提取 + 导出
        row1 = QHBoxLayout()
        self.btn_upload = QPushButton("上传 PDF")
        self.btn_upload.setIcon(_get_qta().icon(
            'fa5s.upload', color=ThemeManager.get_color('on_accent')))
        self.btn_upload.setFixedHeight(32)
        self.btn_upload.setStyleSheet(primary_qss())
        self.btn_upload.setToolTip("选择 PDF 文件（Ctrl+O）")
        self.btn_upload.clicked.connect(self.upload_requested.emit)
        row1.addWidget(self.btn_upload)
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText(
            "逗号/顿号分隔，如：报关单号,价税合计,发票号码")
        row1.addWidget(self.keyword_input, stretch=1)
        self.btn_extract = QPushButton("提取")
        self.btn_extract.setStyleSheet(primary_qss())
        self.btn_extract.clicked.connect(self._on_extract_clicked)
        row1.addWidget(self.btn_extract)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setStyleSheet(primary_qss())
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_requested.emit)
        row1.addWidget(self.btn_export)
        layout.addLayout(row1)

        # Row2：关键字集
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("集合:"))
        self.set_combo = QComboBox()
        self.set_combo.currentIndexChanged.connect(
            lambda _i: self._on_set_selected())
        row2.addWidget(self.set_combo)
        self.btn_save_set = QPushButton("保存为集合")
        self.btn_save_set.clicked.connect(self._on_save_set)
        row2.addWidget(self.btn_save_set)
        self.btn_manage_sets = QPushButton("管理集合")
        self.btn_manage_sets.clicked.connect(self.manage_sets_requested.emit)
        row2.addWidget(self.btn_manage_sets)
        row2.addStretch()
        layout.addLayout(row2)

        # 主体：可选左侧文件列表 + 汇总树 + 核对面板（初始隐藏）
        # GGUF 窗口把文件列表嵌在关键字页内部（子界面必须是整页容器，
        # 否则 addSubInterface 重挂载时外层 wrapper 会被丢弃）
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = KeywordSummaryTree()
        self.splitter.addWidget(self.tree)
        self.inspection = KeywordInspectionPanel()
        self.inspection.setVisible(False)
        self.splitter.addWidget(self.inspection)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        main_row = QHBoxLayout()
        main_row.setSpacing(ThemeManager.get_spacing('sm'))
        if left_panel is not None:
            main_row.addWidget(left_panel)
        main_row.addWidget(self.splitter, 1)
        layout.addLayout(main_row, 1)

        # Row3：统计 + 进度 + 取消
        self.stats_label = QLabel("尚未提取")
        self.stats_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        layout.addWidget(self.stats_label)
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, stretch=1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        progress_row.addWidget(self.btn_cancel)
        layout.addLayout(progress_row)

        # 底部状态栏（GGUF 窗口传入：与文件列表一起保留在关键字页内）
        if status_bar is not None:
            layout.addWidget(status_bar)

        self._last_results = []

    # ---------- 对外接口 ----------

    def load_results(self, results):
        self._last_results = results
        self.tree.load_results(results)
        self._update_stats(results)

    def set_progress(self, done: int, total: int, current: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.stats_label.setText(f"正在提取 {done}/{total}: {current}")

    def set_running(self, running: bool):
        self.progress_bar.setVisible(running)
        self.btn_cancel.setVisible(running)
        self.btn_extract.setEnabled(not running)

    def enable_export(self, enabled: bool):
        self.btn_export.setEnabled(enabled)

    def refresh_sets(self):
        self._refresh_sets()

    def current_results(self):
        return self._last_results

    # ---------- 内部 ----------

    def _refresh_sets(self):
        current = self.set_combo.currentText()
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItems(self.set_manager.list_sets())
        if current:
            idx = self.set_combo.findText(current)
            self.set_combo.setCurrentIndex(max(0, idx))
        self.set_combo.blockSignals(False)

    def _on_set_selected(self):
        name = self.set_combo.currentText()
        if not name:
            return
        kws = self.set_manager.load(name)
        if kws:
            self.keyword_input.setText("，".join(kws))

    def _on_extract_clicked(self):
        keywords = [k.strip() for k in _KW_SPLIT_RE.split(self.keyword_input.text())
                    if k.strip()]
        if not keywords:
            return
        self.extract_requested.emit(keywords)

    def _on_save_set(self):
        keywords = [k.strip() for k in _KW_SPLIT_RE.split(self.keyword_input.text())
                    if k.strip()]
        if not keywords:
            QMessageBox.warning(self, "提示", "请先输入关键字")
            return
        name, ok = KeywordSetDialog.ask_name(self, self.set_manager.list_sets())
        if ok and name:
            self.save_set_requested.emit(name, keywords)

    def _update_stats(self, results):
        files = len(results)
        pages = sum(len(fr.pages) for fr in results)
        pending = sum(1 for fr in results for pg in fr.pages
                      for c in pg.cells.values() if c.status == "pending")
        failed = sum(1 for fr in results if not fr.success)
        self.stats_label.setText(
            f"共 {files} 个文件 | {pages} 页 | 待确认 {pending} | 失败 {failed}")

    def apply_theme(self):
        self.stats_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        # P6 签名：GGUF 深色操作台统计数字用等宽字体
        if ThemeManager.current_design() == 'gguf':
            self.stats_label.setFont(ThemeManager.get_font('mono'))
        else:
            from PyQt6.QtGui import QFont
            self.stats_label.setFont(QFont())
        self.btn_extract.setStyleSheet(primary_qss())
        self.btn_export.setStyleSheet(primary_qss())
        self.btn_upload.setStyleSheet(primary_qss())
        self.btn_upload.setIcon(_get_qta().icon(
            'fa5s.upload', color=ThemeManager.get_color('on_accent')))
        self.inspection.apply_theme()
