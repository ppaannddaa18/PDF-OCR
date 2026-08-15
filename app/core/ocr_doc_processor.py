"""文档级 OCR 编排：PDF/图片 → 逐页渲染 → 引擎识别 → PageResult 列表
（新程序专用：顺序批量队列，GPU 单任务避免并发 OOM）"""
import os
import threading
import time
from typing import List, Optional, Dict
from PIL import Image
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine_base import OCREngineBase
from app.models.page_result import PageResult

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


class _ProcessThread(QThread):
    """后台处理线程：顺序执行文件队列，信号转发"""
    file_started = pyqtSignal(int, int)
    page_progress = pyqtSignal(str, int, int, float)
    file_done = pyqtSignal(str, list)
    file_failed = pyqtSignal(str, str)
    all_done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, loader, engine, queue, dpi, cancel_flag):
        super().__init__()
        self._loader = loader
        self._engine = engine
        self._queue = queue
        self._dpi = dpi
        self._cancel_flag = cancel_flag

    def run(self):
        total = len(self._queue)
        for idx, path in enumerate(self._queue):
            if self._cancel_flag.is_set():
                self.cancelled.emit()
                return
            self.file_started.emit(idx, total)
            try:
                pages = self._process_file(path)
                if self._cancel_flag.is_set():
                    # 取消：进行中文件的已解析页保留（file_done 先写缓存再发信号，与正常路径一致）
                    self.file_done.emit(path, pages)
                    self.cancelled.emit()
                    return
                self.file_done.emit(path, pages)
            except Exception as e:
                self.file_failed.emit(path, str(e))
        self.all_done.emit()

    def _process_file(self, path: str) -> List[PageResult]:
        if is_image_file(path):
            with Image.open(path) as im:
                page = self._engine.recognize_page_auto(im.convert("RGB"))
            return [page]
        count = self._loader.page_count(path)
        pages: List[PageResult] = []
        for i in range(count):
            if self._cancel_flag.is_set():
                return pages
            img = self._loader.render_page(path, i)  # dpi 为 PdfLoader 构造参数
            t0 = time.monotonic()
            try:
                page = self._engine.recognize_page_auto(img)
            except Exception:
                # 单页失败不中断文件：构造失败占位（markdown 空）并计入结果
                page = PageResult(blocks=[], markdown="", image_size=img.size)
                self.page_progress.emit(path, i + 1, count, 0.0)
                pages.append(page)
                continue
            self.page_progress.emit(path, i + 1, count,
                                    (time.monotonic() - t0) * 1000)
            pages.append(page)
        return pages


class OcrDocProcessor(QObject):
    """文档识别编排门面：队列管理 + 线程生命周期 + 结果缓存"""
    file_started = pyqtSignal(int, int)
    page_progress = pyqtSignal(str, int, int, float)
    file_done = pyqtSignal(str, list)
    file_failed = pyqtSignal(str, str)
    all_done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, loader: PdfLoader, engine: OCREngineBase, config: dict):
        super().__init__()
        self._loader = loader
        self._engine = engine
        self._dpi = int(config.get("pdf", {}).get("render_dpi", 200))
        self._queue: List[str] = []
        self._run_items: set = set()  # 本次运行快照：结束后只清空这批条目
        self._thread: Optional[_ProcessThread] = None
        self._cancel_flag = threading.Event()
        self._cache: Dict[str, List[PageResult]] = {}

    def add_files(self, paths: List[str]) -> None:
        for p in paths:
            if p not in self._queue:
                self._queue.append(p)
            # 显式重加入（重试语义）：从本次运行快照摘除，
            # 运行结束时不再被 _clear_run_queue 清出，由续跑机制重新处理
            self._run_items.discard(p)

    def clear_queue(self) -> None:
        """清空未处理队列（运行中调用不影响已启动的线程，仅终止后续续跑）"""
        self._queue.clear()

    def get_cache(self, path: str) -> Optional[List[PageResult]]:
        return self._cache.get(path)

    def clear_cache(self) -> None:
        self._cache.clear()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self) -> None:
        if self.is_running() or not self._queue:
            return
        self._cancel_flag.clear()
        self._run_items = set(self._queue)  # 本次运行快照
        self._thread = _ProcessThread(self._loader, self._engine,
                                      list(self._queue), self._dpi,
                                      self._cancel_flag)
        self._thread.file_started.connect(self.file_started)
        self._thread.page_progress.connect(self.page_progress)
        self._thread.file_done.connect(self._on_file_done)
        self._thread.file_failed.connect(self.file_failed)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.cancelled.connect(self._on_cancelled)
        # 保持引用直至 finished（QThread 收尾时置 None 属 Qt UB），finished 后回收
        self._thread.finished.connect(self._on_thread_finished)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_flag.set()

    def _on_file_done(self, path: str, pages: List[PageResult]) -> None:
        self._cache[path] = pages
        self.file_done.emit(path, pages)

    def _on_all_done(self) -> None:
        if self._thread is self.sender():
            self._clear_run_queue()
            self.all_done.emit()
            if self._queue:
                self.start()  # 续跑：运行期间追加/重试入队的条目

    def _on_cancelled(self) -> None:
        if self._thread is self.sender():
            self._clear_run_queue()
            self.cancelled.emit()
            if self._queue:
                self.start()  # 续跑：取消后仍有未处理条目（运行中重试）

    def _on_thread_finished(self) -> None:
        # finished 之后线程对象才可安全回收；若已被新线程替换，只回收旧对象
        thread = self.sender()
        if thread is not None:
            thread.deleteLater()
        if self._thread is thread:
            self._thread = None
            if self._queue:
                # 竞态兜底：all_done/cancelled 处理之后又入队（如运行中重试
                # 恰好发生在批次收尾），此时线程已停止，可安全续跑
                self.start()

    def _clear_run_queue(self) -> None:
        """只清空本次运行快照条目，运行期间 add_files 追加的保留到下次 start"""
        if self._run_items:
            self._queue = [p for p in self._queue if p not in self._run_items]
            self._run_items = set()
