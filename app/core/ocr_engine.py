from rapidocr_onnxruntime import RapidOCR
from PIL import Image
import numpy as np
import threading
from app.utils.image_utils import preprocess_for_ocr


class OCREngine:
    _instance = None

    def __new__(cls, *args, **kwargs):
        # 单例：避免 RapidOCR 模型被重复加载
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
        self._init_error = None  # 存储初始化错误信息
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
                # RapidOCR 默认使用 PP-OCRv4 模型
                self._ocr = RapidOCR()
                self._initialized = True
                self._init_error = None
            except Exception as e:
                self._init_error = str(e)
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
            self._ocr = RapidOCR()
            self._initialized = True

    @property
    def is_ready(self) -> bool:
        """检查OCR引擎是否已初始化完成"""
        return self._initialized

    @property
    def is_loading(self) -> bool:
        """检查OCR引擎是否正在加载"""
        return self._loading

    @property
    def init_error(self) -> str:
        """获取初始化错误信息"""
        return self._init_error or ""

    def recognize(self, image: Image.Image, mode: str = "general") -> tuple:
        """
        返回 (合并文本, 平均置信度)
        """
        if not self._initialized:
            if self._init_error:
                raise RuntimeError(f"OCR引擎初始化失败: {self._init_error}")
            raise RuntimeError("OCR引擎未初始化，请先调用 initialize_async() 或 initialize_sync()")

        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)

        with self._lock:
            # RapidOCR 返回 (result, elapse)
            # result: [[bbox, text, confidence], ...]
            result, elapse = self._ocr(arr)

        if result is None or len(result) == 0:
            return "", 0.0

        lines = []
        confidences = []
        for line in result:
            # RapidOCR: [bbox, text, confidence]
            text, conf = line[1], line[2]
            lines.append(text)
            confidences.append(conf)

        merged = " ".join(lines) if mode == "single_line" else "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return merged, avg_conf
