"""
GgufMainWindow — GGUF 双界面（深色科技「推理操作台」，Task P4）

MRO 契约（硬性，详见 base_window.py 顶部注释）：
    GgufMainWindow → AppBaseWindowMixin → FluentWindow → ... → QWidget

构造协议：
    _init_app_base(config)（纯数据）必须在 super().__init__() 之前；
    关键字状态 _init_keyword_state()（纯数据）同样在 super().__init__()
    之前；_post_init_base()（UI 部件）在 super().__init__() 之后；
    EngineStatusBand 在 _post_init_base 之后挂载。

引擎路径固定 gguf：config["ocr"]["engine"] 强制 'gguf'。窗口固定深色
（design='gguf'，强调色 #E8A33D + 状态色 #5EEAD4），不监听系统主题。

页面：侧边导航 4 页 —— 关键字提取（核心）/ 识别结果 / 历史记录 / 模型设置。
无模板工作区（不 import field_panel/pdf_canvas，import 隔离由测试断言）。

关键字提取结果经 keyword_result_adapter 转 FileResult 写入「识别结果」页与
历史记录（每文件每关键字一行）。
"""
import logging
import re

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QFileDialog
from qfluentwidgets import (
    FluentWindow,
    InfoBar, InfoBarPosition, Theme,
)

from app.ui.theme_manager import ThemeManager
from app.ui.windows.base_window import AppBaseWindowMixin
from app.ui.widgets.engine_status_band import EngineStatusBand
from app.utils.keyword_set_manager import KeywordSetManager


# qtawesome 延迟加载（与旧 main_window.py 一致）
qta = None


def _icon(name: str, color: str = '#E8A33D'):
    """获取图标（延迟加载 qtawesome）"""
    global qta
    if qta is None:
        import qtawesome
        qta = qtawesome
    return qta.icon(name, color=color)


