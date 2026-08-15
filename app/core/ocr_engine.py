"""
OCR引擎工厂 — 根据配置返回对应引擎实例
"""
from typing import Optional
from app.core.ocr_engine_base import OCREngineBase


def get_ocr_engine(config: dict) -> OCREngineBase:
    """
    根据配置创建OCR引擎实例。

    config["ocr"]["engine"]:
        "paddle_vl" → PaddleOCRVLEngine（PaddleOCR-VL-1.6 官方管线 paddlex native，主引擎）
        "gguf"      → GGUFOCREngine（llama.cpp 服务器，旧路径保留兼容）
        "rapidocr"  → RapidOCREngine（CPU，降级备用）

    如果 PaddleOCRVLEngine 初始化失败（环境未配置/模型缺失），
    自动降级到 RapidOCREngine。
    """
    engine_type = config.get("ocr", {}).get("engine", "paddle_vl")

    if engine_type == "paddle_vl":
        try:
            from app.core.ocr_engine_paddle_vl import PaddleOCRVLEngine
            return PaddleOCRVLEngine(config)
        except ImportError as e:
            import logging
            logging.getLogger("PDFOCR").warning(
                f"PaddleOCR-VL 引擎不可用 ({e})，降级到RapidOCR"
            )
            # 自动降级
            from app.core.ocr_engine_rapid import RapidOCREngine
            ocr_config = config.get("ocr", {})
            rapid_config = ocr_config.get("rapidocr", {})
            return RapidOCREngine(
                lang=rapid_config.get("lang", "ch"),
                use_gpu=rapid_config.get("use_gpu", False),
            )

    if engine_type == "gguf":
        try:
            from app.core.ocr_engine_gguf import GGUFOCREngine
            return GGUFOCREngine(config)
        except ImportError as e:
            import logging
            logging.getLogger("PDFOCR").warning(
                f"GGUF引擎不可用 ({e})，降级到RapidOCR"
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
