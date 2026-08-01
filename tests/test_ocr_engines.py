"""
OCR引擎功能测试 — RapidOCR、PaddleOCR-VL、工厂函数
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from PIL import Image
from app.core.ocr_engine import get_ocr_engine
from app.core.ocr_engine_base import OCREngineBase
from app.utils.config_loader import get_default_config


class TestOCREngineFactory:
    """工厂函数 + 降级测试"""

    def test_rapidocr_engine(self):
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        engine = get_ocr_engine(config)
        assert engine.engine_name == 'rapidocr'
        engine.initialize()
        assert engine.is_ready

    def test_paddleocr_vl_degradation(self):
        """PaddlePaddle不可用时应自动降级"""
        config = get_default_config()
        config['ocr']['engine'] = 'paddleocr_vl'
        engine = get_ocr_engine(config)
        # 如果PaddlePaddle已安装则可能是paddleocr_vl，否则应是rapidocr
        assert engine.engine_name in ('paddleocr_vl', 'rapidocr')

    def test_unknown_engine_defaults_to_rapid(self):
        config = get_default_config()
        config['ocr']['engine'] = 'unknown'
        engine = get_ocr_engine(config)
        assert engine.engine_name == 'rapidocr'

    def test_factory_returns_ocreninebase(self):
        config = get_default_config()
        engine = get_ocr_engine(config)
        assert isinstance(engine, OCREngineBase)
        assert hasattr(engine, 'initialize')
        assert hasattr(engine, 'recognize')
        assert hasattr(engine, 'recognize_page')
        assert hasattr(engine, 'is_ready')


class TestRapidOCREngine:
    """RapidOCR引擎功能测试"""

    @pytest.fixture
    def engine(self):
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        e = get_ocr_engine(config)
        e.initialize()
        return e

    def test_recognize_blank_image(self, engine):
        img = Image.new('RGB', (200, 50), 'white')
        text, conf = engine.recognize(img)
        assert isinstance(text, str)
        assert isinstance(conf, float)
        assert 0.0 <= conf <= 1.0

    def test_recognize_single_line_mode(self, engine):
        img = Image.new('RGB', (300, 60), 'white')
        text, conf = engine.recognize(img, mode='single_line')
        assert isinstance(text, str)
        # single_line mode should not contain newlines
        assert '\n' not in text

    def test_recognize_auto_reinit(self):
        """R3修复后 recognzie() 自动尝试重新初始化"""
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        from app.core.ocr_engine_rapid import RapidOCREngine
        RapidOCREngine.reset_instance()
        engine = RapidOCREngine(lang='ch', use_gpu=False)
        # unload后recognize应自动重新初始化
        img = Image.new('RGB', (100, 30), 'white')
        text, conf = engine.recognize(img)  # 不抛异常，自动reinit
        assert isinstance(text, str)

    def test_recognize_page_empty_regions(self, engine):
        img = Image.new('RGB', (200, 100), 'white')
        results = engine.recognize_page(img, [])
        assert results == {}

    def test_singleton_preserved(self, engine):
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        e2 = get_ocr_engine(config)
        assert e2.is_ready  # same instance, already initialized


class TestDetectLines:
    """P1 检测层：detect_lines 行盒转换 + 坐标缩放回原始图像空间"""

    @pytest.fixture
    def engine(self):
        config = get_default_config()
        config['ocr']['engine'] = 'rapidocr'
        e = get_ocr_engine(config)
        e.initialize()
        return e

    def test_detect_lines_converts_to_blocks(self, engine, monkeypatch):
        # 合成 RapidOCR 结果：[4点框, 文本, score]
        fake_result = [
            ([[0, 0], [100, 0], [100, 20], [0, 20]], "报关单号：123", 0.95),
        ]
        monkeypatch.setattr(engine, "_ocr", lambda arr: (fake_result, 0.5))
        img = Image.new('RGB', (200, 100), 'white')
        blocks = engine.detect_lines(img)
        assert len(blocks) == 1
        b = blocks[0]
        assert b.block_type == 'text'
        assert b.content == "报关单号：123"
        assert len(b.bbox) == 4
        assert b.bbox == [0, 0, 100, 20]
        assert 0.0 <= b.confidence <= 1.0

    def test_detect_lines_scales_back_when_preprocess_resized(self, engine, monkeypatch):
        # min(size)=30 < 100 → preprocess_for_ocr 放大 ×3；
        # bbox 必须缩放回原始图像坐标（== 画布场景坐标）
        fake_result = [
            ([[0, 0], [150, 0], [150, 30], [0, 30]], "文本", 0.9),
        ]
        monkeypatch.setattr(engine, "_ocr", lambda arr: (fake_result, 0.5))
        img = Image.new('RGB', (50, 30), 'white')
        blocks = engine.detect_lines(img)
        assert len(blocks) == 1
        x1, y1, x2, y2 = blocks[0].bbox
        assert x1 == 0 and y1 == 0
        # 预处理图 150×90，框 0..150 × 0..30 → 原图 0..50 × 0..10
        assert abs(x2 - 50) < 0.01
        assert abs(y2 - 10) < 0.01

    def test_detect_lines_empty_result(self, engine, monkeypatch):
        monkeypatch.setattr(engine, "_ocr", lambda arr: (None, 0.5))
        img = Image.new('RGB', (200, 100), 'white')
        assert engine.detect_lines(img) == []

    def test_detect_lines_not_ready_returns_empty(self, monkeypatch):
        from app.core.ocr_engine_rapid import RapidOCREngine
        RapidOCREngine.reset_instance()
        engine = RapidOCREngine(lang='ch', use_gpu=False)
        # 阻止真实初始化（加载 ONNX 模型），验证未就绪兜底
        monkeypatch.setattr(engine, "initialize", lambda: None)
        img = Image.new('RGB', (200, 100), 'white')
        assert engine.detect_lines(img) == []


class TestPaddleOCREngine:
    """PaddleOCR-VL引擎功能测试（需要PaddlePaddle GPU）"""

    @pytest.fixture
    def paddle_engine(self):
        config = get_default_config()
        config['ocr']['engine'] = 'paddleocr_vl'
        e = get_ocr_engine(config)
        if e.engine_name == 'paddleocr_vl':
            e.initialize()
        return e

    def test_engine_name(self, paddle_engine):
        assert paddle_engine.engine_name in ('paddleocr_vl', 'rapidocr')

    def test_recognize_delegates_to_recognize_page(self, paddle_engine):
        if not paddle_engine.is_ready:
            pytest.skip("PaddleOCR-VL not available")
        img = Image.new('RGB', (200, 100), 'white')
        text, conf = paddle_engine.recognize(img)
        assert isinstance(text, str)
        assert isinstance(conf, float)

    def test_dummy_region_created_at_module_level(self):
        from app.core.ocr_engine_gguf import _DummyRegion
        dr = _DummyRegion(100, 50, mode='general')
        assert dr.id == '__single__'
        assert dr.x == 0.0
        assert dr.y == 0.0
        assert dr.w == 1.0
        assert dr.h == 1.0
        assert dr._pixel_bbox == [0, 0, 100, 50]

    def test_image_pixel_limit_rescaling(self):
        """GGUF 引擎的像素限制缩放逻辑（_image_to_base64）"""
        import base64, io
        from app.core.ocr_engine_gguf import GGUFOCREngine
        config = get_default_config()
        config['ocr']['engine'] = 'gguf'
        config['ocr']['gguf']['min_pixels'] = 147384
        config['ocr']['gguf']['max_pixels'] = 2822400
        GGUFOCREngine.reset_instance()
        engine = GGUFOCREngine(config)
        # 小图（10000 px << min_pixels）应被放大（int 截断允许 <1% 误差）
        small = Image.new('RGB', (100, 100), 'white')
        out = Image.open(io.BytesIO(base64.b64decode(engine._image_to_base64(small))))
        assert out.width * out.height >= 147384 * 0.99
        # 大图（25M px >> max_pixels）应被缩小到不超过 max_pixels
        big = Image.new('RGB', (5000, 5000), 'white')
        out = Image.open(io.BytesIO(base64.b64decode(engine._image_to_base64(big))))
        assert out.width * out.height <= 2822400
