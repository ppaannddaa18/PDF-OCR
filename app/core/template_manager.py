import json
import logging
from pathlib import Path
from typing import Optional
from app.models.template import Template

logger = logging.getLogger("PDFOCR")


class TemplateManager:
    def save(self, template: Template, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, filepath: str) -> Optional[Template]:
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            return Template.from_dict(data)
        except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
            logger.error(f"加载模板失败 {filepath}: {e}")
            return None

    def list_templates(self, folder: str) -> list:
        return [str(p) for p in Path(folder).glob("*.json")]
