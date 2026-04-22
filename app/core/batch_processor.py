from typing import List, Callable
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.models.template import Template
from app.models.ocr_result import FileResult, FieldResult


class BatchProcessor:
    def __init__(self, pdf_loader: PdfLoader, ocr_engine: OCREngine):
        self.pdf_loader = pdf_loader
        self.ocr = ocr_engine

    def process_one(self, pdf_path: str, template: Template) -> FileResult:
        try:
            fields = {}
            for region in template.regions:
                crop = self.pdf_loader.crop_region(pdf_path, region)
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
        results = []
        total = len(pdf_paths)
        for idx, path in enumerate(pdf_paths):
            result = self.process_one(path, template)
            results.append(result)
            if progress_cb:
                progress_cb(idx + 1, total, path)
        return results
