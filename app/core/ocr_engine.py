from paddleocr import PaddleOCR
from PIL import Image
import numpy as np
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
        self.ocr = PaddleOCR(
            use_angle_cls=use_angle_cls,
            lang=lang,
            use_gpu=use_gpu,
            show_log=False,
        )
        self._initialized = True

    def recognize(self, image: Image.Image, mode: str = "general") -> tuple:
        """
        返回 (合并文本, 平均置信度)
        """
        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)
        result = self.ocr.ocr(arr, cls=True)

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
