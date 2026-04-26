"""
PDF加载器 - 性能优化版
- 异步渲染支持
- 内存感知的缓存策略
- 线程安全的LRU缓存
"""
import fitz
from PIL import Image
import threading
import time
from collections import OrderedDict
from typing import Optional, Tuple


class PdfLoader:
    """
    PDF加载器 - 性能优化版

    优化点：
    1. 线程安全的LRU文档缓存
    2. 内存感知的缓存淘汰
    3. 支持异步渲染
    """

    # 内存阈值：缓存总大小超过此值时触发淘汰
    MEMORY_THRESHOLD_MB = 200

    def __init__(self, dpi: int = 200, max_cached_docs: int = 10):
        self.dpi = dpi
        self._max_cached = max_cached_docs
        self._doc_cache: OrderedDict = OrderedDict()  # path -> (doc, last_access_time, estimated_size)
        self._lock = threading.RLock()
        self._total_cache_size = 0  # 估算的缓存总大小（MB）

    def _estimate_doc_size(self, doc: fitz.Document) -> float:
        """估算文档内存占用（MB）"""
        # 基于页面数量和DPI估算
        page_count = len(doc)
        # 单页渲染大小估算：DPI=200时约11MB
        single_page_size = (self.dpi / 72) ** 2 * 0.05  # MB
        return page_count * single_page_size

    def _get_document(self, pdf_path: str) -> fitz.Document:
        """获取或打开PDF文档（带LRU缓存和内存感知淘汰）"""
        with self._lock:
            # 检查缓存
            if pdf_path in self._doc_cache:
                doc, _, size = self._doc_cache[pdf_path]
                # 更新访问时间并移到末尾（最近使用）
                self._doc_cache.move_to_end(pdf_path)
                return doc

            # 打开新文档
            doc = fitz.open(pdf_path)
            size = self._estimate_doc_size(doc)

            # 内存感知淘汰
            while (len(self._doc_cache) >= self._max_cached or
                   self._total_cache_size + size > self.MEMORY_THRESHOLD_MB):
                if not self._doc_cache:
                    break
                oldest_path, (oldest_doc, _, oldest_size) = self._doc_cache.popitem(last=False)
                try:
                    oldest_doc.close()
                except Exception:
                    pass
                self._total_cache_size -= oldest_size

            self._doc_cache[pdf_path] = (doc, time.time(), size)
            self._total_cache_size += size
            return doc

    def _close_document(self, pdf_path: str):
        """关闭并移除缓存的文档"""
        with self._lock:
            if pdf_path in self._doc_cache:
                doc, _, size = self._doc_cache.pop(pdf_path)
                try:
                    doc.close()
                except Exception:
                    pass
                self._total_cache_size -= size

    def clear_cache(self):
        """清空所有缓存的文档"""
        with self._lock:
            for doc, _, _ in self._doc_cache.values():
                try:
                    doc.close()
                except Exception:
                    pass
            self._doc_cache.clear()
            self._total_cache_size = 0

    def render_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """
        渲染指定页为 PIL Image

        注意：此方法包含同步I/O，建议在后台线程调用
        """
        doc = self._get_document(pdf_path)
        page = doc[page_num]
        mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        # 使用零拷贝方式创建图像，避免PNG中间格式
        img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples_mv)
        return img

    def render_page_async(
        self,
        pdf_path: str,
        page_num: int = 0,
        callback: Optional[callable] = None
    ) -> None:
        """
        异步渲染页面

        Args:
            pdf_path: PDF文件路径
            page_num: 页面编号
            callback: 渲染完成回调，接收 (image, error) 参数
        """
        def _render():
            try:
                image = self.render_page(pdf_path, page_num)
                if callback:
                    callback(image, None)
            except Exception as e:
                if callback:
                    callback(None, str(e))

        thread = threading.Thread(target=_render, daemon=True, name="PDF-Render")
        thread.start()

    def get_page_size(self, pdf_path: str, page_num: int = 0) -> Tuple[float, float]:
        """返回 PDF 页面原始尺寸 (width_pt, height_pt)"""
        doc = self._get_document(pdf_path)
        page = doc[page_num]
        rect = page.rect
        return rect.width, rect.height

    def crop_region(
        self,
        pdf_path: str,
        region,
        page_num: int = 0,
        rendered_image: Optional[Image.Image] = None
    ) -> Image.Image:
        """
        根据归一化坐标裁剪区域

        性能优化：支持传入已渲染的图像，避免重复渲染

        Args:
            pdf_path: PDF文件路径
            region: 区域对象（包含归一化坐标）
            page_num: 页面编号
            rendered_image: 已渲染的图像（可选，用于避免重复渲染）
        """
        # 使用传入的图像或重新渲染
        if rendered_image is not None:
            img = rendered_image
        else:
            img = self.render_page(pdf_path, page_num)

        W, H = img.size
        left = max(0, int(region.x * W))
        top = max(0, int(region.y * H))
        right = min(W, int((region.x + region.w) * W))
        bottom = min(H, int((region.y + region.h) * H))

        if right <= left or bottom <= top:
            return Image.new("RGB", (1, 1), (255, 255, 255))

        return img.crop((left, top, right, bottom))

    @property
    def cache_size(self) -> float:
        """获取当前缓存大小（MB）"""
        return self._total_cache_size

    @property
    def cached_count(self) -> int:
        """获取缓存文档数量"""
        return len(self._doc_cache)