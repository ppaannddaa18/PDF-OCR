from PyQt6.QtCore import QThread, pyqtSignal as Signal
import time


class BatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileResult]

    # 进度信号节流参数
    PROGRESS_THROTTLE_MS = 100  # 最小更新间隔（毫秒）

    def __init__(self, processor, pdf_files, templates):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.templates = templates
        self._is_cancelled = False
        self._last_progress_time = 0

    def cancel(self):
        """请求取消批量处理"""
        self._is_cancelled = True

    def run(self):
        def throttled_cb(done, total, current):
            if self._is_cancelled:
                raise InterruptedError("用户取消")

            now = time.time() * 1000
            # 强制发送：第一个、最后一个、或间隔超过阈值
            if done == 1 or done == total or \
               now - self._last_progress_time >= self.PROGRESS_THROTTLE_MS:
                self.progress.emit(done, total, current)
                self._last_progress_time = now

        try:
            results = self.processor.process_batch_with_templates(self.pdf_files, self.templates, throttled_cb)
            self.finished_all.emit(results)
        except InterruptedError:
            self.finished_all.emit([])
