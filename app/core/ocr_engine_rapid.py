"""
RapidOCR引擎 — 基于 ONNX Runtime 的轻量级OCR
线程安全的单例模式
"""
from typing import Optional, Tuple, Dict, List, Any
from PIL import Image
import numpy as np
import threading
from app.core.ocr_engine_base import OCREngineBase
from app.utils.image_utils import preprocess_for_ocr


class RapidOCREngine(OCREngineBase):
    """
    RapidOCR引擎 — 线程安全单例

    基于 RapidOCR (ONNX Runtime)，CPU运行，无需GPU。
    逐区域裁剪后识别。
    """
    _instance: Optional['RapidOCREngine'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, lang: str = "ch", use_gpu: bool = False, use_angle_cls: bool = True):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return
            self._ocr = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._ocr_lock = threading.RLock()
            self._lang = lang
            self._use_gpu = use_gpu
            self._use_angle_cls = use_angle_cls
            self._initialized_flag = True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用）"""
        if self._initialized:
            return
        with self._ocr_lock:
            if self._initialized:
                return
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr = RapidOCR()
                self._initialized = True
                self._warmup()
            except Exception as e:
                self._init_error = str(e)

    def _warmup(self) -> None:
        if not self._ocr:
            return
        try:
            dummy_img = np.zeros((10, 10, 3), dtype=np.uint8)
            self._ocr(dummy_img)
        except Exception:
            pass

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "rapidocr"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def unload(self) -> None:
        """RapidOCR无需显式卸载"""
        pass

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        if not self._initialized:
            # 尝试自动重新初始化
            try:
                self.initialize()
            except Exception:
                pass
            if not self._initialized:
                if self._init_error:
                    raise RuntimeError(f"OCR引擎初始化失败: {self._init_error}")
                raise RuntimeError("OCR引擎未初始化")

        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)

        with self._ocr_lock:
            if self._ocr is None:
                raise RuntimeError("OCR引擎未正确初始化")
            result, elapse = self._ocr(arr)

        if result is None or len(result) == 0:
            return "", 0.0

        lines = []
        confidences = []
        for line in result:
            text, conf = line[1], line[2]
            lines.append(text)
            confidences.append(conf)

        merged = " ".join(lines) if mode == "single_line" else "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return merged, avg_conf

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """逐区域裁剪后识别（保持现有行为）"""
        results = {}
        W, H = image.size
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            if right <= left or bottom <= top:
                crop = Image.new("RGB", (1, 1), (255, 255, 255))
            else:
                crop = image.crop((left, top, right, bottom))
            text, conf = self.recognize(crop, region.ocr_mode)
            results[region.id] = (text, conf, 0, None)
        return results

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance = None
