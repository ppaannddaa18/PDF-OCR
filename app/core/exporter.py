import pandas as pd
from typing import List
from app.models.ocr_result import FileResult


class Exporter:
    def to_excel(self, results: List[FileResult], output_path: str, include_confidence: bool = True):
        rows = []
        for r in results:
            row = {"源文件": r.source_file, "状态": "成功" if r.success else f"失败：{r.error_msg}"}
            for field_name, fr in r.fields.items():
                row[field_name] = fr.text
                if include_confidence:
                    row[f"{field_name}_置信度"] = round(fr.confidence, 3)
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_excel(output_path, index=False, engine="openpyxl")

    def to_csv(self, results: List[FileResult], output_path: str, include_confidence: bool = True):
        rows = []
        for r in results:
            row = {"源文件": r.source_file, "状态": "成功" if r.success else f"失败：{r.error_msg}"}
            for field_name, fr in r.fields.items():
                row[field_name] = fr.text
                if include_confidence:
                    row[f"{field_name}_置信度"] = round(fr.confidence, 3)
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_csv(output_path, index=False, encoding="utf-8-sig")
