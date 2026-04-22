from PIL import Image, ImageEnhance
import cv2
import numpy as np


def preprocess_for_ocr(image: Image.Image, mode: str = "general") -> Image.Image:
    """OCR 前的图像预处理：放大、去噪、对比度增强"""
    # 放大小图
    if min(image.size) < 100:
        image = image.resize((image.size[0]*3, image.size[1]*3), Image.LANCZOS)

    # 转灰度 + 自适应阈值（仅对 general/number 模式）
    if mode == "number":
        arr = np.array(image.convert("L"))
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 10)
        image = Image.fromarray(arr).convert("RGB")
    else:
        # 轻度增强对比度
        image = ImageEnhance.Contrast(image.convert("RGB")).enhance(1.2)

    return image
