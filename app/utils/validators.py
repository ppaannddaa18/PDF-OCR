import re

PATTERNS = {
    "email": r"^[\w\.-]+@[\w\.-]+\.\w+$",
    "phone": r"^1[3-9]\d{9}$",
    "date":  r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$",
    "number": r"^-?\d+(\.\d+)?$",
}


def validate(text: str, field_type: str) -> bool:
    if field_type == "text":
        return True
    pat = PATTERNS.get(field_type)
    return bool(re.match(pat, text.strip())) if pat else True
