"""OcrResultViews 组件测试（offscreen）

复用 tests/ui/conftest.py 的会话级 qapp fixture（不定义本地重复 fixture）。
"""
from pathlib import Path
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models.page_result import PageResult, Block
from app.ui.widgets.ocr_result_views import OcrDocView, OcrJsonView


def _page():
    return PageResult(
        blocks=[Block("text", "Hello", [0, 0, 10, 10]),
                Block("table", "| a | b |", [0, 0, 10, 10])],
        markdown="# Title\n\nHello\n\n| a | b |",
        raw_json={"parsing_res_list": [{"block_label": "paragraph",
                                        "block_content": "Hello"}]},
        image_size=(100, 100))


def test_doc_view_renders_text(qapp):
    view = OcrDocView()
    view.show_page(_page(), Image.new("RGB", (100, 100)), show_boxes=True)
    assert "Title" in view.text()
    assert "Hello" in view.text()


def test_json_view_tree(qapp):
    view = OcrJsonView()
    view.show_result({"parsing_res_list": [
        {"block_label": "paragraph", "block_content": "Hello"}]})
    # 树中应包含键与值文本
    all_text = "\n".join(view.topLevelItem(i).text(0)
                         for i in range(view.topLevelItemCount()))
    assert "parsing_res_list" in all_text
