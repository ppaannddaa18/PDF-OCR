"""
PaddleOCR-VL 引擎 — 基于视觉语言模型的智能OCR
GPU加速，整页理解，支持表格/手写/公式
"""
from typing import Optional, Tuple, Dict, List, Any
import logging
from PIL import Image
import threading
import time
from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher

logger = logging.getLogger("PDFOCR")


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
            self._pipeline_lock = threading.RLock()
            self._model_name = vl_cfg.get("vl_rec_model_name", "PaddleOCR-VL-1.6-0.9B")
            self._device = vl_cfg.get("device", "gpu:0")
            self._precision = vl_cfg.get("precision", "fp16")
            self._warmup_on_startup = vl_cfg.get("warmup_on_startup", True)
            self._idle_unload_seconds = vl_cfg.get("idle_unload_seconds", 300)
            self._page_dpi = vl_cfg.get("page_dpi", 200)
            self._matcher = FieldMatcher(config)
            self._last_used_time = time.time()
            self._nvml_initialized = False
            self._nvml_handle = None
            self._initialized_flag = True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用，不阻塞GUI）"""
        if self._initialized:
            return
        with self._pipeline_lock:
            if self._initialized:
                return
            try:
                from paddleocr import PaddleOCRVL
                self._pipeline = PaddleOCRVL(
                    vl_rec_model_name=self._model_name,
                    device=self._device,
                    precision=self._precision,
                    use_layout_detection=True,
                )
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
            list(self._pipeline.predict(dummy, temperature=0))
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
        with self._pipeline_lock:
            if self._pipeline is not None:
                del self._pipeline
                self._pipeline = None
                self._initialized = False
        # I2: shutdown NVML on unload
        if self._nvml_initialized:
            try:
                import pynvml
                pynvml.nvmlShutdown()
            except Exception:
                pass
            self._nvml_initialized = False
            self._nvml_handle = None

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
            __slots__ = ('id', 'field_name', 'x', 'y', 'w', 'h',
                         '_pixel_bbox', 'match_keywords', 'match_mode', 'ocr_mode')

            def __init__(self, width, height, mode="general"):
                self.id = "__single__"
                self.field_name = "text"
                self.x = 0.0
                self.y = 0.0
                self.w = 1.0
                self.h = 1.0
                self._pixel_bbox = [0, 0, width, height]
                self.match_keywords = []
                self.match_mode = "value"
                self.ocr_mode = mode

        results = self.recognize_page(image, [_DummyRegion(image.width, image.height, mode)])
        result = results.get("__single__", ("", 0.0, 0, None))
        return result[0], result[1]

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — PaddleOCR-VL一次推理，FieldMatcher匹配到各region
        """
        self._ensure_loaded()

        # 为每个region计算像素坐标（不修改原region对象，避免多线程竞态）
        W, H = image.size
        pixel_bboxes = {}
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            pixel_bboxes[region.id] = [left, top, right, bottom]

        try:
            with self._pipeline_lock:
                max_px = self._calc_max_pixels(image.size)
                outputs = list(self._pipeline.predict(
                    image,
                    temperature=0,
                    max_pixels=max_px,
                ))
        except Exception as e:
            logger.error(f"PaddleOCR-VL推理失败: {e}")
            return {r.id: ("", 0.0, 0, None) for r in regions}

        if not outputs:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # 提取elements和markdown
        output = outputs[0] if isinstance(outputs, list) else outputs
        elements = self._extract_elements(output)
        markdown_text = self._extract_markdown(output)

        # 三级匹配（传入像素坐标字典，避免修改共享region对象）
        match_results = self._matcher.match(elements, regions, markdown_text, pixel_bboxes)

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

    def _calc_max_pixels(self, image_size: Tuple[int, int]) -> int:
        """根据图片尺寸计算 max_pixels，防止高DPI导致GPU OOM"""
        w, h = image_size
        actual_pixels = w * h
        # 上限 16M 像素（约 4000x4000），防止 GPU OOM；下限 1M
        return max(min(actual_pixels, 16 * 1024 * 1024), 1024 * 1024)

    def _extract_elements(self, output) -> List[dict]:
        """从 PaddleOCR-VL Result 对象提取 elements 列表

        官方 Result 对象结构:
        - .json -> dict 含 overall_ocr_res (dt_polys, rec_texts, rec_scores)
                            + parsing_res_list (block_bbox, block_label, block_content)
        - .markdown -> dict 含 markdown_texts
        """
        elements = []
        try:
            data = output.json if hasattr(output, 'json') else (output if isinstance(output, dict) else {})

            # 从 overall_ocr_res 提取文字 + 四点坐标 + 置信度
            ocr_res = data.get("overall_ocr_res", {})
            rec_texts = ocr_res.get("rec_texts", [])
            rec_scores = ocr_res.get("rec_scores", [])
            dt_polys = ocr_res.get("dt_polys", [])

            for i, text in enumerate(rec_texts):
                if not text or not text.strip():
                    continue
                bbox = None
                if i < len(dt_polys):
                    poly = dt_polys[i]
                    # dt_polys = [[x1,y1],[x2,y2],[x3,y3],[x4,y4]]
                    if len(poly) >= 4:
                        xs = [p[0] for p in poly]
                        ys = [p[1] for p in poly]
                        bbox = [min(xs), min(ys), max(xs), max(ys)]

                confidence = rec_scores[i] if i < len(rec_scores) else 0.0
                elements.append({
                    "type": "text",
                    "text": text,
                    "confidence": float(confidence),
                    "bbox": bbox,
                })

            # 从 parsing_res_list 提取表格/公式等结构化元素
            for item in data.get("parsing_res_list", []):
                block_label = item.get("block_label", "")
                if block_label in ("table", "formula"):
                    content = item.get("block_content", "")
                    coord = item.get("block_bbox", None)
                    elements.append({
                        "type": block_label,
                        "text": content if isinstance(content, str) else str(content),
                        "confidence": 0.95,
                        "bbox": coord,
                    })

        except Exception:
            pass
        return elements

    def _extract_markdown(self, output) -> str:
        """从 PaddleOCR-VL Result 对象提取 markdown 文本"""
        try:
            md = output.markdown if hasattr(output, 'markdown') else {}
            if isinstance(md, dict):
                texts = md.get("markdown_texts", [])
                return "\n\n".join(texts) if texts else ""
            return str(md) if md else ""
        except Exception:
            return ""

    def _init_nvml(self) -> None:
        """惰性初始化NVML并查找最大显存的GPU（I2+I3）"""
        if self._nvml_initialized:
            return
        try:
            import pynvml
            pynvml.nvmlInit()
            self._nvml_initialized = True
            count = pynvml.nvmlDeviceGetCount()
            best_handle = None
            best_mem = 0
            for i in range(count):
                h = pynvml.nvmlDeviceGetHandleByIndex(i)
                info = pynvml.nvmlDeviceGetMemoryInfo(h)
                if info.total > best_mem:
                    best_mem = info.total
                    best_handle = h
            self._nvml_handle = best_handle
        except Exception:
            self._nvml_initialized = False
            self._nvml_handle = None

    def get_vram_usage(self) -> Tuple[float, float]:
        """获取GPU显存使用 (used_gb, total_gb) - 需要pynvml"""
        self._init_nvml()
        if self._nvml_handle is None:
            return 0.0, 0.0
        try:
            import pynvml
            info = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
            return info.used / 1024**3, info.total / 1024**3
        except Exception:
            return 0.0, 0.0

    def _check_idle_unload(self) -> None:
        """检查是否需要空闲卸载（由定时器调用，加锁保证原子性）"""
        if self._idle_unload_seconds <= 0:
            return
        with self._pipeline_lock:
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
