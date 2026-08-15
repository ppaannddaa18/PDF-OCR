"""PaddleOCR-VL-1.6 引擎 — 官方管线（paddlex native 本地推理）

官方高层 API：``paddleocr.PaddleOCRVL`` 包装 paddlex ``PaddleOCR-VL-1.6`` 管线
（layout 检测 → 裁剪 → VLM → 结果组装全流程官方实现）。``vl_rec_backend="native"``
= 本地权重直接推理（官方后端枚举之一，无 llama.cpp server）。

Spotting 任务（行级文本 + 坐标）：
- 布局检测下 PP-DocLayoutV3 无 "spotting" 标签 → ``page_has_spotting`` 恒 False；
- 官方唯一路径：``use_layout_detection=False + prompt_label="spotting"`` 把整页作为
  单个 spotting 假布局盒 → VLM 输出 ``<|LOC_n|>`` token → 官方
  ``post_process_for_spotting`` 以整页尺寸还原 → ``rec_polys`` 为整页像素四点坐标
  （与预览面板坐标系一致），坐标还原由官方实现，本引擎不解析 LOC token。

显存（8GB 卡整页 spotting 实测适配）：
- 加载后 ``paddle.device.cuda.empty_cache()`` 释放显存池预分配；
- 459/570 个 fp32 参数（paddlex keep_in_fp32 精度保护）→ bf16 原地转换省 ~1GB
  （逆用官方 dtype 切换手法 _share_data_with，model_utils.py:1349-1353）；
- 官方 spotting 像素上限 1605632（~2090 patches → 全序列 logits 大块分配
  ~3.9GB OOM）→ 运行时替换为配置值（默认 1M，实测 138 行/38.9s/峰值 6.8GB）。

线程安全：native 生成非线程安全，推理加锁（多 worker 并行时排队）。
"""
import logging
import os
import threading
import time
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from PIL import Image

from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher
from app.models.page_result import PageResult, Block

logger = logging.getLogger("PDFOCR")

# 8GB 卡适配：官方 spotting 像素上限 1605632（~2090 patches → 全序列 logits
# 大块分配 ~3.9GB OOM）；1M 实测 138 行/38.9s/峰值 6.8GB 正常
_DEFAULT_SPOTTING_MAX_PIXELS = 1048576
# 官方 spotting 像素上限（paddlex 3.7.2 pipeline.py:339 写死）
_OFFICIAL_SPOTTING_MAX_PIXELS = 1605632
# raw_json 大数组降级阈值：numpy 元素数超过则弃 tolist()（整页图像/逐块图像
# 会展开成数百万数字 → 每页膨胀数百 MB），spotting 坐标数组在阈值内保留
_JSON_SAFE_MAX_NDARRAY_ELEMS = 5000


def _default_model_dir() -> str:
    """默认模型目录探测：配置 → paddlex 官方模型缓存 → HF 缓存"""
    home = os.path.expanduser("~")
    candidates = [
        os.path.join(home, ".paddlex", "official_models", "PaddleOCR-VL-1.6"),
        os.path.join(home, ".cache", "huggingface", "hub",
                     "models--PaddlePaddle--PaddleOCR-VL-1.6", "snapshots"),
    ]
    for c in candidates:
        if os.path.isdir(c):
            if c.endswith("snapshots"):
                subs = [os.path.join(c, s) for s in os.listdir(c) if not s.startswith(".")]
                if subs:
                    return sorted(subs)[-1]
            return c
    return candidates[0]


