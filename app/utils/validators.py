import re
from datetime import datetime
from typing import Tuple, Optional

PATTERNS = {
    "email": r"^[\w\.-]+@[\w\.-]+\.\w+$",
    "phone": r"^1[3-9]\d{9}$",
    "date":  r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$",
    "number": r"^-?\d+(\.\d+)?$",
}

# 日期解析格式
DATE_FORMATS = [
    "%Y-%m-%d",
    "%Y/%m/%d",
    "%Y年%m月%d日",
    "%Y年%m月%d",
    "%d/%m/%Y",
    "%d-%m-%Y",
]


def validate(text: str, field_type: str) -> bool:
    """验证文本是否符合字段类型格式"""
    if field_type == "text":
        return True
    if not text or not text.strip():
        return True  # 空值不验证
    pat = PATTERNS.get(field_type)
    return bool(re.match(pat, text.strip())) if pat else True


def validate_with_error(text: str, field_type: str) -> Tuple[bool, Optional[str]]:
    """
    验证文本并返回错误信息
    返回: (是否通过, 错误信息)
    """
    if field_type == "text":
        return True, None
    if not text or not text.strip():
        return True, None  # 空值不验证

    text = text.strip()

    if field_type == "number":
        if not re.match(PATTERNS["number"], text):
            return False, "格式应为数字（如：123 或 123.45）"
        return True, None

    elif field_type == "date":
        if not re.match(PATTERNS["date"], text):
            return False, "格式应为日期（如：2024-01-15 或 2024年1月15日）"
        # 尝试解析日期
        parsed = parse_date(text)
        if parsed is None:
            return False, "日期格式无法识别"
        return True, None

    elif field_type == "email":
        if not re.match(PATTERNS["email"], text):
            return False, "格式应为邮箱（如：example@domain.com）"
        return True, None

    elif field_type == "phone":
        # 先清理文本中的空格和横线
        cleaned = re.sub(r"[\s-]", "", text)
        if not re.match(PATTERNS["phone"], cleaned):
            return False, "格式应为手机号（如：13800138000）"
        return True, None

    return True, None


def parse_date(text: str) -> Optional[datetime]:
    """尝试解析日期字符串"""
    text = text.strip()
    # 清理常见的变体
    text = text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")

    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def normalize_number(text: str) -> str:
    """标准化数字格式"""
    if not text:
        return text
    # 提取数字部分
    numbers = re.findall(r"-?\d+\.?\d*", text.replace(",", ""))
    if numbers:
        return numbers[0]
    return text


def normalize_date(text: str) -> str:
    """标准化日期格式为 YYYY-MM-DD"""
    parsed = parse_date(text)
    if parsed:
        return parsed.strftime("%Y-%m-%d")
    return text


def normalize_phone(text: str) -> str:
    """标准化手机号格式"""
    cleaned = re.sub(r"[\s-]", "", text)
    return cleaned


def normalize_by_type(text: str, field_type: str) -> str:
    """根据字段类型标准化文本"""
    if field_type == "number":
        return normalize_number(text)
    elif field_type == "date":
        return normalize_date(text)
    elif field_type == "phone":
        return normalize_phone(text)
    return text
