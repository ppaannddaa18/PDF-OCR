import pandas as pd
from typing import List
from app.models.ocr_result import FileResult


class Exporter:
    def to_excel(self, results: List[FileResult], output_path: str, include_confidence: bool = True):
        rows = []
        for r in results:
            row = {"源文件": r.source_file, "状态": "成功" if r.success else f"失败：{r.error_msg}"}
            seen_names = set()
            for region_id, fr in r.fields.items():
                # 如果多个 region 有同名 field_name，用 region_id 区分列名
                col_name = fr.field_name
                if col_name in seen_names:
                    col_name = f"{fr.field_name}_{region_id[:8]}"
                seen_names.add(fr.field_name)
                row[col_name] = fr.text
                if include_confidence:
                    row[f"{col_name}_置信度"] = round(fr.confidence, 3)
                row[f"{col_name}_引擎"] = fr.engine
                row[f"{col_name}_匹配级别"] = fr.match_level
                row[f"{col_name}_人工修正"] = "是" if fr.manually_edited else "否"
            rows.append(row)
        df = pd.DataFrame(rows)
        try:
            df.to_excel(output_path, index=False, engine="openpyxl")
        except Exception as e:
            raise IOError(f"Failed to write Excel file: {e}")

    def to_csv(self, results: List[FileResult], output_path: str, include_confidence: bool = True):
        rows = []
        for r in results:
            row = {"源文件": r.source_file, "状态": "成功" if r.success else f"失败：{r.error_msg}"}
            seen_names = set()
            for region_id, fr in r.fields.items():
                # 如果多个 region 有同名 field_name，用 region_id 区分列名
                col_name = fr.field_name
                if col_name in seen_names:
                    col_name = f"{fr.field_name}_{region_id[:8]}"
                seen_names.add(fr.field_name)
                row[col_name] = fr.text
                if include_confidence:
                    row[f"{col_name}_置信度"] = round(fr.confidence, 3)
                row[f"{col_name}_引擎"] = fr.engine
                row[f"{col_name}_匹配级别"] = fr.match_level
                row[f"{col_name}_人工修正"] = "是" if fr.manually_edited else "否"
            rows.append(row)
        df = pd.DataFrame(rows)
        try:
            df.to_csv(output_path, index=False, encoding="utf-8-sig")
        except Exception as e:
            raise IOError(f"Failed to write CSV file: {e}")