class PaddleOCRVLEngine(OCREngineBase):
    """PaddleOCR-VL-1.6 官方权重 · 官方管线（paddlex native）本地推理"""

    _instance: Optional['PaddleOCRVLEngine'] = None
    _lock = threading.Lock()

    @classmethod
    def reset_instance(cls):
        """重置单例（用于引擎切换）。

        paddlex 管线内部有循环引用：仅置 ``_instance = None`` 不会及时回收
        模型张量（实测残留 ~4.4GB 活分配，下次 initialize OOM）→ 显式
        gc.collect() + empty_cache()（与 _hard_reset 同序列）。
        """
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.unload()
                except Exception:
                    pass
                cls._instance = None
            try:
                import gc
                import paddle
                gc.collect()
                paddle.device.cuda.empty_cache()
            except Exception:
                pass

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: Optional[dict] = None):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return
            self._config = config or {}
            cfg = self._config.get("ocr", {}).get("paddle_vl", {})
            # model_dir 由 paddlex 官方模型缓存接管（配置键保留兼容探测）
            self._model_dir = cfg.get("model_dir") or _default_model_dir()
            # 生成上限：官方 native 无重复惩罚，greedy 可能进入重复循环跑满
            # 上限（10000 → 实测 ~315s/页）；4096 足够 138 行输出（~1200 token）
            self._max_new_tokens = int(cfg.get("max_new_tokens", 4096))
            # 重复惩罚：native 后端忽略参数，引擎直接注入 generation_config
            # （0/None → 禁用，保持官方 greedy）
            self._repetition_penalty = float(cfg.get("repetition_penalty", 1.1) or 0)
            # 视觉注意力 SDPA（flash）：Windows 默认被官方 Linux 判断挡掉 →
            # eager 全量注意力物化 [1,H,L,L] fp32（峰值 +2.6GB）；
            # 启用后实测峰值 6.4→4.2GB、质量无损（0 → 禁用回 eager）
            self._vision_sdpa = bool(cfg.get("vision_sdpa", 1))
            # 逐块 Spotting（布局切块 + 每块坐标偏移映射）：默认关闭（整页
            # 模式）；表格文档收益有限（表格是单一大块），纯文本文档可省
            # ~25% 时间（实验实测：整页 41s/138 行 vs 逐块 42s/135 行，
            # 内容等价、仅标点风格差异）
            self._block_spotting = bool(cfg.get("block_spotting", 0))
            # 8GB 显存适配：spotting 像素上限（0/None → 官方默认 1605632）
            self._spotting_max_pixels = int(cfg.get("spotting_max_pixels", 0) or 0)
            if not self._spotting_max_pixels:
                self._spotting_max_pixels = _DEFAULT_SPOTTING_MAX_PIXELS
            # 解析配置透传（参考 AI Studio 解析配置弹窗；默认与现状一致，主程序无回归）
            self._use_doc_orientation_classify = bool(cfg.get("use_doc_orientation_classify", 0))
            self._use_doc_unwarping = bool(cfg.get("use_doc_unwarping", 0))
            self._use_chart_recognition = bool(cfg.get("use_chart_recognition", 1))
            self._use_seal_recognition = bool(cfg.get("use_seal_recognition", 1))
            self._use_ocr_for_image_block = bool(cfg.get("use_ocr_for_image_block", 1))
            self._merge_layout_blocks = bool(cfg.get("merge_layout_blocks", 1))
            self._spotting_min_pixels = int(cfg.get("spotting_min_pixels", 0) or 0)
            # 辅助内容过滤标签（markdown_ignore_labels，Task 2 使用）
            self._markdown_ignore_labels = list(cfg.get("markdown_ignore_labels", []) or [])
            self._pipe = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._infer_lock = threading.RLock()
            self._matcher = FieldMatcher(self._config)
            self._initialized_flag = True

    # ── 生命周期 ─────────────────────────────────────────────

    def initialize(self) -> None:
        """同步加载官方管线（后台线程调用）。bf16 权重，~3GB 显存。"""
        if self._initialized:
            return
        with self._infer_lock:
            if self._initialized:
                return
            try:
                # 显存池按需增长，避免预分配峰值（8GB 卡关键）
                os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
                import paddle
                # 创建期 dtype 决定参数精度（bf16 生效，实测验证）
                paddle.set_default_dtype("bfloat16")
                from paddleocr import PaddleOCRVL
                t0 = time.monotonic()
                self._pipe = PaddleOCRVL(
                    pipeline_version="v1.6", vl_rec_backend="native",
                    use_doc_orientation_classify=False, use_doc_unwarping=False)
                # 8GB 卡整页 spotting 显存适配：fp32 参数转 bf16 + 像素上限降低
                self._cast_params_to_bf16(paddle)
                self._patch_spotting_max_pixels()
                self._patch_assemble_spotting_merge()
                self._patch_vision_sdpa()
                paddle.device.cuda.empty_cache()
                self._initialized = True
                logger.info(f"PaddleOCR-VL 官方管线加载完成 "
                            f"({time.monotonic()-t0:.1f}s)")
            except Exception as e:
                logger.error(f"PaddleOCR-VL initialization failed: {e}")
                self._init_error = str(e)

    def unload(self) -> None:
        """释放管线与显存"""
        with self._infer_lock:
            self._pipe = None
            self._initialized = False
            try:
                import paddle
                paddle.device.cuda.empty_cache()
            except Exception:
                pass

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "paddle_vl"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def _ensure_loaded(self) -> None:
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError(f"PaddleOCR-VL 初始化失败: {self._init_error}")

    # ── 8GB 显存适配 ─────────────────────────────────────────

    def _cast_params_to_bf16(self, paddle) -> None:
        """fp32 参数（paddlex keep_in_fp32 精度保护，实测 459/570）→ bf16。

        整页 spotting 显存适配（实测省 ~1GB）。逆用 paddlex 官方 dtype 切换
        手法（model_utils.py:1349-1353）：``param.cast(dtype)`` 产生新参数后
        用 ``_share_data_with`` 原地替换底层数据，逐参数峰值可控。
        探测/转换失败不阻塞加载（回官方行为）。
        """
        try:
            inner = self._pipe.paddlex_pipeline.vl_rec_model.infer
            params = list(inner.parameters())
        except Exception as e:
            logger.warning(f"PaddleOCR-VL 参数探测失败，跳过 bf16 转换: {e}")
            return
        n = 0
        for p in params:
            if p.dtype == paddle.float32:
                try:
                    p_bf16 = p.cast(dtype=paddle.bfloat16)
                    p.value().get_tensor()._share_data_with(
                        p_bf16.value().get_tensor())
                    n += 1
                except Exception as e:
                    logger.warning(
                        f"PaddleOCR-VL 参数 {getattr(p, 'name', '?')} 转换失败: {e}")
        if n:
            logger.info(f"PaddleOCR-VL: {n} 个 fp32 参数已转 bf16（8GB 显存适配）")

    def _patch_spotting_max_pixels(self) -> None:
        """统一 collect：布局块/整页假盒全部走 Spotting + 像素上限适配。

        - 官方写死 ``blk_max_pixels = 1605632``（~8192 patches → 视觉注意力
          fp32 矩阵大块分配 ~3.9GB，8GB 卡 OOM）→ 降为配置值（默认 1M）；
        - 整页假盒（use_layout_detection=False）label 已是 "spotting"；
          布局模式（block_spotting）非 image 块 label 改写 "spotting"
          （assemble 靠标签命中坐标解析）→ 统一函数两模式通用；
        - **双入口替换**：布局单页走 benchmark 装饰的
          ``_paddleocr_vl_collect_block_vlm_inputs``（装饰时已捕获官方原
          函数，只替换 core 不生效——实验实证），须一并替换。
        venv 升级后若官方函数签名变化会在调用侧抛错，配置
        ``ocr.paddle_vl.spotting_max_pixels: 1605632`` 可禁用像素适配
        （但标签改写仍生效，勿用于回退）。
        """
        engine = self  # 闭包捕获引擎引用：辅助过滤集合每次调用读取（配置热生效）
        max_pixels = self._spotting_max_pixels
        if not max_pixels:
            max_pixels = _OFFICIAL_SPOTTING_MAX_PIXELS
        import paddlex.inference.pipelines.paddleocr_vl.pipeline as _vlp

        def _collect(self, page_idx, blocks_for_img, imgs_in_doc_for_img,
                     layout_prep_cfg):
            page_vlm_entries = []
            page_has_spotting = False
            page_drop_figures = set()
            # 辅助内容过滤（识别前）：布局模式原标签命中忽略集 → 不送 VLM。
            # 必须在 label 改写**之前**过滤 —— assemble 阶段标签已被改写为
            # "spotting"，_filter_ignored_blocks（按原标签）永不命中。每次
            # 调用从引擎实例读取（apply_config 热生效，无需重装 patch）；
            # 整页假盒 label "spotting" 不在忽略集，不受影响。
            ignore_labels = set(engine._markdown_ignore_labels)
            for j, block in enumerate(blocks_for_img):
                block_img = block["img"]
                block_label = block["label"]
                if block_label in ignore_labels:
                    continue
                if (block_label not in layout_prep_cfg["image_labels"]
                        and block_img is not None):
                    block["label"] = "spotting"  # 布局块改写；假盒本身已是
                    page_has_spotting = True
                    page_vlm_entries.append(
                        (page_idx, j, _vlp.pre_process_for_spotting(block_img),
                         "Spotting:", (112896, max_pixels), {}))
            return page_vlm_entries, page_has_spotting, page_drop_figures

        _vlp._PaddleOCRVLPipeline._paddleocr_vl_collect_page_vlm_entries_core = (
            _collect)
        _vlp._PaddleOCRVLPipeline._paddleocr_vl_collect_block_vlm_inputs = (
            _collect)
        if max_pixels != _OFFICIAL_SPOTTING_MAX_PIXELS:
            logger.info(f"PaddleOCR-VL: spotting max_pixels → {max_pixels}"
                        "（8GB 显存适配）")

    def _patch_assemble_spotting_merge(self) -> None:
        """assemble 合并版：逐块 spotting 坐标偏移映射 + 页级累积。

        官方 ``_paddleocr_vl_assemble_parsing_results``（paddlex 3.7.2
        pipeline.py:598-602）的 spotting 分支每块解析后 ``spotting_res``
        被覆盖 —— 布局多块时只保留最后一块坐标。基于官方完整函数体复制，
        仅改 spotting 分支：块内 rec_polys（tuple）叠加块 bbox 左上角偏移
        重建为整页坐标，累积合并到页级 spotting_res。整页模式单块时
        等价原行为。venv 升级签名变化会在调用侧抛错（同其他 patch）。
        """
        import paddlex.inference.pipelines.paddleocr_vl.pipeline as _vlp

        def _assemble(self, blocks, batch_dict_by_pixel, id2pixel_key_map,
                      drop_figures_set, vis_image_labels):
            parsing_res_lists = []
            table_res_lists = []
            spotting_res_list = []
            image_path_to_obj_map = {}
            table_blocks = []
            for i, blocks_for_img in enumerate(blocks):
                parsing_res_list = []
                table_res_list = []
                spotting_res = {}
                for j, block in enumerate(blocks_for_img):
                    block_img = block["img"]
                    block_bbox = block["box"]
                    block_label = block["label"]
                    block_content = ""
                    figure_token_map = {}
                    if (i, j) in id2pixel_key_map:
                        pixel_key = id2pixel_key_map[(i, j)]
                        pixel_info = batch_dict_by_pixel[pixel_key]
                        curr_vlm_block_idx = pixel_info["curr_vlm_block_idx"]
                        assert curr_vlm_block_idx < len(
                            pixel_info["vlm_block_ids"]) and pixel_info[
                            "vlm_block_ids"][curr_vlm_block_idx] == (i, j)
                        vl_rec_result = pixel_info["vlm_results"][
                            curr_vlm_block_idx]
                        block_img4vl = pixel_info["images"][curr_vlm_block_idx]
                        figure_token_map = pixel_info["figure_token_maps"][
                            curr_vlm_block_idx]
                        curr_vlm_block_idx += 1
                        pixel_info["curr_vlm_block_idx"] = curr_vlm_block_idx
                        vl_rec_result["image"] = block_img4vl
                        result_str = vl_rec_result.get("result", "")
                        if result_str is None:
                            result_str = ""
                        min_count = 5000 if block_label == "table" else 50
                        result_str = _vlp.truncate_repetitive_content(
                            result_str, min_count=min_count)
                        if ("\\(" in result_str and "\\)" in result_str) or (
                            "\\[" in result_str and "\\]" in result_str
                        ):
                            result_str = result_str.replace("$", "")
                            result_str = (
                                result_str.replace("\\(", " $ ")
                                .replace("\\)", " $")
                                .replace("\\[\\[", "\\[")
                                .replace("\\]\\]", "\\]")
                                .replace("\\[", " $$ ")
                                .replace("\\]", " $$ ")
                            )
                            if block_label == "formula_number":
                                result_str = result_str.replace("$", "")
                        if block_label == "table":
                            html_str = _vlp.convert_otsl_to_html(result_str)
                            if html_str != "":
                                result_str = html_str
                        if block_label == "spotting":
                            h, w = block_img.shape[:2]
                            result_str, block_spot = (
                                _vlp.post_process_for_spotting(result_str, w, h))
                            # 块内坐标 → 整页：叠加块 bbox 左上角偏移
                            # （rec_polys 为 tuple，重建为 list）
                            bx, by = float(block_bbox[0]), float(block_bbox[1])
                            texts = block_spot.get("rec_texts") or []
                            polys = block_spot.get("rec_polys") or []
                            offset_polys = [
                                [[float(pt[0]) + bx, float(pt[1]) + by]
                                 for pt in poly]
                                for poly in polys
                            ]
                            spotting_res.setdefault("rec_texts",
                                                    []).extend(texts)
                            spotting_res.setdefault("rec_polys",
                                                    []).extend(offset_polys)

                        block_content = result_str
                    block_info = _vlp.PaddleOCRVLBlock(
                        label=block_label,
                        bbox=block_bbox,
                        content=block_content,
                        group_id=block.get("group_id", None),
                        polygon_points=block.get("polygon_points", None),
                    )
                    if block_label == "table":
                        table_blocks.append(
                            {
                                "figure_token_map": figure_token_map,
                                "block": block_info,
                            }
                        )
                    if block_label in vis_image_labels and block_img is not None:
                        img_path = _vlp.construct_img_path(
                            block["label"], block["box"])
                        image_path_to_obj_map[img_path] = block_info
                        if img_path not in drop_figures_set:
                            import cv2
                            block_img = cv2.cvtColor(
                                block_img, cv2.COLOR_BGR2RGB)
                            block_info.image = {
                                "path": img_path,
                                "img": Image.fromarray(block_img),
                            }
                        else:
                            continue

                    parsing_res_list.append(block_info)
                    del block_info, block_img
                for blk_info in table_blocks:
                    block = blk_info["block"]
                    figure_token_map = blk_info["figure_token_map"]
                    block.content = _vlp.untokenize_figure_of_table(
                        block.content, figure_token_map, image_path_to_obj_map)
                parsing_res_lists.append(parsing_res_list)
                table_res_lists.append(table_res_list)
                spotting_res_list.append(spotting_res)
                del parsing_res_list, table_res_list, spotting_res

            return parsing_res_lists, table_res_lists, spotting_res_list

        _vlp._PaddleOCRVLPipeline._paddleocr_vl_assemble_parsing_results = (
            _assemble)
        logger.info("PaddleOCR-VL: assemble 合并版已启用（逐块坐标偏移映射）")

    def _patch_repetition_penalty(self, paddle) -> None:
        """注入重复惩罚：打破 greedy 重复循环（315s/页 根因）。

        **已改为 predict 前注入**（见 ``_predict_once``：每次 predict 前写
        ``self._pipe.infer.generation_config``，配置热生效，无需重载）。
        本方法保留不再调用（避免破坏其它外部引用）。

        native 后端忽略 repetition_penalty/temperature/top_p 参数
        （doc_vlm/predictor.py:233-244 仅 warning）→ greedy argmax 进入重复块
        即确定性死循环跑满 max_new_tokens。生成入口
        （generation/utils.py:908 ``generation_config = self.generation_config``
        → :1088 透传 → :474-476 挂 RepetitionPenaltyLogitsProcessor）——
        直接设置实例的 generation_config.repetition_penalty 即生效。
        配置 0/None 禁用（保持官方 greedy）。
        """
        penalty = self._repetition_penalty
        if not penalty or penalty == 1.0:
            return  # 禁用
        try:
            inner = self._pipe.paddlex_pipeline.vl_rec_model.infer
            gc = getattr(inner, "generation_config", None)
            if gc is None:
                logger.warning("PaddleOCR-VL generation_config 缺失，"
                               "跳过重复惩罚注入")
                return
            gc.repetition_penalty = penalty
            logger.info(f"PaddleOCR-VL: repetition_penalty → {penalty}"
                        "（打破 greedy 重复循环）")
        except Exception as e:
            logger.warning(f"PaddleOCR-VL 重复惩罚注入失败: {e}")

    def _patch_vision_sdpa(self) -> None:
        """视觉注意力 SDPA（flash）启用 — 显存峰值 6.4→4.2GB，质量无损。

        官方实现（paddlex 3.7.2 _siglip.py:149-156）仅 Linux 启用 SDPA，
        Windows 恒走 eager 全量注意力：物化 [1,H,L,L] fp32 矩阵 + softmax
        副本（1M 像素 ≈ 3.7GB 瞬时）。paddle 的 SDPA（scaled_dot_product_
        attention）不物化完整矩阵且内部同样 fp32 softmax（精度不变）。
        遍历视觉层强制 ``_supports_sdpa``（实例属性，与官方 Linux 路径
        等效）；实测 138 行/坐标完整/峰值 4.2GB。配置
        ``ocr.paddle_vl.vision_sdpa: 0`` 可禁用回 eager。
        """
        if not self._vision_sdpa:
            return
        try:
            inner = self._pipe.paddlex_pipeline.vl_rec_model.infer
            n = 0
            for mod in inner.sublayers():
                if type(mod).__name__ == "SiglipAttention":
                    mod._supports_sdpa = True
                    n += 1
            if n:
                logger.info(f"PaddleOCR-VL: 视觉注意力 SDPA 已启用（{n} 层，"
                            "显存峰值 6.4→4.2GB）")
        except Exception as e:
            logger.warning(f"PaddleOCR-VL SDPA 启用失败（回 eager）: {e}")

    # ── 识别 ─────────────────────────────────────────────────

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """单图识别（Region 裁剪用）— 官方整页模式 OCR 任务"""
        self._ensure_loaded()
        prompt_label = "spotting" if mode == "detection" else "ocr"
        with self._infer_lock:
            res = self._predict_one(image, prompt_label=prompt_label)
        text = self._result_text(res)
        return (text or "", 0.95 if text else 0.0)

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """整页识别 — 委托 recognize_page_auto，从 blocks 做 FieldMatcher 匹配"""
        self._ensure_loaded()
        W, H = image.size
        pixel_bboxes = {}
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            pixel_bboxes[region.id] = [left, top, right, bottom]

        page_result = self.recognize_page_auto(image)
        if not page_result.blocks:
            return {r.id: ("", 0.0, 0, None) for r in regions}
        elements = _blocks_to_elements(page_result.blocks)
        match_results = self._matcher.match(
            elements, regions, page_result.markdown, pixel_bboxes)
        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)
        return results

    def recognize_page_auto(self, image: Image.Image) -> PageResult:
        """整页 Spotting：行级文本 + 坐标一次生成（官方管线整页模式）。

        返回 PageResult：markdown=按行拼接（供 KeywordExtractor），
        blocks/line_boxes=行级 Block（bbox 为原图像素矩形，官方整页坐标）。
        无坐标时回退纯文本（blocks 空，文本仍可用）。
        """
        self._ensure_loaded()
        W, H = image.size
        t0 = time.monotonic()
        with self._infer_lock:
            res = self._predict_one(
                image, prompt_label="spotting",
                max_new_tokens=self._max_new_tokens)
        res = self._filter_ignored_blocks(res)
        elapsed = (time.monotonic() - t0) * 1000

        spot = res.get("spotting_res") or {}
        texts = spot.get("rec_texts") or []
        polys = spot.get("rec_polys") or []
        blocks = []
        for txt, poly in zip(texts, polys):
            try:
                xs = [float(p[0]) for p in poly]
                ys = [float(p[1]) for p in poly]
                blocks.append(Block(
                    block_type="text", content=str(txt),
                    bbox=[min(xs), min(ys), max(xs), max(ys)],
                    confidence=1.0))
            except (TypeError, ValueError, IndexError):
                # 单行坐标解析失败不影响其余行
                continue
        markdown = "\n".join(str(t) for t in texts) if texts else self._result_text(res)
        logger.info(f"PaddleOCR-VL 页面解析完成: {len(blocks)} lines, "
                    f"{elapsed:.0f}ms")
        # raw_json 副本必须先于 del res 构造（res 持有整页 output_img 等大对象，
        # 转换后的原生列表与原 numpy 数据解耦）
        raw_json = _json_safe(dict(res)) if isinstance(res, dict) else {}
        # 页间清理：结果对象持有整页 output_img（几百 MB），显式释放 +
        # 回收 paddle 池空闲块（多页批次时池不复用膨胀）
        del res
        if blocks:
            import gc
            gc.collect()
        try:
            import paddle
            paddle.device.cuda.empty_cache()
        except Exception:
            pass
        return PageResult(
            blocks=blocks,
            markdown=markdown,
            tables=[],
            raw_json=raw_json,
            image_size=(W, H),
            inference_time_ms=elapsed,
            line_boxes=blocks,
        )

    # ── 内部 ─────────────────────────────────────────────────

    def _predict_one(self, image: Image.Image, prompt_label: str = "ocr",
                     max_new_tokens: Optional[int] = None,
                     _retried: bool = False) -> dict:
        """官方管线整页预测（use_layout_detection=False 整页模式）。

        paddleocr 的 ``predict`` 返回 list（官方实现 paddleocr_vl.py:186），
        取第一个即单页 PaddleOCRVLResult（dict 风格，支持 .get）。

        OOM 自愈：生成路径偶发显存泄漏（greedy 重复循环，实测 ~4.4GB）会
        导致后续页显存不足 → 完整重置引擎（释放池 + 重新加载 ~13s）后
        重试一次；仍失败则上抛（调用方转失败页）。
        """
        try:
            return self._predict_once(image, prompt_label, max_new_tokens)
        except Exception as e:
            if not _retried and _is_oom(e):
                logger.warning(f"PaddleOCR-VL 显存不足，重置引擎后重试: {e}")
                self._hard_reset()
                return self._predict_once(image, prompt_label, max_new_tokens)
            raise

    def _predict_once(self, image: Image.Image, prompt_label: str,
                      max_new_tokens: Optional[int]) -> dict:
        # 跨线程修复：paddle 动态图模式标志是线程本地状态 —— GUI 中 initialize
        # 在 OCR-Init 线程、predict 在 KeywordWorker 线程，预测线程会被误判为
        # 静态图模式（int(Tensor) is not supported in static graph mode，
        # 实测 GUI 提取失败）→ 调用线程强制动态图模式
        try:
            import paddle
            paddle.disable_static()
        except Exception:
            pass
        # 重复抑制热生效：每次 predict 前注入 generation_config（native 后端
        # 忽略重复惩罚参数，需直接写 generation_config；0/None/1.0 → 不写，
        # 保持官方 1.0 —— 生成链仅在 penalty!=1.0 时挂
        # RepetitionPenaltyLogitsProcessor，penalty=0 会抛 ValueError）。
        # 生产对象图：PaddleOCRVL 无 infer 属性，管线在
        # self._pipe.paddlex_pipeline.vl_rec_model.infer 下（与
        # _cast_params_to_bf16/_patch_vision_sdpa 同路径）
        penalty = self._repetition_penalty
        if penalty and penalty != 1.0:
            try:
                gen = self._pipe.paddlex_pipeline.vl_rec_model.infer.\
                    generation_config
                if getattr(gen, "repetition_penalty", None) != penalty:
                    gen.repetition_penalty = penalty
            except Exception:
                pass
        arr = np.array(image.convert("RGB"))
        kwargs: dict = {}
        if max_new_tokens is not None:
            kwargs["max_new_tokens"] = max_new_tokens
        # 解析配置透传（AI Studio 解析配置弹窗对齐；默认与现状一致）
        kwargs.update({
            "use_doc_orientation_classify": self._use_doc_orientation_classify,
            "use_doc_unwarping": self._use_doc_unwarping,
            "use_chart_recognition": self._use_chart_recognition,
            "use_seal_recognition": self._use_seal_recognition,
            "use_ocr_for_image_block": self._use_ocr_for_image_block,
            "merge_layout_blocks": self._merge_layout_blocks,
        })
        # 逐块模式（block_spotting）：布局切块 + 每块 Spotting（坐标已在
        # assemble 合并版映射回整页）；默认整页假盒模式
        results = self._pipe.predict(
            arr,
            use_layout_detection=bool(self._block_spotting),
            prompt_label=prompt_label,
            **kwargs,
        )
        if not results:
            raise RuntimeError("PaddleOCR-VL 无输出（模型推理失败）")
        return results[0]

    def _hard_reset(self) -> None:
        """OOM 自愈：完整释放管线（参数张量销毁 → 池回收）并重新加载"""
        with self._infer_lock:
            self._pipe = None
            self._initialized = False
            try:
                import gc
                import paddle
                gc.collect()
                paddle.device.cuda.empty_cache()
            except Exception:
                pass
        self.initialize()

    @staticmethod
    def _result_text(res: dict) -> str:
        """结果纯文本：spotting rec_texts 行拼接，或 parsing_res_list 内容拼接"""
        spot = res.get("spotting_res") or {}
        texts = spot.get("rec_texts") or []
        if texts:
            return "\n".join(str(t) for t in texts)
        blocks = res.get("parsing_res_list") or []
        lines = [str(b.content) for b in blocks if b and getattr(b, "content", "")]
        return "\n".join(lines)

    def _filter_ignored_blocks(self, res: dict) -> dict:
        """辅助内容过滤：parsing_res_list 中 label 命中忽略集的块剔除。

        真实 paddlex 3.7.2 ``PaddleOCRVLBlock`` 属性为 ``label``（非
        ``block_label``），同时兼容旧属性（``getattr`` 双属性兜底）；
        等价 paddlex markdown_ignore_labels 语义；整页 spotting 行不受影响。
        """
        ignore = set(self._markdown_ignore_labels)
        if not ignore:
            return res
        res = dict(res)
        blocks = res.get("parsing_res_list") or []
        kept = [b for b in blocks
                if not ((getattr(b, "label", None)
                         or getattr(b, "block_label", None)) in ignore)]
        res["parsing_res_list"] = kept
        return res

    # ── 配置热生效（解析配置弹窗） ─────────────────────────────

    def apply_config(self, patch: dict) -> None:
        """解析配置弹窗热生效：更新实例属性（缺失键保持不变）。

        类型转换与 __init__ 一致（float/bool/int/list）；识别参数
        （_predict_once kwargs、_filter_ignored_blocks、_collect 闭包辅助
        过滤）均从实例属性读取 → 应用后即时生效，无需重启管线。注意：
        _collect 闭包内的 spotting 像素上限为 patch 安装时快照（同
        max_pixels 既有语义），spotting_max_pixels 改动需重新加载管线生效。
        """
        cfg = (patch or {}).get("ocr", {}).get("paddle_vl", {})
        if not cfg:
            return
        if "repetition_penalty" in cfg:
            self._repetition_penalty = float(cfg.get("repetition_penalty") or 0)
        if "markdown_ignore_labels" in cfg:
            self._markdown_ignore_labels = list(
                cfg.get("markdown_ignore_labels") or [])
        for key, attr in (
            ("use_doc_orientation_classify", "_use_doc_orientation_classify"),
            ("use_doc_unwarping", "_use_doc_unwarping"),
            ("use_chart_recognition", "_use_chart_recognition"),
            ("use_seal_recognition", "_use_seal_recognition"),
            ("use_ocr_for_image_block", "_use_ocr_for_image_block"),
            ("merge_layout_blocks", "_merge_layout_blocks"),
            ("block_spotting", "_block_spotting"),
        ):
            if key in cfg:
                setattr(self, attr, bool(cfg[key]))
        if "spotting_min_pixels" in cfg:
            self._spotting_min_pixels = int(cfg.get("spotting_min_pixels") or 0)
        if "spotting_max_pixels" in cfg:
            v = int(cfg.get("spotting_max_pixels") or 0)
            self._spotting_max_pixels = v or _DEFAULT_SPOTTING_MAX_PIXELS


