from PySide6.QtCore import QThread, Signal
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
