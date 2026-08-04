"""关键字提取器 — 两级匹配（精确锚点 → 宽松兜底），纯 Python 可无头单测

精确 pass 复用 structured_extractor 的锚点取值核心（_SEP/_anchor_pattern/
_extract_value，模块级函数 import 复用）；宽松 pass 在精确未命中时启用：
L1 同行剩余 → L2 下一行拼接 → L3 blob 兜底（止于下一锚点）。宽松命中
一律 status=pending 供人工核对（source='loose'）。
"""
import re
from typing import Dict, List, Optional, Pattern, Tuple

from app.models.keyword_result import KeywordCell
from app.core.structured_extractor import _SEP, _anchor_pattern, StructuredExtractor

# _extract_value 是 StructuredExtractor 的 staticmethod（非模块级），通过类取用
_extract_value = StructuredExtractor._extract_value


def normalize_keyword(keyword: str) -> str:
    """关键字归一化：strip + 去尾部冒号/括号（'价税合计：' 与 '价税合计' 等价）"""
    return keyword.strip().rstrip("：:（( ")


class KeywordExtractor:
    """两级匹配提取器：输入全页文本（GGUF markdown），输出每关键字一个 KeywordCell"""

    def __init__(self, keywords: List[str], loose: bool = True, max_next_lines: int = 1):
        self.keywords = [normalize_keyword(k) for k in keywords if normalize_keyword(k)]
        self.loose = loose
        self.max_next_lines = max(1, max_next_lines)
        # 精确锚点：(compiled regex, keyword)，有序
        self._anchors: List[Tuple[Pattern, str]] = [
            (re.compile(_anchor_pattern(kw)), kw) for kw in self.keywords
        ]

    def extract(self, text: str, lines: Optional[List[str]] = None) -> Dict[str, KeywordCell]:
        """两级匹配提取，返回 keyword -> KeywordCell

        Args:
            text: 全页文本（GGUF markdown，可能为无换行 blob）
            lines: 可选行级文本（宽松跨行拼接用；缺省从 text 按换行切分）
        """
        text = text or ""
        line_list = lines if lines is not None else [ln for ln in text.split("\n")]
        exact = self._exact_pass(text)
        loose = self._loose_pass(line_list, text) if self.loose else {}
        cells: Dict[str, KeywordCell] = {}
        for kw in self.keywords:
            if kw in exact:
                cells[kw] = KeywordCell(keyword=kw, value=exact[kw],
                                        status="confirmed", source="exact")
            elif kw in loose:
                cells[kw] = KeywordCell(keyword=kw, value=loose[kw],
                                        status="pending", source="loose",
                                        line_text=self._hit_line(kw, line_list))
            else:
                cells[kw] = KeywordCell(keyword=kw, value="",
                                        status="not_found", source="none")
        return cells

    # ---------- 精确 pass（复用结构化提取取值核心） ----------

    def _exact_pass(self, text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for pat, kw in self._anchors:
            m = pat.search(text)
            if not m:
                continue
            # 锚点模式尾部 \s* 可能吞掉换行：跨行命中 → 此行无值，交宽松 pass
            if "\n" in m.group(0):
                continue
            value = _extract_value(text, m.end(), self._anchors)
            if value:
                result[kw] = value
        return result

    # ---------- 宽松 pass ----------

    def _loose_pass(self, lines: List[str], text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for kw in self.keywords:
            value = self._loose_one(kw, lines, text)
            if value:
                result[kw] = value
        return result

    def _loose_one(self, kw: str, lines: List[str], text: str) -> str:
        """L1 同行剩余 → L2 后续行拼接（跳过标签行）→ L3 blob 兜底"""
        for i, line in enumerate(lines):
            pos = line.find(kw)
            if pos == -1:
                continue
            rest = line[pos + len(kw):].lstrip("：:（( ")
            # 同行剩余止于下一个关键字（blob/同行多列时值常与后续标签粘连）
            rest = self._truncate_at_other_keyword(rest, kw)
            # 剩余部分只是相邻字段标签（如 贸易国（地区）（DEU））→ 走 L2 跨行
            if self._is_label_like(rest):
                rest = ""
            if self._plausible(rest):
                return self._clean(rest)
            # L2：同行剩余为空/不可信 → 拼接后续行；标签行（相邻字段标题）
            # 跳过但不消耗预算，兼容「标签在上一行、值在下一行」的表格布局
            joined = rest
            scanned = 0
            j = 1
            while scanned < self.max_next_lines and i + j < len(lines):
                nxt = lines[i + j].strip()
                nxt = self._truncate_at_other_keyword(nxt, kw)
                if self._is_label_like(nxt):
                    j += 1
                    continue
                scanned += 1
                joined += nxt
                if self._plausible(joined):
                    return self._clean(joined)
                j += 1
            break
        # L3：单行 blob 退化 → 复用 _extract_value（止于下一锚点/闭括号/标点）
        if len(lines) <= 1 and kw in text:
            pos = text.find(kw) + len(kw)
            value = _extract_value(text, pos, self._anchors)
            if value:
                return value
        return ""

    def _truncate_at_other_keyword(self, value: str, kw: str) -> str:
        """值文本止于下一个用户关键字（防把相邻字段标签当作值）"""
        for other in self.keywords:
            if not other or other == kw:
                continue
            idx = value.find(other)
            if idx != -1:
                value = value[:idx]
                break
        return value.strip()

    @staticmethod
    def _is_label_like(value: str) -> bool:
        """标签行启发式：空行，或「纯中文前缀 + 末尾括号编码」形态

        覆盖报关单等表格的相邻字段标题（如 贸易国（地区）（DEU）、
        经停港（BEL003）、入境口岸（210101）、（DEU））：这些行是标签
        而非值，L2 跨行扫描时应跳过，直到找到真正的值行。
        """
        s = value.strip()
        if not s:
            return True
        m = re.search(r"^(.*?)[（(][A-Za-z0-9]+[）)]$", s)
        if m and not re.search(r"[A-Za-z0-9]", m.group(1)):
            return True
        return False

    @staticmethod
    def _plausible(value: str) -> bool:
        """宽松命中可信度：含数字 → 可信；无数字需含非汉字字符（防抓正文行）"""
        if not value:
            return False
        if any(ch.isdigit() for ch in value):
            return True
        return len(value) >= 2 and any(not ('一' <= ch <= '鿿') for ch in value)

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip().strip("。．，,、；;：:）)")

    def _hit_line(self, kw: str, lines: List[str]) -> str:
        for line in lines:
            if kw in line:
                return line.strip()
        return ""
