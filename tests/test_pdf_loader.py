import unittest
import sys
import os
import tempfile

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import fitz

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

    def _make_pdf(self, pages: int) -> str:
        """生成临时 PDF 并返回路径（用 fitz 构造，避免依赖测试资源）"""
        doc = fitz.open()
        for i in range(pages):
            page = doc.new_page()
            page.insert_text((72, 72), f"page {i}")
        fd, path = tempfile.mkstemp(suffix=".pdf")
        os.close(fd)
        try:
            doc.save(path)
        finally:
            doc.close()
        return path

    def _unlink(self, path: str):
        """先释放 loader 缓存中的 fitz 文档再删除临时文件（Windows 文件锁）"""
        try:
            self.loader.clear_cache()
        except Exception:
            pass
        try:
            os.unlink(path)
        except OSError:
            pass

    def test_page_count_equals_len_doc(self):
        """page_count 返回文档页数（== len(doc)）"""
        path = self._make_pdf(3)
        try:
            self.assertEqual(self.loader.page_count(path), 3)
        finally:
            self._unlink(path)

    def test_page_count_single_page(self):
        """单页 PDF"""
        path = self._make_pdf(1)
        try:
            self.assertEqual(self.loader.page_count(path), 1)
        finally:
            self._unlink(path)

    def test_page_count_invalid_file_returns_zero(self):
        """无效文件 page_count 返回 0（不抛异常）"""
        self.assertEqual(self.loader.page_count("nonexistent.pdf"), 0)

    def test_page_count_does_not_leak_refcount(self):
        """page_count 正确配对 _get_document/_release_document，引用计数不泄漏"""
        path = self._make_pdf(2)
        try:
            before = self.loader._doc_refcount.get(path, 0)
            self.loader.page_count(path)
            after = self.loader._doc_refcount.get(path, 0)
            self.assertEqual(after, before)
        finally:
            self._unlink(path)


if __name__ == "__main__":
    unittest.main()
