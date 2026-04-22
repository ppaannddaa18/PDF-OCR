import unittest
import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.pdf_loader import PdfLoader
from app.models.region import Region


class TestPdfLoader(unittest.TestCase):
    """PDF 加载器测试"""

    def setUp(self):
        self.loader = PdfLoader(dpi=150)

    def test_init(self):
        """测试初始化"""
        self.assertEqual(self.loader.dpi, 150)

    def test_get_page_size_invalid_file(self):
        """测试无效文件处理"""
        with self.assertRaises(Exception):
            self.loader.get_page_size("nonexistent.pdf")


if __name__ == "__main__":
    unittest.main()
