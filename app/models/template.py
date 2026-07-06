from dataclasses import dataclass, field, asdict
from typing import List
from datetime import datetime
from app.models.region import Region


@dataclass
class Template:
    name: str
    regions: List[Region] = field(default_factory=list)
    page_width: float = 0.0            # 模板 PDF 页面宽（pt）
    page_height: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        data = data.copy()
        if not isinstance(data.get("regions"), list):
            data["regions"] = []
        data["regions"] = [Region.from_dict(r) for r in data["regions"]]
        return cls(**data)