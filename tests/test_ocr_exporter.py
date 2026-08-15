"""OcrExporter 导出测试"""
import json
from pathlib import Path
import pytest
from app.core.ocr_exporter import (export_txt, export_markdown, export_json)
from app.models.page_result import PageResult, Block


def _pages():
    return [
        PageResult(blocks=[Block("text", "Hello", [0, 0, 1, 1])],
                   markdown="# Title\n\nHello", raw_json={"k": "v"},
                   image_size=(100, 100)),
        PageResult(blocks=[], markdown="Second", raw_json={"k2": 2}),
    ]


def test_export_txt(tmp_path):
    files = export_txt(_pages(), str(tmp_path), "doc")
    assert len(files) == 2
    assert (tmp_path / "doc_p1.txt").read_text(encoding="utf-8") == "Hello"
    assert (tmp_path / "doc_p2.txt").read_text(encoding="utf-8") == "Second"


def test_export_txt_preserves_body_punctuation(tmp_path):
    """T10：只剔除行首 markdown 语法——正文中的 -/#/*/`/~ 等字符保留，
    日期/编号/代码符号不被破坏；标题行仍整行剔除"""
    pages = [PageResult(
        blocks=[],
        markdown="# 标题\n\n"
                 "会议日期：2024-08-15\n"
                 "C# 语言 入门\n"
                 "编号 1234-5678\n"
                 "- 列表项 `code` 保留\n"
                 "> 引用行",
        raw_json={})]
    files = export_txt(pages, str(tmp_path), "doc")
    text = (tmp_path / "doc_p1.txt").read_text(encoding="utf-8")
    assert "2024-08-15" in text          # 日期中的连字符保留
    assert "C# 语言 入门" in text         # 正文 # 保留
    assert "1234-5678" in text           # 编号连字符保留
    assert "列表项 `code` 保留" in text    # 行首 "- " 剥除，正文符号保留
    assert "引用行" in text               # 行首 "> " 剥除
    assert "标题" not in text             # 标题行整行剔除
    assert "20240815" not in text         # 连字符未被删除（无日期变形）


def test_export_markdown_merged(tmp_path):
    files = export_markdown(_pages(), str(tmp_path), "doc")
    text = (tmp_path / "doc.md").read_text(encoding="utf-8")
    assert "# Title" in text and "Second" in text


def test_export_json(tmp_path):
    files = export_json(_pages(), str(tmp_path), "doc")
    data = json.loads((tmp_path / "doc_p1.json").read_text(encoding="utf-8"))
    assert data["k"] == "v"
    data2 = json.loads((tmp_path / "doc_p2.json").read_text(encoding="utf-8"))
    assert data2["k2"] == 2
