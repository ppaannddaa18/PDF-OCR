import json
from pathlib import Path
from app.models.template import Template


class TemplateManager:
    def save(self, template: Template, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, filepath: str) -> Template:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Template.from_dict(data)

    def list_templates(self, folder: str) -> list:
        return [str(p) for p in Path(folder).glob("*.json")]
