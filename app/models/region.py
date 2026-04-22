from dataclasses import dataclass, field
from typing import Literal


@dataclass
class Region:
    """框选区域数据模型（坐标使用归一化 0~1 比例）"""
    id: str                            # 唯一标识
    field_name: str                    # 字段名（如"姓名"）
    x: float                           # 左上角 x 比例
    y: float                           # 左上角 y 比例
    w: float                           # 宽度比例
    h: float                           # 高度比例
    field_type: Literal["text", "number", "date", "email", "phone"] = "text"
    ocr_mode: Literal["general", "single_line", "number"] = "general"
    color: str = "#FF5733"             # 框的显示颜色

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "Region":
        return cls(**data)