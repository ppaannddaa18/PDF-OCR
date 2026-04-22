import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.ocr_engine import OCREngine


class TestOCREngine(unittest.TestCase):
    """OCR 引擎测试"""

    def test_singleton(self):
        """测试单例模式"""
        engine1 = OCREngine(lang="ch", use_gpu=False)
        engine2 = OCREngine(lang="ch", use_gpu=False)
        self.assertIs(engine1, engine2)


if __name__ == "__main__":
    unittest.main()
