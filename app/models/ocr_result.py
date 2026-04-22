from dataclasses import dataclass
from typing import Dict


@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    manually_edited: bool = False


@dataclass
class FileResult:
    source_file: str
    fields: Dict[str, FieldResult]
    success: bool = True
    error_msg: str = ""