import unittest
import sys
import os
import tempfile

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.core.exporter import Exporter
from app.models.ocr_result import FileResult, FieldResult


class TestExporter(unittest.TestCase):
    """导出器测试"""

    def setUp(self):
        self.exporter = Exporter()
        self.test_results = [
            FileResult(
                source_file="test1.pdf",
                fields={
                    "姓名": FieldResult("姓名", "张三", 0.95),
                    "日期": FieldResult("日期", "2024-01-15", 0.88),
                },
                success=True,
            ),
            FileResult(
                source_file="test2.pdf",
                fields={
                    "姓名": FieldResult("姓名", "李四", 0.92),
                    "日期": FieldResult("日期", "2024-01-16", 0.85),
                },
                success=True,
            ),
        ]

    def test_to_excel(self):
        """测试 Excel 导出"""
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as f:
            output_path = f.name

        try:
            self.exporter.to_excel(self.test_results, output_path, include_confidence=True)
            self.assertTrue(os.path.exists(output_path))
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)

    def test_to_csv(self):
        """测试 CSV 导出"""
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as f:
            output_path = f.name

        try:
            self.exporter.to_csv(self.test_results, output_path, include_confidence=True)
            self.assertTrue(os.path.exists(output_path))
        finally:
            if os.path.exists(output_path):
                os.unlink(output_path)


if __name__ == "__main__":
    unittest.main()
