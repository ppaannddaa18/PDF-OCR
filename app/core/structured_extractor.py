"""StructuredExtractor — 报关单/发票结构化字段提取（纯 Python，无 Qt 依赖，可无头单测）

设计（P0-a 结构化默认视图）：
- Source A（启发式，主线）：有序锚点正则扫描 ``page_result.markdown``，
  值 = 锚点后到下一个锚点 / 行尾 / 闭括号 / 结尾标点之间的子串。正则容忍
  空格与 ``：/:/（/(`` 分隔符变体（GGUF blob 无换行，锚点可能带/不带分隔符）。
- Source B（vlm，预留）：``page_result.raw_json`` 非空且含字段映射时解析。
  GGUF 今日 ``raw_json=={}``，恒 inert，接口留好、接线延后。
- 合并规则：双方一致 → confirmed；仅一方 → pending（待确认）；双方存在但
  不一致 → conflict（标红）；均无 → not_found（绝不臆造）。
- 校验委托 ``FinanceProcessor.validate_field``（发票号码/开票日期/金额/价税），
  不重复实现规则。
- 表格解析复用 ``table_extractor.extract_tables``。
- ``detect``/``line_boxes`` 为 Phase 4 预留 hook：P0 阶段 ``detect=None``，
  ``line_boxes`` 恒为空，Block/bbox 路径完全跳过。
"""
import logging
import re
from typing import Dict, List, Optional, Pattern, Tuple

from app.models.page_result import PageResult, StructuredField, StructuredResult
from app.core.table_extractor import extract_tables
from app.core.finance_processor import FinanceProcessor

logger = logging.getLogger("PDFOCR")

# 锚点分隔符变体：容忍空格 + 可选的 ：/:/（/(
_SEP = r"\s*[：:（(]?\s*"


def _anchor_pattern(text: str) -> str:
    """由锚点文本构造容忍分隔符变体的正则模式"""
    return re.escape(text) + _SEP


# 报关单头部国标字段（有序，覆盖决策4 中的 海关编号/进境关别 等实际格式）
_CUSTOMS_ANCHORS: List[Tuple[str, str]] = [
    (_anchor_pattern("报关单号"), "报关单号"),
    (_anchor_pattern("海关编号"), "海关编号"),
    (_anchor_pattern("预录入编号"), "预录入编号"),
    (_anchor_pattern("申报日期"), "申报日期"),
    (_anchor_pattern("经营单位"), "经营单位"),
    (_anchor_pattern("运输方式"), "运输方式"),
    (_anchor_pattern("提运单号"), "提运单号"),
    (_anchor_pattern("贸易方式"), "贸易方式"),
    (_anchor_pattern("征免性质"), "征免性质"),
    (_anchor_pattern("成交方式"), "成交方式"),
    (_anchor_pattern("币制"), "币制"),
    (_anchor_pattern("件数"), "件数"),
    (_anchor_pattern("毛重"), "毛重"),
    (_anchor_pattern("净重"), "净重"),
    (_anchor_pattern("集装箱号"), "集装箱号"),
    (_anchor_pattern("进境关别"), "进境关别"),
    (_anchor_pattern("境内收货人"), "境内收货人"),
    (_anchor_pattern("境内发货人"), "境内发货人"),
    (_anchor_pattern("合同协议号"), "合同协议号"),
    (_anchor_pattern("备注"), "备注"),
]

# 默认发票关键词（config["finance"]["invoice"]["keywords"] 可覆盖）
_DEFAULT_INVOICE_KEYWORDS = ["发票号码", "开票日期", "价税合计", "购买方", "销售方"]


