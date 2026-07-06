"""
OCR引擎旧接口测试 — 已迁移到 test_ocr_engines.py
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from app.core.ocr_engine import get_ocr_engine
from app.utils.config_loader import get_default_config


class TestOCREngineCompat:
    """向后兼容测试"""

    def test_factory_returns_singleton_for_rapidocr(self):
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        e1 = get_ocr_engine(config)
        e2 = get_ocr_engine(config)
        assert e1 is e2  # 单例

    def test_default_degradation(self):
        config = get_default_config()
        engine = get_ocr_engine(config)
        assert engine.engine_name in ('rapidocr', 'paddleocr_vl')

