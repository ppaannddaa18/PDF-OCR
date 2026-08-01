import pytest

from app.core.keyword_extractor import KeywordExtractor, normalize_keyword


class TestNormalize:
    def test_strip_and_trailing_colon(self):
        assert normalize_keyword(" 价税合计： ") == "价税合计"

    def test_trailing_parenthesis(self):
        assert normalize_keyword("境内收货人（") == "境内收货人"


class TestExactMatch:
    def test_blob_with_colon(self):
        # 值止于下一锚点：需把后文关键字一并列入锚点列表
        ex = KeywordExtractor(["报关单号", "预录入编号"])
        cells = ex.extract("报关单号：090820241000039736 预录入编号：123")
        assert cells["报关单号"].value == "090820241000039736"
        assert cells["报关单号"].status == "confirmed"
        assert cells["报关单号"].source == "exact"

    def test_fullwidth_colon(self):
        ex = KeywordExtractor(["发票号码"])
        cells = ex.extract("发票号码：12345678")
        assert cells["发票号码"].value == "12345678"

    def test_no_separator(self):
        """_SEP 容忍无分隔符：'价税合计100.00' 直接精确命中"""
        ex = KeywordExtractor(["价税合计"])
        cells = ex.extract("价税合计100.00")
        assert cells["价税合计"].value == "100.00"

    def test_value_stops_at_next_anchor(self):
        ex = KeywordExtractor(["报关单号", "申报日期"])
        cells = ex.extract("报关单号 090820241000039736 申报日期 2026-01-01")
        assert cells["报关单号"].value == "090820241000039736"
        assert cells["申报日期"].value == "2026-01-01"

    def test_trailing_punct_cleaned(self):
        ex = KeywordExtractor(["毛重"])
        cells = ex.extract("毛重：1500.00千克。")
        assert cells["毛重"].value == "1500.00千克"

    def test_keyword_with_parenthesis_value(self):
        ex = KeywordExtractor(["境内收货人"])
        cells = ex.extract("境内收货人(91210213959942233Y) 电话：123")
        assert cells["境内收货人"].value == "91210213959942233Y"


class TestLooseMatch:
    def test_loose_cross_line_join(self):
        """精确取到行尾为空 → 宽松 L2 拼接下一行"""
        ex = KeywordExtractor(["价税合计"], loose=True, max_next_lines=1)
        cells = ex.extract("价税合计\n¥1,234.56")
        assert cells["价税合计"].value == "¥1,234.56"
        assert cells["价税合计"].status == "pending"
        assert cells["价税合计"].source == "loose"

    def test_loose_respects_max_next_lines(self):
        ex = KeywordExtractor(["价税合计"], loose=True, max_next_lines=1)
        cells = ex.extract("价税合计\n中间行\n¥1,234.56")
        assert cells["价税合计"].status == "not_found"  # 值在 2 行后超范围

    def test_loose_pure_chinese_line_rejected(self):
        """无数字且全汉字的行不可信（防抓正文）；含非汉字字符（如：）则可信"""
        ex = KeywordExtractor(["备注"])
        cells = ex.extract("备注\n合同副本一式两份")
        assert cells["备注"].status == "not_found"

    def test_loose_blob_exact_wins(self):
        """单行 blob：精确 pass 优先命中（_SEP 容忍无分隔符），宽松不覆盖"""
        ex = KeywordExtractor(["价税合计", "备注"])
        cells = ex.extract("价税合计¥1,234.56备注：无")
        assert cells["价税合计"].value == "¥1,234.56"
        assert cells["价税合计"].status == "confirmed"
        assert cells["备注"].value == "无"


class TestStatusMatrix:
    def test_not_found_empty_value(self):
        ex = KeywordExtractor(["不存在的字段"])
        cells = ex.extract("报关单号：123")
        c = cells["不存在的字段"]
        assert c.status == "not_found"
        assert c.value == ""
        assert c.source == "none"

    def test_empty_text_all_not_found(self):
        ex = KeywordExtractor(["a", "b"])
        cells = ex.extract("")
        assert all(c.status == "not_found" for c in cells.values())

    def test_regex_special_chars_safe(self):
        ex = KeywordExtractor(["金额(元)", "$total"])
        cells = ex.extract("金额(元)：100 $total：200")
        assert cells["金额(元)"].value == "100"
        assert cells["$total"].value == "200"

    def test_empty_keyword_skipped(self):
        ex = KeywordExtractor(["", "   "])
        assert ex.keywords == []
