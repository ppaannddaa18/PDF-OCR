from PyQt6.QtCore import QThread, pyqtSignal as Signal


class BatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileResult]

    def __init__(self, processor, pdf_files, template):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.template = template
        self._is_cancelled = False

    def cancel(self):
        """请求取消批量处理"""
        self._is_cancelled = True

    def run(self):
        def cb(done, total, current):
            if self._is_cancelled:
                raise InterruptedError("用户取消")
            self.progress.emit(done, total, current)
        try:
            results = self.processor.process_batch(self.pdf_files, self.template, cb)
            self.finished_all.emit(results)
        except InterruptedError:
            self.finished_all.emit([])
