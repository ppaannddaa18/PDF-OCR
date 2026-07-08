"""
OCR引擎工厂 — 根据配置返回对应引擎实例
"""
from typing import Optional
from app.core.ocr_engine_base import OCREngineBase


def get_ocr_engine(config: dict) -> OCREngineBase:
    """
    根据配置创建OCR引擎实例。

    config["ocr"]["engine"]:
        "paddleocr_vl" → PaddleOCREngine（GPU，主引擎）
        "rapidocr"     → RapidOCREngine（CPU，降级备用）

    如果 PaddleOCREngine 导入失败（环境未安装PaddlePaddle），
    自动降级到 RapidOCREngine。
    """
    engine_type = config.get("ocr", {}).get("engine", "rapidocr")

    if engine_type in ("paddleocr_vl", "paddleocr_vl_cpu"):
        try:
            # 在 PaddlePaddle 导入前设置内存分配策略（进程级，必须在首次 import paddle 之前）
            import os
            if engine_type == "paddleocr_vl":
                os.environ.setdefault("FLAGS_allocator_strategy", "auto_growth")
                # 显存上限 = max_vram_gb，留 10% 余量给其他进程
                vl_cfg_pre = config.get("ocr", {}).get("paddleocr_vl", {})
                max_vram = vl_cfg_pre.get("max_vram_gb", 7.8)
                memory_limit_mb = int(max_vram * 1024 * 0.9)
                os.environ.setdefault("FLAGS_gpu_memory_limit_mb", str(memory_limit_mb))

            # 预检：确认 PaddleOCR 实际可导入
            import paddleocr  # noqa: F401
            from app.core.ocr_engine_paddle import PaddleOCREngine
            vl_cfg = dict(config.get("ocr", {}).get("paddleocr_vl", {}))
            if engine_type == "paddleocr_vl_cpu":
                # CPU模式：覆盖device配置（质量相同，0显存，较慢）
                vl_cfg["device"] = "cpu"
                vl_cfg["precision"] = "fp32"
            else:
                # GPU模式：显式设置，防止之前CPU模式切换残留的配置污染
                vl_cfg["device"] = "gpu:0"
                vl_cfg["precision"] = "fp16"
            # 创建独立副本，不修改原始 config
            config = dict(config)
            config["ocr"] = dict(config.get("ocr", {}))
            config["ocr"]["paddleocr_vl"] = vl_cfg
            return PaddleOCREngine(config)
        except ImportError as e:
            import logging
            logging.getLogger("PDFOCR").warning(
                f"PaddleOCR-VL不可用 ({e})，降级到RapidOCR"
            )
            # 自动降级
            from app.core.ocr_engine_rapid import RapidOCREngine
            ocr_config = config.get("ocr", {})
            rapid_config = ocr_config.get("rapidocr", {})
            return RapidOCREngine(
                lang=rapid_config.get("lang", "ch"),
                use_gpu=rapid_config.get("use_gpu", False),
            )

    # 默认使用 RapidOCR
    from app.core.ocr_engine_rapid import RapidOCREngine
    ocr_config = config.get("ocr", {})
    rapid_config = ocr_config.get("rapidocr", {})
    return RapidOCREngine(
        lang=rapid_config.get("lang", "ch"),
        use_gpu=rapid_config.get("use_gpu", False),
    )


# 向后兼容别名
# 旧代码: from app.core.ocr_engine import OCREngine; OCREngine(lang=..., use_gpu=...)
# 新代码: from app.core.ocr_engine import get_ocr_engine; engine = get_ocr_engine(config)
OCREngine = get_ocr_engine
