"""StructuredExtractor 无头单测（纯 Python，不依赖 Qt）"""
import pandas as pd
import pytest
from PIL import Image

from app.core.structured_extractor import StructuredExtractor
from app.models.page_result import PageResult, Block, StructuredResult, StructuredField


def make_extractor(config=None):
    return StructuredExtractor(config)


def field_map(result: StructuredResult):
    return {f.label: f for f in result.fields}


class TestHeuristicExtraction:
    """Source A（启发式）：无换行 GGUF blob → 报关单 + 发票锚点取值"""

    def test_no_newline_blob_customs_and_invoice(self):
        blob = (
            "报关单号：090820241000039736海关编号：0908"
            "境内收货人(91210213959942233Y) 进境关别(0908)"
            "发票号码：12345678开票日期：2024年01月05日"
        )
        pr = PageResult(blocks=[], markdown=blob)
        result = make_extractor().enrich(pr)
        assert isinstance(result, StructuredResult)
        m = field_map(result)
        # 跨决策4 的实际格式：报关单号值应止于下一锚点 海关编号
        assert m["报关单号"].value == "090820241000039736"
        assert m["海关编号"].value == "0908"
        # 境内收货人(…) 括号形式：值止于闭括号
        assert m["境内收货人"].value == "91210213959942233Y"
        assert m["进境关别"].value == "0908"
        # 发票锚点（config 关键词）
        assert m["发票号码"].value == "12345678"
        assert m["开票日期"].value == "2024年01月05日"
        # 单一来源（raw_json 空）→ 匹配字段为 pending，绝不臆造
        assert m["报关单号"].status == "pending"
        assert m["发票号码"].status == "pending"

    def test_value_stops_at_next_anchor_and_trailing_punctuation(self):
        blob = "报关单号：090820241000039736。海关编号：0908"
        pr = PageResult(blocks=[], markdown=blob)
        m = field_map(make_extractor().enrich(pr))
        assert m["报关单号"].value == "090820241000039736"
        assert m["海关编号"].value == "0908"

    def test_unmatched_anchor_is_not_found(self):
        blob = "报关单号：090820241000039736"
        pr = PageResult(blocks=[], markdown=blob)
        m = field_map(make_extractor().enrich(pr))
        assert m["报关单号"].status == "pending"
        assert m["备注"].status == "not_found"
        assert m["备注"].value == ""
        assert m["备注"].source == "none"
        assert m["备注"].bbox is None

    def test_empty_markdown_all_not_found(self):
        pr = PageResult(blocks=[], markdown="")
        result = make_extractor().enrich(pr)
        assert result.fields
        assert all(f.status == "not_found" for f in result.fields)


class TestMergeRules:
    """Source A + Source B ensemble 合并：confirmed / pending / conflict"""

    def test_merge_rules_confirmed_pending_conflict(self):
        blob = "报关单号：090820241000039736海关编号：0908"
        raw_json = {"fields": {
            "报关单号": "090820241000039736",   # A == B → confirmed
            "预录入编号": "E2024001",            # 仅 B → pending
            "海关编号": "9999",                  # A=0908 B=9999 → conflict
        }}
        pr = PageResult(blocks=[], markdown=blob, raw_json=raw_json)
        m = field_map(make_extractor().enrich(pr))
        assert m["报关单号"].status == "confirmed"
        assert m["报关单号"].source == "heuristic"
        assert m["预录入编号"].status == "pending"
        assert m["预录入编号"].source == "vlm"
        assert m["预录入编号"].value == "E2024001"
        assert m["海关编号"].status == "conflict"
        assert m["海关编号"].value == "0908"  # 冲突时以 Source A 为准

    def test_vlm_inert_when_raw_json_empty(self):
        pr = PageResult(blocks=[], markdown="报关单号：090820241000039736", raw_json={})
        result = make_extractor().enrich(pr)
        assert all(f.source != "vlm" for f in result.fields)

    def test_vlm_inert_on_malformed_raw_json(self):
        for bad in (None, [], "x", {"fields": 123}):
            pr = PageResult(blocks=[], markdown="", raw_json=bad)
            result = make_extractor().enrich(pr)
            assert all(f.source != "vlm" for f in result.fields)


class TestValidationDelegation:
    """校验委托 FinanceProcessor，不重复实现"""

    def test_invalid_invoice_no_flagged(self):
        pr = PageResult(blocks=[], markdown="发票号码：12345")
        result = make_extractor().enrich(pr)
        f = field_map(result)["发票号码"]
        assert f.validated is False
        assert "位长" in f.validation_msg
        assert any("位长" in w for w in result.warnings)

    def test_valid_invoice_no_passes(self):
        pr = PageResult(blocks=[], markdown="发票号码：12345678")
        f = field_map(make_extractor().enrich(pr))["发票号码"]
        assert f.validated is True

    def test_invalid_date_flagged(self):
        pr = PageResult(blocks=[], markdown="开票日期：2024-13-99")
        f = field_map(make_extractor().enrich(pr))["开票日期"]
        assert f.validated is False


class TestTablesAndDetect:
    """enrich 接线：tables 复活 / line_boxes hook"""

    def test_enrich_populates_tables_from_pipe_table_markdown(self):
        md = (
            "| 序号 | 品名 | 金额 |\n"
            "|---|---|---|\n"
            "| 1 | 苹果 | 10 |\n"
            "| 2 | 香蕉 | 20 |"
        )
        pr = PageResult(blocks=[], markdown=md, tables=[])
        result = make_extractor().enrich(pr)
        assert pr.structured is result
        assert len(pr.tables) >= 1
        df = pr.tables[0]
        assert list(df.columns) == ["序号", "品名", "金额"]
        assert len(df) == 2

    def test_existing_tables_not_overwritten(self):
        df = pd.DataFrame({"a": [1]})
        pr = PageResult(blocks=[], markdown="| a |\n|---|\n| 1 |", tables=[df])
        make_extractor().enrich(pr)
        assert pr.tables == [df]

    def test_no_detect_line_boxes_empty_and_block_path_skipped(self):
        img = Image.new("RGB", (10, 10), (255, 255, 255))
        pr = PageResult(blocks=[], markdown="报关单号：090820241000039736")
        result = make_extractor().enrich(pr, image=img)  # detect=None
        assert pr.line_boxes == []
        assert all(f.bbox is None for f in result.fields)

    def test_detect_populates_line_boxes(self):
        img = Image.new("RGB", (10, 10), (255, 255, 255))
        box = Block(block_type="text", content="报关单号：090820241000039736", bbox=[0, 0, 100, 20])
        pr = PageResult(blocks=[], markdown="报关单号：090820241000039736")

        def detect(image):
            assert image is img
            return [box]

        make_extractor().enrich(pr, image=img, detect=detect)
        assert pr.line_boxes == [box]


class TestConfig:
    def test_invoice_keywords_from_config(self):
        config = {"finance": {"invoice": {"keywords": ["发票号码", "开票日期"]}}}
        ex = make_extractor(config)
        pr = PageResult(blocks=[], markdown="发票号码：12345678")
        result = ex.enrich(pr)
        labels = [f.label for f in result.fields]
        assert "发票号码" in labels
        assert "开票日期" in labels
        assert "购买方" not in labels
        assert "销售方" not in labels
        # 报关单锚点始终保留
        assert "报关单号" in labels

    def test_default_config_includes_standard_invoice_keywords(self):
        ex = make_extractor()
        labels = ex._labels
        for kw in ["发票号码", "开票日期", "价税合计", "购买方", "销售方"]:
            assert kw in labels
