import pandas as pd
import pytest

from app.core.keyword_exporter import KeywordExporter
from app.models.keyword_result import (FileKeywordResult, PageKeywordResult,
                                       KeywordCell)


def _make_results():
    fr1 = FileKeywordResult(source_file="a.pdf")
    fr1.pages.append(PageKeywordResult(page_no=1, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="", status="not_found"),
    }))
    fr2 = FileKeywordResult(source_file="b.pdf", success=False,
                            error_msg="无法打开文件")
    return [fr1, fr2]


def test_build_rows_one_row_per_page():
    rows = KeywordExporter()._build_rows(_make_results())
    assert len(rows) == 2  # a.pdf 1页 + b.pdf 无页（占位行）
    assert rows[0]["源文件"] == "a.pdf"
    assert rows[0]["页号"] == 1
    assert rows[0]["报关单号"] == "0908"
    assert rows[0]["报关单号_状态"] == "已确认"
    assert rows[0]["价税合计"] == ""
    assert rows[0]["价税合计_状态"] == "未找到"
    assert rows[1]["文件状态"].startswith("失败")


def test_include_status_off(tmp_path):
    rows = KeywordExporter()._build_rows(_make_results(), include_status=False)
    assert "报关单号_状态" not in rows[0]


def test_include_confidence_off_by_default():
    """默认不导出置信度列（旧导出格式不变）"""
    rows = KeywordExporter()._build_rows(_make_results())
    assert "报关单号_置信度" not in rows[0]


def test_include_confidence_adds_column():
    """include_confidence=True 时每关键字加置信度列（设置页开关接线点）"""
    rows = KeywordExporter()._build_rows(_make_results(), include_confidence=True)
    assert rows[0]["报关单号_置信度"] == 1.0
    assert rows[0]["价税合计_置信度"] == 1.0
    # 失败文件占位行无单元格 → 不添加列
    assert "报关单号_置信度" not in rows[1]


def test_to_excel_include_confidence_roundtrip(tmp_path):
    out = tmp_path / "kw_conf.xlsx"
    KeywordExporter().to_excel(_make_results(), str(out), include_confidence=True)
    df = pd.read_excel(out)
    assert "报关单号_置信度" in df.columns
    assert df.loc[0, "报关单号_置信度"] == 1.0


def test_to_excel_roundtrip(tmp_path):
    out = tmp_path / "kw.xlsx"
    KeywordExporter().to_excel(_make_results(), str(out))
    df = pd.read_excel(out)
    assert "源文件" in df.columns
    assert "报关单号" in df.columns
    assert len(df) == 2


def test_to_csv_has_bom(tmp_path):
    out = tmp_path / "kw.csv"
    KeywordExporter().to_csv(_make_results(), str(out))
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM
