"""关键字结果适配器 — FileKeywordResult → FileResult（Task P4）

GGUF 窗口的「识别结果」页与历史记录消费 FileResult（字段表格式），而关键字
提取产出 FileKeywordResult（每文件每页每关键字一个 KeywordCell）。本适配器
把关键字结果转换为 FileResult 供 ResultTable / HistoryManager 复用。

转换规则（每文件每关键字一行，跨页同名关键字加 _2/_3 后缀去重）：
    field_name  = 关键字（首次出现）/ 关键字_N（重复出现）
    text        = KeywordCell.value
    confidence  = KeywordCell.confidence
    manually_edited = KeywordCell.manually_edited
    engine      = 'gguf'
    success     = FileKeywordResult.success
    error_msg   = FileKeywordResult.error_msg
"""
from typing import Iterable, List

from app.models.keyword_result import FileKeywordResult
from app.models.ocr_result import FieldResult, FileResult


def _unique_field_name(fields: dict, base: str) -> str:
    """同名关键字去重：base、base_2、base_3…（与 BatchProcessor 同策略）"""
    if base not in fields:
        return base
    n = 2
    while f"{base}_{n}" in fields:
        n += 1
    return f"{base}_{n}"


def to_file_results(
    file_results: Iterable[FileKeywordResult],
    engine: str = "gguf",
) -> List[FileResult]:
    """把关键字提取结果转换为识别结果（每文件每关键字一行）"""
    converted: List[FileResult] = []
    for fr in file_results:
        fields: dict = {}
        for page in fr.pages:
            for keyword, cell in page.cells.items():
                name = _unique_field_name(fields, keyword)
                fields[name] = FieldResult(
                    field_name=name,
                    text=cell.value,
                    confidence=cell.confidence,
                    region_id="",
                    manually_edited=cell.manually_edited,
                    match_level=0,
                    engine=engine,
                )
        converted.append(FileResult(
            source_file=fr.source_file,
            fields=fields,
            success=fr.success,
            error_msg=fr.error_msg,
        ))
    return converted
