"""关键字批量提取 — 逐文件逐页：渲染 → GGUF recognize_page_auto → 提取

仅 GGUF 路径（用户决策：关键字提取用 GGUF，模板框选用 RapidOCR）。
文件级并行（ThreadPoolExecutor）、页级串行；单页失败不中断批次；
progress_cb 内抛 InterruptedError 可取消（与 BatchWorker 同模式）。
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

from app.core.keyword_extractor import KeywordExtractor
from app.models.keyword_result import FileKeywordResult, PageKeywordResult


class KeywordBatchProcessor:

    def __init__(self, pdf_loader, ocr_engine, config: Optional[dict] = None,
                 max_workers: int = 4):
        self.pdf_loader = pdf_loader
        self.ocr_engine = ocr_engine
        self.config = config or {}
        self.max_workers = max(1, max_workers)
        # 单页失败重试次数（设置页 batch.retry_times；0 = 不重试）
        self.retry_times = max(0, int(self.config.get("batch", {}).get("retry_times", 2)))

    def process_batch(self, pdf_paths: List[str], keywords: List[str],
                      progress_cb: Optional[Callable[[int, int, str], None]] = None,
                      completed_results: Optional[list] = None,
                      ) -> List[FileKeywordResult]:
        """并行处理全部文件，结果按输入顺序回填；单文件异常不中断批次。

        completed_results 用于取消场景：进度回调抛 InterruptedError 时，
        已完成的文件结果已收集到该列表（worker 取消后可展示部分结果）。
        """
        results: List[FileKeywordResult] = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for idx, path in enumerate(pdf_paths):
                futures[pool.submit(self.process_one, path, keywords)] = idx
            for future in futures:
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = FileKeywordResult(
                        source_file=pdf_paths[idx], success=False, error_msg=str(e))
                completed += 1
                if completed_results is not None:
                    completed_results.append(results[idx])
                if progress_cb:
                    progress_cb(completed, total, pdf_paths[idx])
        return results

    def process_one(self, pdf_path: str, keywords: List[str]) -> FileKeywordResult:
        extractor = KeywordExtractor(keywords)
        page_count = self.pdf_loader.page_count(pdf_path)
        if page_count <= 0:
            return FileKeywordResult(source_file=pdf_path, success=False,
                                     error_msg="无法打开文件或文件为空")
        pages: List[PageKeywordResult] = []
        for page_no in range(1, page_count + 1):
            pages.append(self._extract_page(pdf_path, page_no, extractor))
        return FileKeywordResult(source_file=pdf_path, pages=pages,
                                 success=any(p.success for p in pages))

    def _extract_page(self, pdf_path: str, page_no: int,
                      extractor: KeywordExtractor) -> PageKeywordResult:
        """单页提取（含重试：渲染/OCR 偶发失败时按 retry_times 重试）"""
        last_err: Optional[Exception] = None
        for attempt in range(self.retry_times + 1):
            try:
                image = self.pdf_loader.render_page(pdf_path, page_no - 1)
                result = self.ocr_engine.recognize_page_auto(image)
                markdown = getattr(result, "markdown", "") or ""
                cells = extractor.extract(markdown)
                # 检测层行盒（预览核对用）：引擎不提供 → 空列表，行为与旧版一致
                line_boxes = list(getattr(result, "line_boxes", None) or [])
                return PageKeywordResult(page_no=page_no, cells=cells,
                                         line_boxes=line_boxes)
            except Exception as e:
                last_err = e
                if attempt < self.retry_times:
                    continue
        return PageKeywordResult(page_no=page_no, success=False,
                                 error_msg=str(last_err))
