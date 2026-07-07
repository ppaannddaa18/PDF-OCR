from dataclasses import dataclass
from typing import Dict


@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    region_id: str = ""       # 新增：关联的 Region.id
    manually_edited: bool = False
    match_level: int = 0     # 0=未匹配 1=IoU精确 2=就近搜索 3=关键词兜底
    engine: str = ""         # "rapidocr" | "paddleocr_vl" | "paddleocr_vl_cpu"


@dataclass
class FileResult:
    source_file: str
    fields: Dict[str, FieldResult]  # key=region_id (不再是 field_name)
    success: bool = True
    error_msg: str = ""