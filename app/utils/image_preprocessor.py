"""
图像预处理器 - 修复版
修复内容:
1. auto_contrast: 修复参数丢失问题，添加专门的 auto_contrast_applied 标记
2. _apply_transforms: 支持 auto_contrast 和 sharpen 标记
3. 移除 auto_contrast 中的 _apply_transforms 调用，避免覆盖
"""
from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import numpy as np


class ImagePreprocessor:
    """图像预处理器"""

    def __init__(self, image: Image.Image):
        self.original_image = image.copy()
        self.current_image = image.copy()
        # 存储调整参数
        self.rotation = 0
        self.brightness = 1.0
        self.contrast = 1.0
        self.crop_box = None  # (left, top, right, bottom) in pixels
        self.threshold = None  # None 表示不进行二值化
        self.auto_contrast_applied = False  # [修复] 自动对比度标记
        self.sharpen_applied = False  # [修复] 锐化标记

    def reset(self):
        """重置所有调整"""
        self.current_image = self.original_image.copy()
        self.rotation = 0
        self.brightness = 1.0
        self.contrast = 1.0
        self.crop_box = None
        self.threshold = None
        self.auto_contrast_applied = False  # [修复] 重置标记
        self.sharpen_applied = False  # [修复] 重置标记
        return self.current_image

    def rotate(self, angle: int):
        """旋转图像（角度：0, 90, 180, 270）"""
        self.rotation = (self.rotation + angle) % 360
        self._apply_transforms()
        return self.current_image

    def set_rotation(self, angle: int):
        """设置绝对旋转角度"""
        self.rotation = angle % 360
        self._apply_transforms()
        return self.current_image

    def adjust_brightness(self, factor: float):
        """调整亮度（factor: 0.0-2.0, 1.0为原图）"""
        self.brightness = max(0.1, min(2.0, factor))
        self._apply_transforms()
        return self.current_image

    def adjust_contrast(self, factor: float):
        """调整对比度（factor: 0.0-2.0, 1.0为原图）"""
        self.contrast = max(0.1, min(2.0, factor))
        self._apply_transforms()
        return self.current_image

    def set_crop(self, left: int, top: int, right: int, bottom: int):
        """设置裁剪区域"""
        width, height = self.original_image.size
        left = max(0, min(left, width))
        top = max(0, min(top, height))
        right = max(left, min(right, width))
        bottom = max(top, min(bottom, height))
        self.crop_box = (left, top, right, bottom)
        self._apply_transforms()
        return self.current_image

    def clear_crop(self):
        """清除裁剪"""
        self.crop_box = None
        self._apply_transforms()
        return self.current_image

    def set_threshold(self, threshold: int = None):
        """设置二值化阈值（None表示取消二值化，0-255）"""
        if threshold is None:
            self.threshold = None
        else:
            self.threshold = max(0, min(255, threshold))
        self._apply_transforms()
        return self.current_image

    def auto_contrast(self):
        """自动对比度 - [修复] 修复参数丢失问题"""
        self.auto_contrast_applied = True  # [修复] 设置标记
        self._apply_transforms()  # [修复] 统一通过 _apply_transforms 应用
        return self.current_image

    def sharpen(self):
        """锐化 - [修复] 修复参数丢失问题"""
        self.sharpen_applied = True  # [修复] 设置标记
        self._apply_transforms()  # [修复] 统一通过 _apply_transforms 应用
        return self.current_image

    def denoise(self):
        """轻度降噪"""
        self.current_image = self.current_image.filter(ImageFilter.MedianFilter(size=3))
        return self.current_image

    def _apply_transforms(self):
        """应用所有变换 - [修复] 支持 auto_contrast 和 sharpen"""
        # [修复] 如果有自动对比度标记，直接应用并返回
        if self.auto_contrast_applied:
            self.current_image = ImageOps.autocontrast(self.original_image)
            # 应用其他变换（除了亮度和对比度）
            if self.rotation != 0:
                self.current_image = self.current_image.rotate(
                    -self.rotation, expand=True, fillcolor=(255, 255, 255)
                )
            if self.threshold is not None:
                gray = self.current_image.convert('L')
                self.current_image = gray.point(
                    lambda x: 0 if x < self.threshold else 255, '1'
                ).convert('RGB')
            if self.sharpen_applied:
                self.current_image = self.current_image.filter(ImageFilter.SHARPEN)
            return

        # 标准处理流程
        img = self.original_image.copy()

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

        # 5. [修复] 锐化
        if self.sharpen_applied:
            img = img.filter(ImageFilter.SHARPEN)

        self.current_image = img

    def get_current_image(self) -> Image.Image:
        """获取当前处理后的图像"""
        return self.current_image

    def get_original_image(self) -> Image.Image:
        """获取原始图像"""
        return self.original_image

    def get_params(self) -> dict:
        """获取当前处理参数"""
        return {
            'rotation': self.rotation,
            'brightness': self.brightness,
            'contrast': self.contrast,
            'crop_box': self.crop_box,
            'threshold': self.threshold,
            'auto_contrast_applied': self.auto_contrast_applied,  # [修复]
            'sharpen_applied': self.sharpen_applied,  # [修复]
        }

    def set_params(self, params: dict):
        """设置处理参数"""
        self.rotation = params.get('rotation', 0)
        self.brightness = params.get('brightness', 1.0)
        self.contrast = params.get('contrast', 1.0)
        self.crop_box = params.get('crop_box', None)
        self.threshold = params.get('threshold', None)
        self.auto_contrast_applied = params.get('auto_contrast_applied', False)  # [修复]
        self.sharpen_applied = params.get('sharpen_applied', False)  # [修复]
        self._apply_transforms()
        return self.current_image
