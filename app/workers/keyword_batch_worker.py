"""关键字批量 worker — QThread 薄层（镜像 BatchWorker）"""
import time

from PyQt6.QtCore import QThread, pyqtSignal as Signal


class KeywordBatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileKeywordResult]
    cancelled = Signal()

    PROGRESS_THROTTLE_MS = 100

    def __init__(self, processor, pdf_files, keywords):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.keywords = keywords
        self._is_cancelled = False
        self._last_progress_time = 0
        self._completed_results = []

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        self._completed_results.clear()

        def throttled_cb(done, total, current):
            if self._is_cancelled:
                raise InterruptedError("用户取消")
            now = time.time() * 1000
            if done == 1 or done == total or \
               now - self._last_progress_time >= self.PROGRESS_THROTTLE_MS:
                self.progress.emit(done, total, current)
                self._last_progress_time = now

        try:
            results = self.processor.process_batch(
                self.pdf_files, self.keywords, throttled_cb
            )
            self._completed_results = results
            self.finished_all.emit(results)
        except InterruptedError:
            self.cancelled.emit()
