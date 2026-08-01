"""关键字汇总导出 — Excel/CSV：每页一行（文件名|页号|kw|kw_状态|…|文件状态）"""
import pandas as pd
from typing import Dict, List

from app.models.keyword_result import FileKeywordResult

_STATUS_WORDS = {"confirmed": "已确认", "pending": "待确认",
                 "not_found": "未找到", "error": "失败"}


class KeywordExporter:

    def _build_rows(self, results: List[FileKeywordResult],
                    include_status: bool = True) -> List[Dict]:
        keywords: List[str] = []
        for fr in results:
            for pg in fr.pages:
                for kw in pg.cells:
                    if kw not in keywords:
                        keywords.append(kw)
        rows = []
        for fr in results:
            if fr.pages:
                for pg in fr.pages:
                    row = {"源文件": fr.source_file, "页号": pg.page_no,
                           "文件状态": "成功" if fr.success else f"失败：{fr.error_msg}"}
                    for kw in keywords:
                        cell = pg.cells.get(kw)
                        row[kw] = cell.value if cell and cell.status != "not_found" else ""
                        if include_status:
                            row[f"{kw}_状态"] = (
                                _STATUS_WORDS.get(cell.status, "") if cell else "未找到")
                    rows.append(row)
            else:
                rows.append({"源文件": fr.source_file, "页号": "",
                             "文件状态": f"失败：{fr.error_msg}"})
        return rows

    def to_excel(self, results: List[FileKeywordResult], output_path: str,
                 include_status: bool = True):
        pd.DataFrame(self._build_rows(results, include_status)).to_excel(
            output_path, index=False, engine="openpyxl")

    def to_csv(self, results: List[FileKeywordResult], output_path: str,
               include_status: bool = True):
        pd.DataFrame(self._build_rows(results, include_status)).to_csv(
            output_path, index=False, encoding="utf-8-sig")
