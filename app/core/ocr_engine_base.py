"""
OCR引擎抽象基类
定义所有OCR引擎必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Tuple, Dict, List, Any
from PIL import Image


class OCREngineBase(ABC):
    """OCR引擎抽象基类 — 所有引擎必须实现此接口"""

    @abstractmethod
    def initialize(self) -> None:
        """
        同步初始化引擎，加载模型。
        在后台线程中调用，不阻塞UI。
        调用后 is_ready 应为 True。
        """
        ...

    @abstractmethod
    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """
        识别单张图片。

        Args:
            image: PIL Image对象（可能是裁剪后的区域）
            mode: "general" | "single_line" | "number"

        Returns:
            (识别的文本, 平均置信度 0.0~1.0)
        """
        ...

    @abstractmethod
    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        识别整页图片的多个区域。

        Args:
            image: 整页渲染的PIL Image
            regions: Region对象列表
            page_dpi: 页面渲染DPI

        Returns:
            {region_id: (text, confidence, match_level, raw_element)}
            match_level: 0=未匹配 1=IoU 2=就近 3=关键词
            raw_element: PaddleOCR-VL返回的原始element dict（RapidOCR为None）
        """
        ...

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """引擎是否已初始化完成"""
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """引擎名称: "rapidocr" | "gguf" """
        ...

    @abstractmethod
    def unload(self) -> None:
        """卸载模型释放资源（GGUF 需要，RapidOCR可为空操作）"""
        ...
