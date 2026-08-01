from PyQt6.QtCore import QThread, pyqtSignal as Signal
from PIL import Image


class OCRWorker(QThread):
    """单次 OCR 异步工作线程"""
    finished = Signal(str, float)  # text, confidence
    error = Signal(str)

    def __init__(self, ocr_engine, image: Image.Image, mode: str = "general"):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.image = image
        self.mode = mode

    def run(self):
        try:
            text, confidence = self.ocr_engine.recognize(self.image, self.mode)
            self.finished.emit(text, confidence)
        except Exception as e:
            self.error.emit(str(e))


class ParseWorker(QThread):
    """VLM 整页解析异步工作线程（recognize_page_auto → PageResult）"""
    finished = Signal(object)  # PageResult
    error = Signal(str)

    def __init__(self, ocr_engine, image: Image.Image):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.image = image
        self._is_cancelled = False

    def cancel(self):
        """请求取消解析"""
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return
        try:
            result = self.ocr_engine.recognize_page_auto(self.image)
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