class StructuredExtractor:
    """锚点式结构化字段提取器 — 纯 Python，可无头单测"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self.config = cfg
        finance_cfg = cfg.get("finance", {})
        self._invoice_keywords: List[str] = (
            finance_cfg.get("invoice", {}).get("keywords") or list(_DEFAULT_INVOICE_KEYWORDS)
        )
        # 校验委托（发票号码/开票日期/金额/价税），不重复实现
        self._validator = FinanceProcessor(cfg)
        # 有序锚点：(compiled regex, label)，报关单 + 发票
        self._anchors: List[Tuple[Pattern, str]] = [
            (re.compile(pat), label) for pat, label in _CUSTOMS_ANCHORS
        ]
        self._anchors.extend(
            (re.compile(_anchor_pattern(kw)), kw) for kw in self._invoice_keywords
        )
        # 字段展示顺序（去重）：报关单 → 发票
        customs_labels = [label for _, label in _CUSTOMS_ANCHORS]
        self._labels: List[str] = customs_labels + [
            kw for kw in self._invoice_keywords if kw not in customs_labels
        ]

    def enrich(self, page_result: PageResult, image=None, detect=None) -> StructuredResult:
        """结构化/表格/校验全流程（worker 线程内调用），写回 ``page_result.structured``。

        Args:
            page_result: ``recognize_page_auto`` 的原始结果
            image: 原始页面图像（detect 阶段使用；P0 未接线）
            detect: 行盒检测 callable(image) -> List[Block]（Phase 4 接线；P0 传 None）

        Returns:
            组装好的 StructuredResult（同时写回 page_result.structured）
        """
        # 1. 表格复活：tables 为空但 markdown 含管道表 → 灌入（复活「表格数据」Tab）
        if not page_result.tables and page_result.markdown:
            try:
                tables = extract_tables(page_result.markdown)
                if tables:
                    page_result.tables = tables
            except Exception:
                logger.debug("StructuredExtractor: table extraction failed", exc_info=True)

        # 2. line_boxes（Phase 4 hook）：detect 未提供时恒为空，Block 路径跳过
        if detect is not None and image is not None:
            try:
                boxes = detect(image)
                page_result.line_boxes = list(boxes or [])
            except Exception:
                logger.debug("StructuredExtractor: detect failed", exc_info=True)
                page_result.line_boxes = []

        # 3. 组装字段 + 校验
        result = self._extract_fields(page_result)

        # 4. 写回
        page_result.structured = result
        return result

    # ---------- 字段提取（ensemble 合并） ----------

    def _extract_fields(self, page_result: PageResult) -> StructuredResult:
        a_fields = self._extract_heuristic(page_result.markdown or "")
        b_fields = self._extract_vlm(page_result.raw_json)

        fields: List[StructuredField] = []
        for label in self._labels:
            fields.append(self._merge(label, a_fields.get(label), b_fields.get(label)))

        # Block 路径（P1 hook）：P0 阶段 line_boxes 恒为空（detect=None），完全跳过。
        # Phase 4 接线：line_boxes 非空时用邻近逻辑定锚，field.bbox = 命中的行盒并集。
        if page_result.line_boxes:
            self._apply_block_hook(fields)

        # 校验委托 FinanceProcessor（发票号码/开票日期/金额/价税）
        warnings: List[str] = []
        for f in fields:
            if f.value and self._is_validation_target(f.label):
                ok, msg = self._validator.validate_field(f.label, f.value)
                f.validated = ok
                f.validation_msg = msg
                if not ok:
                    warnings.append(msg)
        return StructuredResult(fields=fields, warnings=warnings)

    @staticmethod
    def _apply_block_hook(fields: List[StructuredField]) -> None:
        """P1 hook：Phase 4 用 ``finance_processor._find_neighbor`` 式邻近逻辑定锚。

        P0 阶段为结构占位（无检测引擎，line_boxes 恒为空，实际不会走到这里），
        仅保留扩展点，不执行任何坐标匹配。
        """
        for f in fields:
            f.bbox = None

    @classmethod
    def _merge(cls, label: str, av: Optional[str], bv: Optional[str]) -> StructuredField:
        """Source A（启发式）与 Source B（vlm）合并。

        规则：双方一致 → confirmed；仅一方 → pending；双方存在但不一致 → conflict；
        均无 → not_found（绝不臆造值）。
        """
        if av and bv:
            if av == bv:
                return StructuredField(label=label, value=av, source="heuristic", status="confirmed")
            return StructuredField(label=label, value=av, source="heuristic", status="conflict")
        if av:
            return StructuredField(label=label, value=av, source="heuristic", status="pending")
        if bv:
            return StructuredField(label=label, value=bv, source="vlm", status="pending")
        return StructuredField(label=label, value="", source="none", status="not_found")

    @staticmethod
    def _is_validation_target(label: str) -> bool:
        """与 FinanceProcessor._validate 的分派一致（避免重复实现规则但保持同步）"""
        return label == "发票号码" or label in ("开票日期", "日期") or "金额" in label or "价税" in label

    # ---------- Source A：锚点正则（主线） ----------

    def _extract_heuristic(self, text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for pat, label in self._anchors:
            m = pat.search(text)
            if not m:
                continue
            value = self._extract_value(text, m.end(), self._anchors)
            if value:
                result[label] = value
        return result

    @staticmethod
    def _extract_value(text: str, start: int, anchors) -> str:
        """锚点后到下一个锚点/行尾/闭括号/结尾标点之间的子串，去首尾空白与标点。"""
        rest = text[start:]
        # 行尾
        nl = rest.find("\n")
        if nl != -1:
            rest = rest[:nl]
        # 下一个锚点（最早出现者）
        next_pos = None
        for pat, _label in anchors:
            m = pat.search(rest)
            if m and (next_pos is None or m.start() < next_pos):
                next_pos = m.start()
        if next_pos is not None:
            rest = rest[:next_pos]
        # 闭括号（如 境内收货人(91210213959942233Y)）
        for cp in (")", "）"):
            idx = rest.find(cp)
            if idx != -1:
                rest = rest[:idx]
                break
        return rest.strip().strip("。．，,、；;：:")

    # ---------- Source B：VLM raw_json（预留，今日 inert） ----------

    @staticmethod
    def _extract_vlm(raw_json) -> Dict[str, str]:
        """从 VLM raw_json 解析字段映射。GGUF 今日 ``raw_json=={}``，恒返回 {}。

        约定 raw_json 结构：``{"fields": {label: value, ...}}``；也兼容扁平
        label→value dict。Phase 4 接线时可在本方法内做 label 归一化。
        """
        if not isinstance(raw_json, dict) or not raw_json:
            return {}
        data = raw_json.get("fields") if isinstance(raw_json.get("fields"), dict) else raw_json
        if not isinstance(data, dict):
            return {}
        result: Dict[str, str] = {}
        for k, v in data.items():
            if isinstance(k, str) and isinstance(v, str) and v.strip():
                result[k] = v.strip()
        return result
