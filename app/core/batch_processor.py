from typing import List, Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
import threading
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.models.template import Template
from app.models.ocr_result import FileResult, FieldResult


class BatchProcessor:
    def __init__(self, pdf_loader: PdfLoader, ocr_engine: OCREngine, max_workers: int = 4):
        self.pdf_loader = pdf_loader
        self.ocr = ocr_engine
        self.max_workers = max_workers
        self._ocr_lock = threading.Lock()

    def process_one(self, pdf_path: str, template: Template) -> FileResult:
        try:
            fields = {}
            for region in template.regions:
                crop = self.pdf_loader.crop_region(pdf_path, region)
                # OCR调用需要加锁保护
                with self._ocr_lock:
                    text, conf = self.ocr.recognize(crop, region.ocr_mode)
                fields[region.field_name] = FieldResult(
                    field_name=region.field_name,
                    text=text,
                    confidence=conf,
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
        """并行批量处理PDF文件"""
        results = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed_count = 0
        lock = threading.Lock()

        def process_one_wrapper(idx_path):
            idx, path = idx_path
            result = self.process_one(path, template)
            return idx, result

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(process_one_wrapper, (i, p)): i
                       for i, p in enumerate(pdf_paths)}

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
    ) -> List[FileResult]:
        """为每个PDF使用对应的模板进行并行批量处理"""
        results = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed_count = 0
        lock = threading.Lock()

        def process_one_wrapper(idx_path_template):
            idx, path, template = idx_path_template
            result = self.process_one(path, template)
            return idx, result

        # 准备任务列表
        tasks = [(i, p, templates[i] if i < len(templates) else templates[-1])
                 for i, p in enumerate(pdf_paths)]

        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            futures = {executor.submit(process_one_wrapper, task): task[0]
                       for task in tasks}

            for future in as_completed(futures):
                idx, result = future.result()
                with lock:
                    results[idx] = result
                    completed_count += 1
                if progress_cb:
                    progress_cb(completed_count, total, pdf_paths[idx])

        return results
