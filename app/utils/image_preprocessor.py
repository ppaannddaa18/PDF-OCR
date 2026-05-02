"""
图像预处理器 - 性能优化版
- 内存优化：避免双倍内存占用
- 按需复制图像
- 支持原地操作
- 智能判断是否需要复制
"""
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np
from typing import Optional, Tuple


class ImagePreprocessor:
    """
    图像预处理器 - 性能优化版

    优化点：
    1. 不再双倍存储原图，仅在需要时复制
    2. 支持原地操作减少内存分配
    3. 延迟处理，仅在获取图像时应用变换
    4. 智能判断：无变换时直接返回原图引用
    """

    def __init__(self, image: Image.Image):
        # 性能优化：只存储原图引用，不立即复制
        # 仅在需要修改时才复制（写时复制）
        self._original_image = image
        self._current_image: Optional[Image.Image] = None  # 延迟计算
        self._dirty = True  # 标记是否需要重新计算

        # 存储调整参数
        self.rotation = 0
        self.brightness = 1.0
        self.contrast = 1.0
        self.crop_box: Optional[Tuple[int, int, int, int]] = None
        self.threshold: Optional[int] = None
        self.auto_contrast_applied = False
        self.sharpen_applied = False

    def _has_transforms(self) -> bool:
        """检查是否有任何变换需要应用"""
        return (
            self.rotation != 0 or
            self.brightness != 1.0 or
            self.contrast != 1.0 or
            self.crop_box is not None or
            self.threshold is not None or
            self.auto_contrast_applied or
            self.sharpen_applied
        )

    def _ensure_current_image(self) -> Image.Image:
        """确保当前图像已计算（延迟处理）"""
        # 性能优化：无变换时直接返回原图引用
        if not self._has_transforms():
            return self._original_image

        if self._current_image is None or self._dirty:
            self._apply_transforms()
            self._dirty = False
        return self._current_image

    def reset(self) -> Image.Image:
        """重置所有调整"""
        self._current_image = None
        self._dirty = True
        self.rotation = 0
        self.brightness = 1.0
        self.contrast = 1.0
        self.crop_box = None
        self.threshold = None
        self.auto_contrast_applied = False
        self.sharpen_applied = False
        return self._ensure_current_image()

    def rotate(self, angle: int) -> Image.Image:
        """旋转图像（角度：0, 90, 180, 270）"""
        self.rotation = (self.rotation + angle) % 360
        self._dirty = True
        return self._ensure_current_image()

    def set_rotation(self, angle: int) -> Image.Image:
        """设置绝对旋转角度"""
        self.rotation = angle % 360
        self._dirty = True
        return self._ensure_current_image()

    def adjust_brightness(self, factor: float) -> Image.Image:
        """调整亮度（factor: 0.0-2.0, 1.0为原图）"""
        self.brightness = max(0.1, min(2.0, factor))
        self._dirty = True
        return self._ensure_current_image()

    def adjust_contrast(self, factor: float) -> Image.Image:
        """调整对比度（factor: 0.0-2.0, 1.0为原图）"""
        self.contrast = max(0.1, min(2.0, factor))
        self._dirty = True
        return self._ensure_current_image()

    def set_crop(self, left: int, top: int, right: int, bottom: int) -> Image.Image:
        """设置裁剪区域"""
        width, height = self._original_image.size
        left = max(0, min(left, width))
        top = max(0, min(top, height))
        right = max(left, min(right, width))
        bottom = max(top, min(bottom, height))
        self.crop_box = (left, top, right, bottom)
        self._dirty = True
        return self._ensure_current_image()

    def clear_crop(self) -> Image.Image:
        """清除裁剪"""
        self.crop_box = None
        self._dirty = True
        return self._ensure_current_image()

    def set_threshold(self, threshold: Optional[int] = None) -> Image.Image:
        """设置二值化阈值（None表示取消二值化，0-255）"""
        if threshold is None:
            self.threshold = None
        else:
            self.threshold = max(0, min(255, threshold))
        self._dirty = True
        return self._ensure_current_image()

    def auto_contrast(self) -> Image.Image:
        """自动对比度"""
        self.auto_contrast_applied = True
        self._dirty = True
        return self._ensure_current_image()

    def sharpen(self) -> Image.Image:
        """锐化"""
        self.sharpen_applied = True
        self._dirty = True
        return self._ensure_current_image()

    def denoise(self) -> Image.Image:
        """轻度降噪"""
        img = self._ensure_current_image()
        self._current_image = img.filter(ImageFilter.MedianFilter(size=3))
        return self._current_image

    def _apply_transforms(self):
        """应用所有变换（内部方法）"""
        # 如果有自动对比度标记，直接应用
        if self.auto_contrast_applied:
            img = ImageOps.autocontrast(self._original_image)
            if self.rotation != 0:
                img = img.rotate(-self.rotation, expand=True, fillcolor=(255, 255, 255))
            if self.threshold is not None:
                gray = img.convert('L')
                img = gray.point(
                    lambda x: 0 if x < self.threshold else 255, '1'
                ).convert('RGB')
            if self.sharpen_applied:
                img = img.filter(ImageFilter.SHARPEN)
            self._current_image = img
            return

        # 标准处理流程
        # 性能优化：仅在需要时复制原图
        img = self._original_image.copy()

        # 1. 先裁剪（在旋转前裁剪，基于原图坐标）
        if self.crop_box:
            img = img.crop(self.crop_box)

        # 2. 旋转
        if self.rotation != 0:
            img = img.rotate(-self.rotation, expand=True, fillcolor=(255, 255, 255))

        # 3. 亮度和对比度
        if self.brightness != 1.0:
            enhancer = ImageEnhance.Brightness(img)
            img = enhancer.enhance(self.brightness)

        if self.contrast != 1.0:
            enhancer = ImageEnhance.Contrast(img)
            img = enhancer.enhance(self.contrast)

        # 4. 二值化
        if self.threshold is not None:
            gray = img.convert('L')
            img = gray.point(lambda x: 0 if x < self.threshold else 255, '1').convert('RGB')

        # 5. 锐化
        if self.sharpen_applied:
            img = img.filter(ImageFilter.SHARPEN)

        self._current_image = img

    def get_current_image(self) -> Image.Image:
        """获取当前处理后的图像"""
        return self._ensure_current_image()

    def get_original_image(self) -> Image.Image:
        """获取原始图像"""
        return self._original_image

    def get_image_for_ocr(self) -> Image.Image:
        """
        获取用于OCR的图像
        性能优化：如果无变换，返回原图引用；否则返回处理后的图像副本
        """
        if not self._has_transforms():
            # 无变换，直接返回原图引用
            return self._original_image
        return self._ensure_current_image()

    def get_params(self) -> dict:
        """获取当前处理参数"""
        return {
            'rotation': self.rotation,
            'brightness': self.brightness,
            'contrast': self.contrast,
            'crop_box': self.crop_box,
            'threshold': self.threshold,
            'auto_contrast': self.auto_contrast_applied,
            'sharpen': self.sharpen_applied,
        }

    def set_params(self, params: dict) -> Image.Image:
        """设置处理参数"""
        self.rotation = params.get('rotation', 0)
        self.brightness = params.get('brightness', 1.0)
        self.contrast = params.get('contrast', 1.0)
        self.crop_box = params.get('crop_box', None)
        self.threshold = params.get('threshold', None)
        self.auto_contrast_applied = params.get('auto_contrast', False)
        self.sharpen_applied = params.get('sharpen', False)
        self._dirty = True
        return self._ensure_current_image()
