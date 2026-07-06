"""统一页面结果数据模型 — 引擎无关"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# 发票号位长集合：老专票(8)、普票(10/12)、数电发票(20)
VALID_INVOICE_LEN = {8, 10, 12, 20}


@dataclass
class Block:
    """版面块 — 引擎无关的统一结构"""
    block_type: str           # "text" | "table" | "formula" | "chart" | "seal"
    content: str              # 文本内容（表格为Markdown字符串）
    bbox: List[float]         # [x1, y1, x2, y2] 像素坐标
    confidence: float = 1.0   # 置信度 0-1
    meta: Dict[str, Any] = field(default_factory=dict)  # 引擎特定元数据


@dataclass
class PageResult:
    """整页解析结果"""
    blocks: List[Block]              # 所有版面块
    markdown: str = ""               # 全页Markdown
    tables: List[Any] = field(default_factory=list)  # DataFrame列表
    raw_json: Dict[str, Any] = field(default_factory=dict)  # VLM原始json
    image_size: tuple = (0, 0)       # (width, height)
    inference_time_ms: float = 0.0   # 推理耗时（毫秒）


@dataclass
class FinanceField:
    """单个财务字段"""
    label: str                # 字段名（如"发票号码"）
    value: str                # 提取值
    confidence: float = 1.0   # 置信度
    validated: bool = True    # 是否通过校验
    validation_msg: str = ""  # 校验失败时说明原因


@dataclass
class FinanceResult:
    """财务字段提取结果"""
    fields: List[FinanceField] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # 校验异常

    def get(self, label: str) -> Optional[str]:
        for f in self.fields:
            if f.label == label:
                return f.value
        return None
