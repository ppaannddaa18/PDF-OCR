import logging

from PyQt6.QtCore import QThread, pyqtSignal as Signal
from PIL import Image

logger = logging.getLogger("PDFOCR")


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
    """VLM 整页解析异步工作线程（recognize_page_auto → enricher → PageResult）

    enricher: callable(page_result, image) — 结构化/表格/校验全部在 worker 线程内
    执行，不阻塞 UI。enricher 失败不阻断解析结果送达 UI（降级为结构化缺失）。
    """
    finished = Signal(object)  # PageResult
    error = Signal(str)

    def __init__(self, ocr_engine, image: Image.Image, enricher=None):
        super().__init__()
        self.ocr_engine = ocr_engine
        self.image = image
        self.enricher = enricher
        self._is_cancelled = False

    def cancel(self):
        """请求取消解析"""
        self._is_cancelled = True

    def run(self):
        if self._is_cancelled:
            return
        try:
            result = self.ocr_engine.recognize_page_auto(self.image)
            if self.enricher is not None:
                try:
                    self.enricher(result, self.image)
                except Exception:
                    logger.exception("ParseWorker: enricher failed, keep raw result")
            self.finished.emit(result)
        except Exception as e:
            self.error.emit(str(e))
