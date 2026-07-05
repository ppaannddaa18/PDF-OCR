"""
PaddleOCR-VL 引擎 — 基于视觉语言模型的智能OCR
GPU加速，整页理解，支持表格/手写/公式
"""
from typing import Optional, Tuple, Dict, List, Any
from PIL import Image
import threading
import time
from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher


class PaddleOCREngine(OCREngineBase):
    """
    PaddleOCR-VL引擎 — 单例

    特性:
    - 整页识别: 一次推理获取全页结构化结果
    - 三级匹配: IoU → 就近 → 关键词
    - GPU常驻: 模型加载后保持常驻，避免重复加载
    - 空闲卸载: 可配置空闲N秒后自动释放GPU显存
    """
    _instance: Optional['PaddleOCREngine'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: dict):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return
            self._config = config
            vl_cfg = config.get("ocr", {}).get("paddleocr_vl", {})
            self._pipeline = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._lock = threading.RLock()
            self._model_name = vl_cfg.get("model_name", "PaddleOCR-VL-1.6-0.9B")
            self._device = vl_cfg.get("device", "gpu")
            self._warmup_on_startup = vl_cfg.get("warmup_on_startup", True)
            self._idle_unload_seconds = vl_cfg.get("idle_unload_seconds", 300)
            self._page_dpi = vl_cfg.get("page_dpi", 200)
            self._matcher = FieldMatcher(config)
            self._last_used_time = time.time()
            self._initialized_flag = True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用，不阻塞GUI）"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                from paddleocr import PaddleOCRVL
                self._pipeline = PaddleOCRVL(model_name=self._model_name)
                self._initialized = True
                self._last_used_time = time.time()

                # 启动预热
                if self._warmup_on_startup:
                    self._warmup()

            except Exception as e:
                self._init_error = str(e)

    def _warmup(self) -> None:
        """预热模型 — 用小图跑一次推理触发CUDA kernel编译"""
        if not self._pipeline:
            return
        try:
            dummy = Image.new("RGB", (64, 64), "white")
            list(self._pipeline.predict(dummy))
        except Exception:
            pass  # 预热失败不影响正常使用

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "paddleocr_vl"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def unload(self) -> None:
        """卸载GPU模型释放显存"""
        with self._lock:
            if self._pipeline is not None:
                del self._pipeline
                self._pipeline = None
                self._initialized = False

    def _ensure_loaded(self) -> None:
        """确保模型已加载（支持空闲后重新加载）"""
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError(f"PaddleOCR-VL初始化失败: {self._init_error}")
        self._last_used_time = time.time()

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """单图识别 — 降级为整页识别后只取第一个匹配"""
        # 创建虚拟region覆盖全图
        class _DummyRegion:
            id = "__single__"
            field_name = "text"
            _pixel_bbox = [0, 0, image.width, image.height]
            match_keywords = []
            match_mode = "value"
            ocr_mode = mode

        results = self.recognize_page(image, [_DummyRegion])
        result = results.get("__single__", ("", 0.0, 0, None))
        return result[0], result[1]

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — PaddleOCR-VL一次推理，FieldMatcher匹配到各region
        """
        self._ensure_loaded()

        # 预处理：为每个region计算像素坐标bbox
        W, H = image.size
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            region._pixel_bbox = [left, top, right, bottom]

        try:
            with self._lock:
                outputs = list(self._pipeline.predict(image))
        except Exception as e:
            # 推理失败，返回空结果
            return {r.id: ("", 0.0, 0, None) for r in regions}

        if not outputs:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # 提取elements和markdown
        output = outputs[0] if isinstance(outputs, list) else outputs
        elements = self._extract_elements(output)
        markdown_text = self._extract_markdown(output)

        # 三级匹配
        match_results = self._matcher.match(elements, regions, markdown_text)

        # 转换为统一格式
        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)

        self._last_used_time = time.time()
        return results

    def _extract_elements(self, output) -> List[dict]:
        """从PaddleOCR-VL输出提取elements列表"""
        if hasattr(output, 'elements'):
            elements = []
            for elem in output.elements:
                elem_dict = {
                    "type": getattr(elem, "type", "text"),
                    "text": getattr(elem, "text", ""),
                    "confidence": getattr(elem, "confidence", 0.0),
                }
                bbox = getattr(elem, "bbox", None)
                if bbox is not None:
                    if hasattr(bbox, 'tolist'):
                        bbox = bbox.tolist()
                    elem_dict["bbox"] = list(bbox)
                elements.append(elem_dict)
            return elements
        elif isinstance(output, dict):
            return output.get("elements", [])
        return []

    def _extract_markdown(self, output) -> str:
        """从PaddleOCR-VL输出提取markdown文本"""
        if hasattr(output, 'markdown'):
            return str(output.markdown)
        elif isinstance(output, dict):
            return output.get("markdown", "")
        return ""

    def get_vram_usage(self) -> Tuple[float, float]:
        """获取GPU显存使用 (used_gb, total_gb) - 需要pynvml"""
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return info.used / 1024**3, info.total / 1024**3
        except Exception:
            return 0.0, 0.0

    def _check_idle_unload(self) -> None:
        """检查是否需要空闲卸载（由定时器调用）"""
        if self._idle_unload_seconds <= 0:
            return
        if not self._initialized:
            return
        elapsed = time.time() - self._last_used_time
        if elapsed > self._idle_unload_seconds:
            self.unload()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance.unload()
                cls._instance = None