class GgufMainWindow(AppBaseWindowMixin, FluentWindow):
    """GGUF 推理操作台：侧边导航 关键字提取 / 识别结果 / 历史记录 / 模型设置"""

    WINDOW_TITLE = "PDF OCR — 推理操作台"
    WINDOW_ICON = 'fa5s.cogs'
    DESIGN = 'gguf'
    ACCENT_COLOR = '#E8A33D'
    FLUENT_THEME = Theme.DARK

    def __init__(self, config):
        # 固定 gguf 路径：config 引擎强制 gguf
        config.setdefault("ocr", {})["engine"] = "gguf"
        self._init_app_base(config)  # pre-super：纯数据（config/世代/shutting_down/design）
        self._init_keyword_state()   # pre-super：关键字子系统纯数据
        super().__init__()
        logging.getLogger("PDFOCR").info(
            f"Session start | engine={self.engine_type} | design={self.design} | window=GgufMainWindow")
        self._post_init_base()  # post-super：UI 部件（页面/导航/引擎异步初始化）
        # 签名元素 1：窗口顶部 2px 引擎状态发光横线
        self.engine_band = EngineStatusBand(self)
        self.engine_band.setGeometry(0, 0, self.width(), 2)
        self.engine_band.raise_()
        self._connect_signals()
        self._setup_shortcuts()

    # ── 关键字子系统纯数据状态（pre-super） ─────────────────────

    def _init_keyword_state(self):
        """初始化关键字子系统状态（必须在 _post_init_base 之前）"""
        self.keyword_set_manager = KeywordSetManager()
        self._keyword_worker = None
        self._keyword_results = []
        self._keyword_processor = None  # _on_ocr_ready 时创建
        self._last_engine_status = ("", "unavailable")  # 状态栏回放用

    # ── 页面构建 ────────────────────────────────────────────────

    def _create_workspace_page(self) -> QWidget:
        """创建关键字提取页：左文件列表 + 中央汇总页 + 底部状态栏"""
        from app.ui.widgets.collapsible_panel import CollapsiblePanel
        from app.ui.widgets.file_list_panel import FileListPanel
        from app.ui.widgets.keyword_summary_page import KeywordSummaryPage

        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        content = QWidget()
        content_layout = QHBoxLayout(content)
        content_layout.setSpacing(0)
        content_layout.setContentsMargins(0, 0, 0, 0)

        # 左侧可折叠文件列表（复用 FileListPanel；无框选/模板列）
        self.left_panel = CollapsiblePanel(expanded_width=240, collapsed_width=48)
        self.file_panel = FileListPanel()
        self.left_panel.set_content(self.file_panel)
        content_layout.addWidget(self.left_panel)

        # 中央关键字汇总页（操作带/汇总树/核对面板/统计进度）
        self.keyword_page = KeywordSummaryPage(self.keyword_set_manager)
        content_layout.addWidget(self.keyword_page, 1)

        layout.addWidget(content, 1)
        layout.addWidget(self._create_status_bar())

        # 模型设置页（P5 实现设置表单，本任务占位）
        self.settings_page = self._create_settings_page()
        return page

    def _create_settings_page(self) -> QWidget:
        """创建模型设置页（GgufSettingsPage：表单 + 操作带）"""
        from app.ui.widgets.gguf_settings_page import GgufSettingsPage
        self.settings_page = GgufSettingsPage(self.config, self)
        self.settings_page.save_requested.connect(self._on_settings_save)
        self.settings_page.restart_requested.connect(self._on_settings_restart)
        self.settings_page.test_connection_requested.connect(
            self._on_settings_test_connection)
        return self.settings_page

    # ── 模型设置页动作（P5） ────────────────────────────────────

    def _on_settings_save(self, patch: dict):
        """保存并应用：合并配置 + 写盘（下次启动/重启引擎生效）"""
        self._merge_config_patch(self.config, patch)
        try:
            from app.utils.config_loader import save_config
            save_config(self.config)
        except Exception as e:
            InfoBar.error(title="保存失败", content=f"无法保存设置: {e}",
                          parent=self, duration=5000)
            return
        InfoBar.success(
            title="设置已保存",
            content="配置已写入 config.yaml，重启引擎后生效",
            parent=self, duration=3000)

    def _on_settings_restart(self, patch: dict):
        """重启引擎：合并配置 + 写盘；设备（GPU/CPU）变更走程序重启，
        其余参数进程内卸载重初始化"""
        old_device = self.config.get("ocr", {}).get("gguf", {}).get("device", "gpu")
        self._merge_config_patch(self.config, patch)
        new_device = self.config.get("ocr", {}).get("gguf", {}).get("device", "gpu")
        try:
            from app.utils.config_loader import save_config
            save_config(self.config)
        except Exception as e:
            InfoBar.error(title="保存失败", content=f"无法保存设置: {e}",
                          parent=self, duration=5000)
            return

        if new_device != old_device:
            # GPU↔CPU 需重启程序（llama-server 参数在启动时确定）
            self._restart_with_engine("gguf", new_device)
            return
        self._reinit_engine_in_process()
        InfoBar.success(
            title="引擎已重启",
            content="参数已应用，llama-server 重新初始化中",
            parent=self, duration=3000)

    def _reinit_engine_in_process(self):
        """进程内重启引擎（卸载 + 世代计数 + 后台重新初始化）"""
        if hasattr(self.ocr_engine, 'unload'):
            self.ocr_engine.unload()
        if hasattr(type(self.ocr_engine), 'reset_instance'):
            type(self.ocr_engine).reset_instance()
        from app.core.ocr_engine import get_ocr_engine
        self.ocr_engine = get_ocr_engine(self.config)

        if hasattr(self, 'engine_band'):
            self.engine_band.set_status('initializing')
        if hasattr(self, 'status_bar'):
            self.status_bar.set_engine_status(self.ocr_engine.engine_name, 'initializing')

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

        threading.Thread(target=_reinit, daemon=True, name="OCR-Restart").start()

    def _on_settings_test_connection(self):
        """测试连接：后台请求 llama-server /health"""
        gguf = self.config.get("ocr", {}).get("gguf", {})
        host = gguf.get("host", "127.0.0.1")
        port = gguf.get("port", 8080)

        import threading

        def _probe():
            from app.ui.widgets.gguf_settings_page import check_llama_health
            ok, msg = check_llama_health(host, port)

            def _show():
                if ok:
                    InfoBar.success(title="连接正常", content=msg,
                                    parent=self, duration=3000)
                else:
                    InfoBar.error(
                        title="连接失败",
                        content=f"{msg}（可点击『重启引擎』启动服务）",
                        parent=self, duration=5000)
            QTimer.singleShot(0, _show)

        threading.Thread(target=_probe, daemon=True, name="HealthCheck").start()

    def _register_sub_interfaces(self):
        """注册侧边导航（FluentWindow：左侧 NavigationInterface，4 页）"""
        self.keyword_page.setObjectName('keyword')
        self.result_page.setObjectName('result')
        self.history_page.setObjectName('history')
        self.settings_page.setObjectName('settings')
        self.addSubInterface(self.keyword_page, _icon('fa5s.magic'), '关键字提取')
        self.addSubInterface(self.result_page, _icon('fa5s.table'), '识别结果')
        self.addSubInterface(self.history_page, _icon('fa5s.history'), '历史记录')
        self.addSubInterface(self.settings_page, _icon('fa5s.cogs'), '模型设置')
        # 隐藏返回按钮
        self.navigationInterface.setReturnButtonVisible(False)
        self.switchTo(self.keyword_page)

    # ── 信号接线 ────────────────────────────────────────────────

    def _connect_signals(self):
        self.file_panel.upload_requested.connect(self.on_upload)
        self.file_panel.file_selected.connect(self._on_keyword_file_selected)
        self.file_panel.files_cleared.connect(self._on_keyword_files_cleared)
        self.keyword_page.extract_requested.connect(self._on_keyword_extract)
        self.keyword_page.export_requested.connect(self.on_keyword_export)
        self.keyword_page.save_set_requested.connect(self._on_keyword_save_set)
        self.keyword_page.manage_sets_requested.connect(self._on_keyword_manage_sets)
        self.keyword_page.cancel_requested.connect(self._on_keyword_cancel)
        self.keyword_page.tree.cell_inspect_requested.connect(self._on_cell_inspect)
        self.keyword_page.inspection.value_edited.connect(self._on_inspection_value_edited)

    # ── 引擎就绪（覆盖 base：发光带 + 状态栏 + 关键字处理器） ────

    def _on_ocr_ready(self):
        """OCR 引擎就绪回调：先走 base（遮罩/BatchProcessor），
        再更新 EngineStatusBand 与关键字处理器（仅 GGUF 窗口需要）"""
        # 与 base 相同的世代守卫：过期回调不做任何副作用
        if hasattr(self, '_ready_gen') and self._ready_gen != self._init_gen:
            return
        super()._on_ocr_ready()
        is_ready = self.ocr_engine.is_ready
        if hasattr(self, 'engine_band'):
            self.engine_band.set_status('ready' if is_ready else 'error')
        if hasattr(self, 'status_bar'):
            self.status_bar.set_engine_status(
                self.ocr_engine.engine_name,
                'ready' if is_ready else 'unavailable')
        if is_ready:
            from app.core.keyword_batch_processor import KeywordBatchProcessor
            self._keyword_processor = KeywordBatchProcessor(
                self.pdf_loader, self.ocr_engine, self.config,
                max_workers=self.config.get("batch", {}).get("max_workers", 4))

    def _on_ocr_retry(self):
        """重试初始化：发光带回到琥珀呼吸态"""
        if hasattr(self, 'engine_band'):
            self.engine_band.set_status('initializing')
        if hasattr(self, 'status_bar'):
            self.status_bar.set_engine_status(self.ocr_engine.engine_name, 'initializing')
        super()._on_ocr_retry()

    def resizeEvent(self, event):
        """窗口大小改变时：遮罩层（base）+ 顶部发光带跟随"""
        super().resizeEvent(event)
        if hasattr(self, 'engine_band'):
            self.engine_band.setGeometry(0, 0, self.width(), 2)
            self.engine_band.raise_()

    # ── 文件列表 ────────────────────────────────────────────────

    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_panel.add_files(files)
            self.status_label.setText(f"已加载 {len(files)} 个文件 - 输入关键字后提取")

    def _on_keyword_file_selected(self, pdf_path: str):
        from pathlib import Path
        self.status_label.setText(f"当前: {Path(pdf_path).name}")

    def _on_keyword_files_cleared(self):
        self._keyword_results = []
        self.keyword_page.load_results([])
        self.keyword_page.enable_export(False)
        self.status_label.setText("文件列表已清空 - 请上传 PDF")

    # ── 关键字提取/汇总/核对/导出（从旧 main_window.py 机械迁移） ──

    def _on_keyword_extract(self, keywords: list):
        if self._keyword_worker and self._keyword_worker.isRunning():
            InfoBar.warning(title="提示", content="关键字提取正在进行中",
                            parent=self, duration=2000)
            return
        if getattr(self, "worker", None) and self.worker.isRunning():
            InfoBar.warning(title="提示", content="模板批量识别进行中，请等待完成",
                            parent=self, duration=2000)
            return
        if self._keyword_processor is None:
            InfoBar.error(title="引擎未就绪", content="请等待 OCR 引擎初始化完成",
                          parent=self, duration=3000)
            return
        files = self.file_panel.all_files()
        if not files:
            InfoBar.warning(title="提示", content="请先在文件列表上传 PDF",
                            parent=self, duration=2000)
            return
        from app.workers.keyword_batch_worker import KeywordBatchWorker
        self.keyword_page.set_running(True)
        self._keyword_worker = KeywordBatchWorker(self._keyword_processor, files, keywords)
        self._keyword_worker.progress.connect(self.keyword_page.set_progress)
        self._keyword_worker.finished_all.connect(self._on_keyword_done)
        self._keyword_worker.cancelled.connect(self._on_keyword_cancelled)
        self._keyword_worker.start()

    def _on_keyword_done(self, results):
        self._keyword_results = results
        self.keyword_page.set_running(False)
        self.keyword_page.load_results(results)
        self.keyword_page.enable_export(True)
        # 适配器：关键字结果同步到「识别结果」页与历史记录
        self._sync_keyword_results_to_result_page(results)
        self.status_label.setText(f"关键字提取完成：{len(results)} 个文件")

    def _sync_keyword_results_to_result_page(self, results):
        """把关键字结果经 adapter 转 FileResult 写入结果页/历史/统计"""
        from app.core.keyword_result_adapter import to_file_results
        file_results = to_file_results(results, engine="gguf")
        self.results = file_results
        self.result_table.load_results(file_results)
        self.history_manager.add_record(file_results)

        total = len(file_results)
        success = sum(1 for r in file_results if r.success)
        fail = total - success
        self.stat_total.setText(f"共 {total} 个文件")
        self.stat_success.setText(f"成功: {success}")
        self.stat_fail.setText(f"失败: {fail}")

        self.filter_field_combo.clear()
        self.filter_field_combo.addItem("全部字段")
        if file_results:
            field_names = []
            for r in file_results:
                for fn in r.fields:
                    if fn not in field_names:
                        field_names.append(fn)
            self.filter_field_combo.addItems(field_names)

    def _on_keyword_cancelled(self):
        self.keyword_page.set_running(False)
        partial = list(getattr(self._keyword_worker, "_completed_results", []) or [])
        if partial:
            self.keyword_page.load_results(partial)
            self.keyword_page.enable_export(True)
            self._sync_keyword_results_to_result_page(partial)
        self.status_label.setText("关键字提取已取消")

    def _on_keyword_cancel(self):
        if self._keyword_worker and self._keyword_worker.isRunning():
            self._keyword_worker.cancel()

    def _on_keyword_save_set(self, name: str, keywords: list):
        self.keyword_set_manager.save(name, keywords)
        self.keyword_page.refresh_sets()
        InfoBar.success(title="已保存", content=f"关键字集「{name}」",
                        parent=self, duration=2000)

    def _on_keyword_manage_sets(self):
        from app.ui.widgets.keyword_set_dialog import KeywordSetDialog
        dlg = KeywordSetDialog(self.keyword_set_manager, self)
        dlg.exec()
        if dlg.result_value():
            name, kws = dlg.result_value()
            self.keyword_page.set_combo.setCurrentText(name)
            self.keyword_page.keyword_input.setText("，".join(kws))
        self.keyword_page.refresh_sets()

    def on_keyword_export(self):
        results = self.keyword_page.current_results()
        if not results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出关键字汇总", "keyword_summary.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            from app.core.keyword_exporter import KeywordExporter
            KeywordExporter().to_excel(results, path)
        except Exception as e:
            InfoBar.error(title="导出失败", content=str(e), parent=self, duration=3000)
            return
        InfoBar.success(title="已导出", content=path, parent=self, duration=3000)

    def _on_cell_inspect(self, file_index: int, page_no: int, keyword: str):
        if file_index < 0 or file_index >= len(self._keyword_results):
            return
        fr = self._keyword_results[file_index]
        if page_no < 1 or page_no > len(fr.pages):
            return
        dpi = int(self.config.get("pdf", {}).get("render_dpi", 200))
        self.keyword_page.inspection._file_index = file_index
        self.keyword_page.inspection.show_inspection(
            fr.source_file, page_no, self.pdf_loader, dpi,
            fr.pages[page_no - 1].cells, keyword)
        self.keyword_page.inspection.setVisible(True)

    def _on_inspection_value_edited(self, file_index, page_no, keyword, new_value):
        if file_index < 0 or file_index >= len(self._keyword_results):
            return
        fr = self._keyword_results[file_index]
        if page_no < 1 or page_no > len(fr.pages):
            return
        cell = fr.pages[page_no - 1].cells.get(keyword)
        if cell is not None:
            cell.value = new_value
            cell.manually_edited = True
        self.keyword_page.tree.load_results(self._keyword_results)  # 刷新树

    # ── 快捷键（GGUF 子集，与 Rapid 完全隔离） ───────────────────

    def _setup_shortcuts(self):
        """设置快捷键：Ctrl+O 上传 / Ctrl+Enter 提取 / Ctrl+S 保存集合 /
        Ctrl+Shift+N 新建集合 / Ctrl+Shift+F 导出"""
        from PyQt6.QtGui import QShortcut, QKeySequence

        shortcut_upload = QShortcut(QKeySequence("Ctrl+O"), self)
        shortcut_upload.setObjectName("Ctrl+O")
        shortcut_upload.activated.connect(self.on_upload)

        shortcut_extract = QShortcut(QKeySequence("Ctrl+Return"), self)
        shortcut_extract.setObjectName("Ctrl+Return")
        shortcut_extract.activated.connect(self.keyword_page._on_extract_clicked)

        shortcut_save_set = QShortcut(QKeySequence("Ctrl+S"), self)
        shortcut_save_set.setObjectName("Ctrl+S")
        shortcut_save_set.activated.connect(self._on_keyword_save_set_shortcut)

        shortcut_new_set = QShortcut(QKeySequence("Ctrl+Shift+N"), self)
        shortcut_new_set.setObjectName("Ctrl+Shift+N")
        shortcut_new_set.activated.connect(self._on_keyword_new_set)

        shortcut_export = QShortcut(QKeySequence("Ctrl+Shift+F"), self)
        shortcut_export.setObjectName("Ctrl+Shift+F")
        shortcut_export.activated.connect(self.on_keyword_export)

    def _on_keyword_save_set_shortcut(self):
        """Ctrl+S: 将当前输入保存为命名关键字集"""
        text = self.keyword_page.keyword_input.text().strip()
        keywords = [k.strip() for k in re.split(r"[,，、;；\n]+", text) if k.strip()]
        if not keywords:
            InfoBar.warning(title="提示", content="请先输入关键字",
                            parent=self, duration=2000)
            return
        from app.ui.widgets.keyword_set_dialog import KeywordSetDialog
        name, ok = KeywordSetDialog.ask_name(self, self.keyword_set_manager.list_sets())
        if ok and name:
            self._on_keyword_save_set(name, keywords)

    def _on_keyword_new_set(self):
        """Ctrl+Shift+N: 新建关键字集（清空输入框并聚焦）"""
        self.keyword_page.keyword_input.clear()
        self.keyword_page.keyword_input.setFocus()
        self.status_label.setText("已新建空白关键字集 - 输入关键字后按 Ctrl+Enter 提取")

    # ── GGUF GPU↔CPU 重启（设置页 P5 调用；单会话内保留） ────────

    def _restart_with_engine(self, engine_type: str, device: str = None):
        """写入配置并重启程序切换 GGUF 设备（GPU↔CPU 需重启）"""
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
            logging.getLogger("PDFOCR").error(f"保存配置失败: {e}")

        import sys
        subprocess.Popen([sys.executable, *sys.argv], close_fds=True)
        from PyQt6.QtWidgets import QApplication
        QApplication.quit()
