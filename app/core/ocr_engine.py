"""
OCR引擎 - 性能优化版
- 线程安全的单例模式
- 异步初始化与预热机制
- 细粒度锁优化
"""
from typing import Optional, Tuple
from PIL import Image
import numpy as np
import threading
from concurrent.futures import Future
from app.utils.image_utils import preprocess_for_ocr


class OCREngine:
    """
    OCR引擎单例类 - 线程安全

    性能优化：
    1. 双重检查锁定单例模式
    2. 使用RLock避免死锁
    3. 异步初始化不阻塞UI
    4. 支持预热机制
    """
    _instance: Optional['OCREngine'] = None
    _lock = threading.Lock()  # 类级锁，保护单例创建

    def __new__(cls, *args, **kwargs):
        # 双重检查锁定单例模式
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, lang: str = "ch", use_gpu: bool = False, use_angle_cls: bool = True):
        # 使用标志位避免重复初始化
        if hasattr(self, "_initialized_flag"):
            return

        with getattr(self.__class__, '_lock', threading.Lock()):
            if hasattr(self, "_initialized_flag"):
                return

            # 延迟初始化属性
            self._ocr = None
            self._initialized = False
            self._loading = False
            self._init_error: Optional[str] = None
            self._ocr_lock = threading.RLock()  # 使用RLock支持重入
            self._lang = lang
            self._use_gpu = use_gpu
            self._use_angle_cls = use_angle_cls
            self._init_future: Optional[Future] = None
            self._initialized_flag = True

    def initialize_async(self, callback=None) -> None:
        """
        异步初始化OCR引擎，不阻塞UI

        优化：
        - 使用Future跟踪初始化状态
        - 支持回调通知
        """
        if self._initialized:
            if callback:
                callback()
            return

        if self._loading:
            # 已在加载中，注册回调等待
            if callback and self._init_future:
                def wait_and_callback(future):
                    future.result()
                    callback()
                threading.Thread(target=wait_and_callback, args=(self._init_future,), daemon=True).start()
            return

        self._loading = True
        self._init_error = None

        def _load():
            try:
                # 延迟导入重型模块
                from rapidocr_onnxruntime import RapidOCR

                # RapidOCR 默认使用 PP-OCRv4 模型
                self._ocr = RapidOCR()
                self._initialized = True
                self._init_error = None

                # 预热模型（执行一次空推理）
                self._warmup()

            except Exception as e:
                self._init_error = str(e)
            finally:
                self._loading = False
                if callback:
                    callback()

        thread = threading.Thread(target=_load, daemon=True, name="OCR-Init")
        thread.start()

    def _warmup(self) -> None:
        """
        预热OCR模型 - 执行一次小尺寸推理以加载所有懒加载资源
        """
        if not self._ocr:
            return
        try:
            # 创建1x1最小图像进行预热
            dummy_img = np.zeros((10, 10, 3), dtype=np.uint8)
            self._ocr(dummy_img)
        except Exception:
            pass  # 预热失败不影响正常使用

    def initialize_sync(self) -> None:
        """同步初始化OCR引擎（用于后台线程中调用）"""
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

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """
        执行OCR识别

        Args:
            image: PIL图像对象
            mode: OCR模式 (general/single_line/number)

        Returns:
            (识别文本, 平均置信度)

        性能优化：
        - 预处理在锁外执行
        - 仅推理部分加锁
        """
        if not self._initialized:
            if self._init_error:
                raise RuntimeError(f"OCR引擎初始化失败: {self._init_error}")
            raise RuntimeError("OCR引擎未初始化，请先调用 initialize_async() 或 initialize_sync()")

        # 预处理在锁外执行，减少锁持有时间
        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)

        # 仅推理部分加锁
        with self._ocr_lock:
            if self._ocr is None:
                raise RuntimeError("OCR引擎未正确初始化")
            result, elapse = self._ocr(arr)

        # 结果解析在锁外执行
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

    @classmethod
    def reset_instance(cls) -> None:
        """重置单例实例（用于测试或重新初始化）"""
        with cls._lock:
            if cls._instance is not None:
                cls._instance = None
