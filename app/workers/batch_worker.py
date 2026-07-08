from PyQt6.QtCore import QThread, pyqtSignal as Signal
import time


class BatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileResult]
    cancelled = Signal()                   # 取消信号

    # 进度信号节流参数
    PROGRESS_THROTTLE_MS = 100  # 最小更新间隔（毫秒）

    def __init__(self, processor, pdf_files, templates):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.templates = templates
        self._is_cancelled = False
        self._last_progress_time = 0
        self._completed_results = []  # 存储已完成的结果

    def cancel(self):
        """请求取消批量处理"""
        self._is_cancelled = True

    def run(self):
        # 每次启动时清空上一次的累积结果
        self._completed_results.clear()

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
            results = self.processor.process_batch_with_templates(
                self.pdf_files, self.templates, throttled_cb, self._completed_results
            )
            self.finished_all.emit(results)
        except InterruptedError:
            # 取消时只发送 cancelled 信号，让调用方决定如何处理部分结果
            self.cancelled.emit()
