"""
批量处理器 - 性能优化版
- 页面级渲染缓存，避免重复渲染
- 优化线程池配置
- 减少锁竞争
"""
from typing import List, Callable, Dict, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from PIL import Image
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine_base import OCREngineBase
from app.models.template import Template
from app.models.ocr_result import FileResult, FieldResult


class BatchProcessor:
    """
    批量处理器 - 性能优化版

    优化点：
    1. 页面级渲染缓存，同一PDF的多个区域只渲染一次
    2. 移除冗余的OCR锁（由OCREngineBase子类内部处理）
    3. 动态调整线程数
    """

    def __init__(self, pdf_loader: PdfLoader, ocr_engine: OCREngineBase, config: dict, max_workers: int = 4):
        self.pdf_loader = pdf_loader
        self.ocr = ocr_engine
        self.max_workers = max_workers
        self.config = config  # 用于获取page_dpi等配置
        # 页面渲染缓存：pdf_path -> rendered_image
        self._page_cache: Dict[str, Image.Image] = {}
        self._page_cache_lock = threading.Lock()

    def _get_rendered_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """
        获取渲染后的页面（带缓存）

        性能优化：同一PDF的多个区域共享一次渲染结果
        """
        cache_key = f"{pdf_path}:{page_num}"

        with self._page_cache_lock:
            if cache_key in self._page_cache:
                return self._page_cache[cache_key]

        # 渲染页面
        image = self.pdf_loader.render_page(pdf_path, page_num)

        with self._page_cache_lock:
            self._page_cache[cache_key] = image

        return image

    def _clear_page_cache(self):
        """清空页面缓存"""
        with self._page_cache_lock:
            self._page_cache.clear()

    def process_one(self, pdf_path: str, template: Template) -> FileResult:
        """
        处理单个PDF文件 — 根据引擎类型自动选择处理路径

        PaddleOCR-VL: 整页识别 + FieldMatcher匹配
        RapidOCR:     逐区域裁剪识别（原有逻辑）
        """
        try:
            fields = {}
            regions_by_page: Dict[int, list] = {}
            for region in template.regions:
                page_num = 0  # 多页未实现，统一归到第0页
                if page_num not in regions_by_page:
                    regions_by_page[page_num] = []
                regions_by_page[page_num].append(region)

            use_vl = self.ocr.engine_name in ("paddleocr_vl", "paddleocr_vl_cpu")

            for page_num, regions in regions_by_page.items():
                rendered_image = self._get_rendered_page(pdf_path, page_num)

                if use_vl:
                    # PaddleOCR-VL: 整页一次推理
                    page_results = self.ocr.recognize_page(
                        rendered_image, regions,
                        page_dpi=self.config.get("ocr", {}).get("paddleocr_vl", {}).get("page_dpi", 200)
                    )
                    for region in regions:
                        text, conf, match_level, _ = page_results.get(
                            region.id, ("", 0.0, 0, None)
                        )
                        fields[region.field_name] = FieldResult(
                            field_name=region.field_name,
                            text=text,
                            confidence=conf,
                            match_level=match_level,
                            engine=self.ocr.engine_name,
                        )
                else:
                    # RapidOCR: 逐区域裁剪识别
                    W, H = rendered_image.size
                    for region in regions:
                        left = max(0, int(region.x * W))
                        top = max(0, int(region.y * H))
                        right = min(W, int((region.x + region.w) * W))
                        bottom = min(H, int((region.y + region.h) * H))
                        if right <= left or bottom <= top:
                            crop = Image.new("RGB", (1, 1), (255, 255, 255))
                        else:
                            crop = rendered_image.crop((left, top, right, bottom))
                        text, conf = self.ocr.recognize(crop, region.ocr_mode)
                        fields[region.field_name] = FieldResult(
                            field_name=region.field_name,
                            text=text,
                            confidence=conf,
                            engine="rapidocr",
                        )

            return FileResult(source_file=pdf_path, fields=fields, success=True)

        except Exception as e:
            return FileResult(source_file=pdf_path, fields={}, success=False, error_msg=str(e))

    def process_batch(
        self,
        pdf_paths: List[str],
        template: Template,
        progress_cb: Callable[[int, int, str], None] = None,
    ) -> List[FileResult]:
        """
        并行批量处理PDF文件

        性能优化：
        - 使用线程池并行处理
        - 进度回调支持节流
        """
        # 清空页面缓存（新批次开始）
        self._clear_page_cache()

        results = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed_count = 0
        lock = threading.Lock()

        def process_one_wrapper(idx_path):
            idx, path = idx_path
            result = self.process_one(path, template)
            return idx, result

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(process_one_wrapper, (i, p)): i
                for i, p in enumerate(pdf_paths)
            }

            for future in as_completed(futures):
                idx, result = future.result()
                with lock:
                    results[idx] = result
                    completed_count += 1
                if progress_cb:
                    progress_cb(completed_count, total, pdf_paths[idx])

        return results

    def process_batch_with_templates(
        self,
        pdf_paths: List[str],
        templates: List[Template],
        progress_cb: Callable[[int, int, str], None] = None,
        completed_results: List = None,
    ) -> List[FileResult]:
        """
        为每个PDF使用对应的模板进行并行批量处理

        性能优化：
        - 页面级缓存减少渲染次数
        - 支持取消时返回已完成结果
        """
        # 清空页面缓存（新批次开始）
        self._clear_page_cache()

        results = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed_count = 0
        lock = threading.Lock()

        def process_one_wrapper(idx_path_template):
            idx, path, template = idx_path_template
            result = self.process_one(path, template)
            return idx, result

        # 如果模板列表为空，直接返回错误结果
        if not templates:
            return [FileResult(p, {}, success=False, error_msg="No templates available") for p in pdf_paths]

        # 准备任务列表
        tasks = [
            (i, p, templates[i] if i < len(templates) else templates[-1])
            for i, p in enumerate(pdf_paths)
        ]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {
                executor.submit(process_one_wrapper, task): task[0]
                for task in tasks
            }

            for future in as_completed(futures):
                idx, result = future.result()
                with lock:
                    results[idx] = result
                    completed_count += 1
                    # 收集已完成结果（用于取消时返回）
                    if completed_results is not None:
                        completed_results.append(result)
                if progress_cb:
                    progress_cb(completed_count, total, pdf_paths[idx])

        return results
