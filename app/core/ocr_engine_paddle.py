"""
PaddleOCR-VL 引擎 — 基于视觉语言模型的智能OCR
GPU加速，整页理解，支持表格/手写/公式
"""
from typing import Optional, Tuple, Dict, List, Any
import logging
from PIL import Image
import numpy as np
import threading
import time
from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher
from app.core.layout_extractor import extract_blocks, extract_markdown, extract_raw_json
from app.core.table_extractor import extract_tables
from app.models.page_result import PageResult, Block

logger = logging.getLogger("PDFOCR")


def _blocks_to_elements(blocks: List[Block]) -> List[dict]:
    """将 Block[] 转换为 FieldMatcher 兼容的 elements dict 格式"""
    return [
        {
            "type": b.block_type,
            "text": b.content,
            "confidence": b.confidence,
            "bbox": b.bbox if b.bbox != [0, 0, 0, 0] else None,
        }
        for b in blocks
    ]


class _DummyRegion:
    """虚拟Region用于单图识别（recognize方法）"""
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
            self._use_layout_detection = vl_cfg.get("use_layout_detection", True)
            self._warmup_on_startup = vl_cfg.get("warmup_on_startup", True)
            self._max_new_tokens = vl_cfg.get("max_new_tokens", 2048)
            self._min_pixels = vl_cfg.get("min_pixels", 512 * 512)
            self._use_tensorrt = vl_cfg.get("use_tensorrt", False)
            self._enable_hpi = vl_cfg.get("enable_hpi", False)
            # vlm_extra_args: 按元素类型分级分辨率
            vlm_res_cfg = vl_cfg.get("vlm_resolution", {})
            self._vlm_extra_args = {
                "ocr_min_pixels": vlm_res_cfg.get("text", {}).get("min_pixels", 262144),
                "ocr_max_pixels": vlm_res_cfg.get("text", {}).get("max_pixels", 1048576),
                "table_min_pixels": vlm_res_cfg.get("table", {}).get("min_pixels", 524288),
                "table_max_pixels": vlm_res_cfg.get("table", {}).get("max_pixels", 4194304),
                "formula_min_pixels": vlm_res_cfg.get("formula", {}).get("min_pixels", 524288),
                "formula_max_pixels": vlm_res_cfg.get("formula", {}).get("max_pixels", 4194304),
                "chart_min_pixels": vlm_res_cfg.get("chart", {}).get("min_pixels", 524288),
                "chart_max_pixels": vlm_res_cfg.get("chart", {}).get("max_pixels", 4194304),
                "seal_min_pixels": vlm_res_cfg.get("seal", {}).get("min_pixels", 65536),
                "seal_max_pixels": vlm_res_cfg.get("seal", {}).get("max_pixels", 262144),
            }
            self._idle_unload_seconds = vl_cfg.get("idle_unload_seconds", 300)
            self._page_dpi = vl_cfg.get("page_dpi", 200)
            self._max_vram_gb = vl_cfg.get("max_vram_gb", 7.0)    # VRAM用量上限
            self._min_free_vram_gb = vl_cfg.get("min_free_vram_gb", 0.5)  # 最小保留显存
            self._matcher = FieldMatcher(config)
            self._last_used_time = time.monotonic()
            self._nvml_initialized = False
            self._nvml_handle = None
            self._initialized_flag = True

    def _build_paddlex_config(self):
        """
        构建 PaddleX 配置，控制模型加载。

        关键: PaddleOCRVL.__init__ 的 use_layout_detection 参数不会阻止模型加载，
        PP-DocLayoutV3 (~2.5GB) 始终被加载。通过 paddlex_config 传入修改后的
        完整配置，从 SubModules 中移除 LayoutDetection 才能省下这 2.5GB。
        """
        try:
            from paddlex.inference import load_pipeline_config

            config = load_pipeline_config("PaddleOCR-VL-1.6")
            # AttrDict → 普通 dict，递归转换
            def _to_dict(obj):
                if hasattr(obj, "items"):
                    return {k: _to_dict(v) for k, v in obj.items()}
                elif isinstance(obj, list):
                    return [_to_dict(v) for v in obj]
                return obj

            config = _to_dict(config)
            config["use_layout_detection"] = self._use_layout_detection

            if not self._use_layout_detection:
                submodules = config.get("SubModules", {})
                submodules.pop("LayoutDetection", None)
                if submodules:
                    config["SubModules"] = submodules
                else:
                    config.pop("SubModules", None)
                logger.info("LayoutDetection 模型已从 pipeline 配置中移除，省 ~2.5GB 显存")
            return config
        except Exception as e:
            logger.warning(f"构建 paddlex_config 失败，使用默认配置: {e}")
            return None

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用，不阻塞GUI）"""
        if self._initialized:
            return
        with self._pipeline_lock:
            if self._initialized:
                return
            try:
                logger.info(f"PaddleOCR-VL 开始创建 pipeline (device={self._device}, precision={self._precision}, engine=paddle_dynamic)...")
                from paddleocr import PaddleOCRVL
                import paddle
                paddle.set_device(self._device)
                # GPU显存优化: auto_growth 按需分配（env vars 可能未生效时兜底）
                if self._device != "cpu":
                    try:
                        paddle.device.cuda.set_allocator_strategy("auto_growth")
                        logger.info("PaddlePaddle CUDA allocator: auto_growth")
                    except Exception:
                        pass  # 旧版 PaddlePaddle 不支持，依赖环境变量 FLAGS_allocator_strategy
                # 构建 paddlex_config，控制子模块加载
                paddlex_config = self._build_paddlex_config()
                self._pipeline = PaddleOCRVL(
                    vl_rec_model_name=self._model_name,
                    device=self._device,
                    precision=self._precision,
                    engine="paddle_dynamic",       # 跳过@to_static编译，修复int(Variable)崩溃
                    use_layout_detection=self._use_layout_detection,
                    use_tensorrt=self._use_tensorrt,
                    enable_hpi=self._enable_hpi,
                    paddlex_config=paddlex_config,  # 传入修改后的配置控制模型加载
                )
                logger.info("PaddleOCR-VL pipeline 创建完成")
                self._initialized = True
                self._last_used_time = time.monotonic()

                # 启动预热
                if self._warmup_on_startup:
                    self._warmup()

            except Exception as e:
                logger.error(f"PaddleOCR-VL 初始化失败: {e}")
                self._init_error = str(e)

    def _warmup(self) -> None:
        """预热模型 — 用小图跑一次推理触发CUDA kernel编译"""
        if not self._pipeline:
            return
        try:
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            list(self._pipeline.predict(dummy, temperature=0))
            self._post_inference_cleanup()
        except Exception:
            pass  # 预热失败不影响正常使用

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "paddleocr_vl_cpu" if self._device == "cpu" else "paddleocr_vl"

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
        # NVML 保持初始化，进程退出时自动清理
        # 注意: 不调用 pynvml.nvmlShutdown()，因为它是进程全局操作，
        # 会破坏 PaddlePaddle 内部依赖的 NVML 状态，导致 Place(undefined:0) 崩溃

    def _ensure_loaded(self) -> None:
        """确保模型已加载（支持空闲后重新加载）"""
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError(f"PaddleOCR-VL初始化失败: {self._init_error}")
        self._last_used_time = time.monotonic()

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """单图识别 — 降级为整页识别后只取第一个匹配"""
        # 创建虚拟region覆盖全图
        results = self.recognize_page(image, [_DummyRegion(image.width, image.height, mode)])
        result = results.get("__single__", ("", 0.0, 0, None))
        return result[0], result[1]

    def recognize_page_auto(self, image: Image.Image) -> PageResult:
        """
        整页自动解析 — PaddleOCR-VL模式专用。
        利用pipeline的版面检测+VLM识别，返回结构化PageResult。
        """
        t0 = time.monotonic()
        W, H = image.size

        # VRAM守卫
        max_px = self._vram_guard(image.size)
        if max_px < 0:
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        try:
            arr = np.array(image) if isinstance(image, Image.Image) else image
            with self._pipeline_lock:
                self._ensure_loaded()
                if self._pipeline is None:
                    raise RuntimeError("Pipeline was unloaded after initialization")
                outputs = list(self._pipeline.predict(
                    arr,
                    temperature=0,
                    max_pixels=max_px,
                    min_pixels=self._min_pixels,
                    max_new_tokens=self._max_new_tokens,
                    vlm_extra_args=self._vlm_extra_args,
                ))
                self._last_used_time = time.monotonic()
            self._post_inference_cleanup()
        except Exception as e:
            logger.error(f"PaddleOCR-VL推理失败: {e}")
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        if not outputs:
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        output = outputs[0] if isinstance(outputs, list) else outputs

        # 提取
        blocks = extract_blocks(output)
        md = extract_markdown(output)
        raw = extract_raw_json(output)
        tables = extract_tables(md)

        elapsed = (time.monotonic() - t0) * 1000
        return PageResult(
            blocks=blocks,
            markdown=md,
            tables=tables,
            raw_json=raw,
            image_size=(W, H),
            inference_time_ms=elapsed,
        )

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — 委托给 recognize_page_auto，从 PageResult.blocks 做 FieldMatcher 匹配。
        保留三级匹配（IoU/就近/关键词）行为不变。
        """
        W, H = image.size

        # 为每个 region 计算像素坐标
        pixel_bboxes = {}
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            pixel_bboxes[region.id] = [left, top, right, bottom]

        # 调用 auto 路径获取统一的 Block[] + Markdown（复用一次推理）
        page_result = self.recognize_page_auto(image)

        if not page_result.blocks:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # Block → elements dict 格式（供 FieldMatcher 消费）
        elements = _blocks_to_elements(page_result.blocks)

        # 三级匹配
        match_results = self._matcher.match(elements, regions, page_result.markdown, pixel_bboxes)

        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)

        return results

    def _calc_max_pixels(self, image_size: Tuple[int, int]) -> int:
        """根据图片尺寸计算 max_pixels，上限 8M（8GB 显卡安全），下限 0.5M"""
        w, h = image_size
        actual_pixels = w * h
        return max(min(actual_pixels, 8 * 1024 * 1024), 512 * 1024)

    def _vram_guard(self, image_size: Tuple[int, int]) -> int:
        """VRAM守卫：返回安全的 max_pixels，-1 表示应跳过推理"""
        max_px = self._calc_max_pixels(image_size)
        free_vram = self._get_free_vram_gb()
        if free_vram < self._min_free_vram_gb:
            logger.warning(f"VRAM不足 ({free_vram:.2f}GB < {self._min_free_vram_gb}GB)，跳过推理")
            return -1
        elif free_vram < 1.0:
            max_px = min(max_px, 2 * 1024 * 1024)
            logger.info(f"VRAM紧张 ({free_vram:.2f}GB)，降低分辨率到 {max_px/1e6:.1f}M 像素")
        return max_px

    def _post_inference_cleanup(self) -> None:
        """推理后释放 CUDA 临时缓存（CPU 模式下安全跳过）"""
        try:
            import paddle
            paddle.device.cuda.empty_cache()
        except (OSError, RuntimeError, AttributeError):
            pass  # CPU 模式或 Paddle 未加载时安全跳过

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

    def _get_free_vram_gb(self) -> float:
        """获取可用显存 (GB)，用于VRAM预算检查"""
        self._init_nvml()
        if self._nvml_handle is None:
            return 999.0  # 无法获取时返回大值，不阻止推理
        try:
            import pynvml
            info = pynvml.nvmlDeviceGetMemoryInfo(self._nvml_handle)
            return (info.total - info.used) / 1024**3
        except Exception:
            return 999.0

    def _check_idle_unload(self) -> None:
        """检查是否需要空闲卸载（由定时器调用，加锁保证原子性）"""
        if self._idle_unload_seconds <= 0:
            return
        with self._pipeline_lock:
            if not self._initialized:
                return
            elapsed = time.monotonic() - self._last_used_time
            if elapsed > self._idle_unload_seconds:
                self.unload()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance.unload()
                cls._instance = None
