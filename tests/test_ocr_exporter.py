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
