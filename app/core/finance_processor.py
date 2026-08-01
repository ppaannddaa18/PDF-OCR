"""FinanceProcessor — 引擎无关的财务字段抽取与校验"""
import re
from datetime import date
from typing import List, Optional, Dict, Set, Tuple
from app.models.page_result import Block, FinanceResult, FinanceField, VALID_INVOICE_LEN


class FinanceProcessor:
    """财务字段抽取器 — 输入 Block[]，输出 FinanceResult"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        finance_cfg = cfg.get("finance", {})
        self._keywords: List[str] = finance_cfg.get("invoice", {}).get("keywords", [
            "发票号码", "开票日期", "价税合计", "购买方", "销售方"
        ])
        self._amount_tolerance: float = finance_cfg.get("validation", {}).get("amount_tolerance", 0.01)
        self._tax_rate: float = finance_cfg.get("validation", {}).get("tax_rate", 0.13)

    def process(self, blocks: List[Block]) -> FinanceResult:
        """从 blocks 中抽取财务字段并校验"""
        fields = []
        warnings = []

        # 字段抽取：关键词 → 邻近值
        for kw in self._keywords:
            anchor = None
            for b in blocks:
                # 使用词边界匹配，避免"日期"匹配"出生日期"
                if re.search(r'(?<!\w)' + re.escape(kw) + r'(?!\w)', b.content):
                    anchor = b
                    break
            if anchor is None:
                continue
            value = _find_neighbor(blocks, anchor, direction='right')
            if not value:
                # 从anchor.content中提取关键词后的值部分（如"发票号码：12345678" → "12345678"）
                parts = re.split(r'[：:]\s*', anchor.content, maxsplit=1)
                value = parts[1].strip() if len(parts) > 1 else ""
            fields.append(FinanceField(label=kw, value=value))

        # 校验
        self._validate(fields, warnings)
        return FinanceResult(fields=fields, warnings=warnings)

    def _validate(self, fields: List[FinanceField], warnings: List[str]) -> None:
        """对已抽取字段执行校验规则"""
        for f in fields:
            if f.label == "发票号码":
                _validate_invoice_no(f, warnings)
            elif f.label in ("开票日期", "日期"):
                _validate_date(f, warnings)
            elif "金额" in f.label or "价税" in f.label:
                _validate_amount(f, warnings)

    def validate_field(self, label: str, value: str) -> Tuple[bool, str]:
        """对单个字段执行校验（供 StructuredExtractor 委托，不重复实现规则）

        Returns:
            (validated, validation_msg)
        """
        f = FinanceField(label=label, value=value)
        warnings: List[str] = []
        self._validate([f], warnings)
        return f.validated, f.validation_msg


# --- 坐标邻近查找 ---

def _find_neighbor(blocks: List[Block], anchor: Block, direction: str = 'right') -> str:
    """从 anchor 的右侧（同高度范围内）或下方（同 x 范围内）查找最近的 block"""
    if anchor.bbox is None:
        return ""
    ax1, ay1, ax2, ay2 = anchor.bbox

    # 从中位 block 高度计算行高阈值，下限 30px
    heights = [(b.bbox[3] - b.bbox[1]) for b in blocks if b.bbox is not None and (b.bbox[3] - b.bbox[1]) > 0]
    import statistics
    median_h = statistics.median(heights) if heights else 0
    y_tolerance = max(30, int(median_h * 1.5))
    # Use same median-based tolerance for below direction
    x_tolerance = max(30, int(median_h * 1.5))

    candidates = []
    for b in blocks:
        if b is anchor or b.bbox is None:
            continue
        bx1, by1 = b.bbox[0], b.bbox[1]
        if direction == 'right' and abs(by1 - ay1) < y_tolerance and bx1 >= ax2:
            candidates.append((bx1, b))
        elif direction == 'below' and abs(bx1 - ax1) < x_tolerance and by1 >= ay2:
            candidates.append((by1, b))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1].content
    return ""


# --- 正则工具 ---

_MONEY_RE = re.compile(r'[¥￥]\s*([\d,]+\.?\d*)')

def _extract_money(text: str) -> Optional[float]:
    m = _MONEY_RE.search(text.replace(' ', ''))
    return float(m.group(1).replace(',', '')) if m else None


_DATE_RE = re.compile(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})')

def _extract_date(text: str) -> Optional[str]:
    text_norm = text.replace('年', '-').replace('月', '-').replace('日', '')
    m = _DATE_RE.search(text_norm)
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


# --- 校验 ---

def _validate_invoice_no(f: FinanceField, warnings: List[str]) -> None:
    no = f.value.strip().replace(' ', '')
    if no.isdigit() and len(no) not in VALID_INVOICE_LEN:
        f.validated = False
        f.validation_msg = f"发票号位长 {len(no)} 不在合法范围 {VALID_INVOICE_LEN}"
        warnings.append(f.validation_msg)


def _validate_date(f: FinanceField, warnings: List[str]) -> None:
    d = _extract_date(f.value)
    if d is None:
        f.validated = False
        f.validation_msg = f"无法解析日期: {f.value}"
        warnings.append(f.validation_msg)
    else:
        try:
            parts = d.split('-')
            parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
            if parsed > date.today():
                f.validated = False
                f.validation_msg = f"日期 {d} 超过当前日期"
                warnings.append(f.validation_msg)
        except ValueError:
            f.validated = False
            f.validation_msg = f"非法日期: {d}"
            warnings.append(f.validation_msg)


def _validate_amount(f: FinanceField, warnings: List[str]) -> None:
    amount = _extract_money(f.value)
    if amount is None:
        f.validated = False
        f.validation_msg = f"无法解析金额: {f.value}"
        warnings.append(f.validation_msg)
