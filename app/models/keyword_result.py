"""关键字提取结果模型 — 引擎无关"""
from dataclasses import dataclass, field
from typing import Dict, List

from app.models.page_result import Block


@dataclass
class KeywordCell:
    """单个关键字在本页的提取结果"""
    keyword: str
    value: str = ""
    status: str = "not_found"      # 'confirmed' | 'pending' | 'not_found'
    source: str = "none"           # 'exact' | 'loose' | 'none'
    line_text: str = ""            # 命中行原文（tooltip 供人工核对）
    confidence: float = 1.0
    manually_edited: bool = False  # 人工修正标记（导出/历史用）


@dataclass
class PageKeywordResult:
    """单页提取结果"""
    page_no: int                              # 1-based
    cells: Dict[str, KeywordCell] = field(default_factory=dict)
    success: bool = True
    error_msg: str = ""
    line_boxes: List[Block] = field(default_factory=list)  # OCR 检测层行盒（预览核对用）


@dataclass
class FileKeywordResult:
    """单文件全部页的提取结果"""
    source_file: str
    pages: List[PageKeywordResult] = field(default_factory=list)
    success: bool = True
    error_msg: str = ""
