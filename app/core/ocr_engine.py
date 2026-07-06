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
            # 预检：确认 PaddleOCR 实际可导入
            import paddleocr  # noqa: F401
            from app.core.ocr_engine_paddle import PaddleOCREngine
            vl_cfg = config.setdefault("ocr", {}).setdefault("paddleocr_vl", {})
            if engine_type == "paddleocr_vl_cpu":
                # CPU模式：覆盖device配置（质量相同，0显存，较慢）
                vl_cfg["device"] = "cpu"
                vl_cfg["precision"] = "fp32"
            else:
                # GPU模式：显式设置，防止之前CPU模式切换残留的配置污染
                vl_cfg["device"] = "gpu:0"
                vl_cfg["precision"] = "fp16"
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