def _is_oom(exc: Exception) -> bool:
    """ResourceExhaustedError（paddle OOM）判定"""
    msg = str(exc)
    return "Out of memory" in msg or "ResourceExhaustedError" in msg


def _blocks_to_elements(blocks: List[Block]) -> List[dict]:
    """Block[] → FieldMatcher 兼容的 elements dict 格式"""
    return [
        {
            "type": b.block_type,
            "text": b.content,
            "confidence": b.confidence,
            "bbox": b.bbox if b.bbox != [0, 0, 0, 0] else None,
        }
        for b in blocks
    ]


def _json_safe(obj):
    """递归转 JSON 可序列化：numpy/paddle Tensor/DataFrame → 原生/字符串

    大数组降级：numpy 数组元素数 > 5000 不 tolist()（整页 output_img/逐块
    img 会展开成数百万数字 → raw_json 每页膨胀数百 MB），降级为紧凑描述
    ``{"__ndarray__": [shape...], "dtype": ...}``。spotting 的 rec_polys
    生产为 list-of-list（官方 post_process_for_spotting 构造），不走 numpy
    分支不受影响；(300,4,2) 2400 元素坐标数组仍在阈值内完整 tolist()。
    paddlex Block 统一映射为官方 ``_to_json`` 结构
    ``{"block_label", "block_content", "block_bbox"}``。
    """
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, np.ndarray):
        if obj.size > _JSON_SAFE_MAX_NDARRAY_ELEMS:
            return {"__ndarray__": [int(s) for s in obj.shape],
                    "dtype": str(obj.dtype)}
        return obj.tolist()
    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:
            pass
    if hasattr(obj, "label") or hasattr(obj, "block_label"):  # paddlex Block
        # 真实 paddlex 3.7.2 属性为 label/content/bbox；旧对象仅 block_label
        # （label 缺失/为空时 block_label 兜底）→ 统一映射官方 _to_json 结构
        return _json_safe({"block_label": getattr(obj, "label", None)
                           or getattr(obj, "block_label", None),
                           "block_content": getattr(obj, "content", ""),
                           "block_bbox": getattr(obj, "bbox", [])})
    return str(obj)
