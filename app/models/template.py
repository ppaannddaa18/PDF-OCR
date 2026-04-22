from dataclasses import dataclass, field
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
        return {
            "name": self.name,
            "regions": [r.to_dict() for r in self.regions],
            "page_width": self.page_width,
            "page_height": self.page_height,
            "created_at": self.created_at,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        data = data.copy()
        data["regions"] = [Region.from_dict(r) for r in data.get("regions", [])]
        return cls(**data)