from paddleocr import PaddleOCR
from PIL import Image
import numpy as np
import threading
from app.utils.image_utils import preprocess_for_ocr


class OCREngine:
    _instance = None

    def __new__(cls, *args, **kwargs):
        # 单例：避免 PaddleOCR 模型被重复加载
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, lang="ch", use_gpu=False, use_angle_cls=True):
        if hasattr(self, "_initialized"):
            return
        # 延迟初始化模式
        self._ocr = None
        self._initialized = False
        self._loading = False
        self._lock = threading.Lock()
        self._lang = lang
        self._use_gpu = use_gpu
        self._use_angle_cls = use_angle_cls

    def initialize_async(self, callback=None):
        """异步初始化OCR引擎，不阻塞UI"""
        if self._initialized or self._loading:
            if callback:
                callback()
            return

        self._loading = True

        def _load():
            try:
                self._ocr = PaddleOCR(
                    use_angle_cls=self._use_angle_cls,
                    lang=self._lang,
                    use_gpu=self._use_gpu,
                    show_log=False,
                )
                self._initialized = True
            finally:
                self._loading = False
                if callback:
                    callback()

        thread = threading.Thread(target=_load, daemon=True)
        thread.start()

    def initialize_sync(self):
        """同步初始化OCR引擎（用于后台线程中调用）"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._ocr = PaddleOCR(
                use_angle_cls=self._use_angle_cls,
                lang=self._lang,
                use_gpu=self._use_gpu,
                show_log=False,
            )
            self._initialized = True

    @property
    def is_ready(self) -> bool:
        """检查OCR引擎是否已初始化完成"""
        return self._initialized

    @property
    def is_loading(self) -> bool:
        """检查OCR引擎是否正在加载"""
        return self._loading

    def recognize(self, image: Image.Image, mode: str = "general") -> tuple:
        """
        返回 (合并文本, 平均置信度)
        """
        if not self._initialized:
            raise RuntimeError("OCR引擎未初始化，请先调用 initialize_async() 或 initialize_sync()")

        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)

        with self._lock:
            result = self._ocr.ocr(arr, cls=True)

        if not result or not result[0]:
            return "", 0.0

        lines = []
        confidences = []
        for line in result[0]:
            text, conf = line[1][0], line[1][1]
            lines.append(text)
            confidences.append(conf)

        merged = " ".join(lines) if mode == "single_line" else "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return merged, avg_conf
