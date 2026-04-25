import fitz
from PIL import Image
import io
import time
import threading
from collections import OrderedDict


class PdfLoader:
    def __init__(self, dpi: int = 200, max_cached_docs: int = 10):
        self.dpi = dpi
        self._max_cached = max_cached_docs
        self._doc_cache = OrderedDict()  # path -> (doc, last_access_time)
        self._lock = threading.RLock()

    def _get_document(self, pdf_path: str) -> fitz.Document:
        """获取或打开PDF文档（带LRU缓存）"""
        with self._lock:
            # 检查缓存
            if pdf_path in self._doc_cache:
                doc, _ = self._doc_cache[pdf_path]
                # 更新访问时间并移到末尾（最近使用）
                self._doc_cache.move_to_end(pdf_path)
                return doc

            # LRU 淘汰
            while len(self._doc_cache) >= self._max_cached:
                oldest_path, (oldest_doc, _) = self._doc_cache.popitem(last=False)
                try:
                    oldest_doc.close()
                except Exception:
                    pass

            # 打开新文档
            doc = fitz.open(pdf_path)
            self._doc_cache[pdf_path] = (doc, time.time())
            return doc

    def _close_document(self, pdf_path: str):
        """关闭并移除缓存的文档"""
        with self._lock:
            if pdf_path in self._doc_cache:
                doc, _ = self._doc_cache.pop(pdf_path)
                try:
                    doc.close()
                except Exception:
                    pass

    def clear_cache(self):
        """清空所有缓存的文档"""
        with self._lock:
            for doc, _ in self._doc_cache.values():
                try:
                    doc.close()
                except Exception:
                    pass
            self._doc_cache.clear()

    def render_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """渲染指定页为 PIL Image"""
        doc = self._get_document(pdf_path)
        page = doc[page_num]
        mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # 使用零拷贝方式创建图像，避免PNG中间格式
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples_mv)
        return img

    def get_page_size(self, pdf_path: str, page_num: int = 0) -> tuple:
        """返回 PDF 页面原始尺寸 (width_pt, height_pt)"""
        doc = self._get_document(pdf_path)
        page = doc[page_num]
        rect = page.rect
        return rect.width, rect.height

    def crop_region(self, pdf_path: str, region, page_num: int = 0) -> Image.Image:
        """根据归一化坐标裁剪区域"""
        img = self.render_page(pdf_path, page_num)
        W, H = img.size
        left = max(0, int(region.x * W))
        top = max(0, int(region.y * H))
        right = min(W, int((region.x + region.w) * W))
        bottom = min(H, int((region.y + region.h) * H))
        if right <= left or bottom <= top:
            return Image.new("RGB", (1, 1), (255, 255, 255))
        return img.crop((left, top, right, bottom))
