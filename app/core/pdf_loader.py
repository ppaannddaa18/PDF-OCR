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
from concurrent.futures import ThreadPoolExecutor
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
        self._doc_locks = {}  # path -> threading.Lock, 保护单个文档的并发访问
        self._doc_locks_lock = threading.Lock()  # 保护 _doc_locks 字典
        self._total_cache_size = 0  # 估算的缓存总大小（MB）
        self._async_executor = ThreadPoolExecutor(max_workers=2)
        self._doc_refcount = {}  # path -> int, 活跃用户计数
        self._doc_refcount_lock = threading.Lock()

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
                with self._doc_refcount_lock:
                    self._doc_refcount[pdf_path] = self._doc_refcount.get(pdf_path, 0) + 1
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
            with self._doc_refcount_lock:
                self._doc_refcount[pdf_path] = self._doc_refcount.get(pdf_path, 0) + 1
            return doc

    def _close_document(self, pdf_path: str):
        """关闭并移除缓存的文档（跳过仍在使用的文档）"""
        with self._lock:
            if pdf_path in self._doc_cache:
                with self._doc_refcount_lock:
                    if self._doc_refcount.get(pdf_path, 0) > 0:
                        return  # doc is in use, skip close
                doc, _, size = self._doc_cache.pop(pdf_path)
                try:
                    doc.close()
                except Exception:
                    pass
                self._total_cache_size -= size
        self._cleanup_doc_lock(pdf_path)

    def shutdown(self):
        """关闭所有资源（应用退出时调用）"""
        self.clear_cache()
        self._async_executor.shutdown(wait=True, timeout=10)

    def clear_cache(self):
        """清空所有缓存的文档（跳过仍在使用的文档）"""
        with self._lock:
            to_remove = []
            for path, (doc, _, size) in list(self._doc_cache.items()):
                with self._doc_refcount_lock:
                    if self._doc_refcount.get(path, 0) > 0:
                        continue  # skip in-use documents
                try:
                    doc.close()
                except Exception:
                    pass
                to_remove.append(path)
            for path in to_remove:
                if path in self._doc_cache:
                    _, _, size = self._doc_cache.pop(path)
                    self._total_cache_size -= size
        # 清理异步执行器并重建
        self._async_executor.shutdown(wait=False)
        self._async_executor = ThreadPoolExecutor(max_workers=2)

    def _get_doc_lock(self, pdf_path: str) -> threading.Lock:
        """获取文档级别的锁，保护单个 fitz.Document 的并发访问"""
        with self._doc_locks_lock:
            if pdf_path not in self._doc_locks:
                self._doc_locks[pdf_path] = threading.Lock()
            return self._doc_locks[pdf_path]

    def _release_document(self, pdf_path: str):
        """释放文档引用计数"""
        with self._doc_refcount_lock:
            if pdf_path in self._doc_refcount:
                self._doc_refcount[pdf_path] -= 1
                if self._doc_refcount[pdf_path] <= 0:
                    del self._doc_refcount[pdf_path]

    def _cleanup_doc_lock(self, pdf_path: str):
        """清理已关闭文档的锁"""
        with self._doc_locks_lock:
            self._doc_locks.pop(pdf_path, None)

    def render_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """
        渲染指定页为 PIL Image

        注意：此方法包含同步I/O，建议在后台线程调用
        """
        doc = self._get_document(pdf_path)
        if page_num >= len(doc):
            self._release_document(pdf_path)
            raise ValueError(f"Page {page_num} out of range (doc has {len(doc)} pages)")
        try:
            doc_lock = self._get_doc_lock(pdf_path)
            with doc_lock:
                page = doc[page_num]
                mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
                pix = page.get_pixmap(matrix=mat, alpha=False)
                # 使用零拷贝方式创建图像，避免PNG中间格式
                img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples_mv)
                return img
        finally:
            self._release_document(pdf_path)

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

        self._async_executor.submit(_render)

    def get_page_size(self, pdf_path: str, page_num: int = 0) -> Tuple[float, float]:
        """返回 PDF 页面原始尺寸 (width_pt, height_pt)"""
        doc = self._get_document(pdf_path)
        try:
            doc_lock = self._get_doc_lock(pdf_path)
            with doc_lock:
                page = doc[page_num]
                rect = page.rect
                return rect.width, rect.height
        finally:
            self._release_document(pdf_path)

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