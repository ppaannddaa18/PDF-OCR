"""OcrResultViews 组件测试（offscreen）

复用 tests/ui/conftest.py 的会话级 qapp fixture（不定义本地重复 fixture）。
"""
from pathlib import Path
import sys

import pytest
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models.page_result import PageResult, Block
from app.ui.widgets.ocr_result_views import OcrDocView, OcrJsonView, _render_markdown


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


def test_boxes_toggle_sync_and_replay(qapp):
    """I1-I：检测框复选框与渲染状态同步：
    取消勾选 → show_page 不重新高亮；重新勾选 → 当前页检测框立即重放"""
    view = OcrDocView()
    view.show_page(_page(), Image.new("RGB", (100, 100)))  # 默认勾选 → 高亮
    assert len(view.canvas._highlight_items) == 2

    view.boxes_check.setChecked(False)                     # 取消勾选 → 清空
    assert not view.canvas._highlight_items

    # 不传 show_boxes：跟随复选框状态，不重新高亮
    view.show_page(_page(), Image.new("RGB", (100, 100)))
    assert not view.canvas._highlight_items

    # 重新勾选：_last_result 重放，当前页检测框立即回来（无需翻页）
    view.boxes_check.setChecked(True)
    assert len(view.canvas._highlight_items) == 2


def test_show_page_explicit_show_boxes_syncs_checkbox(qapp):
    """显式传 show_boxes 时同步复选框，_show_boxes 与勾选态始终一致"""
    view = OcrDocView()
    view.boxes_check.setChecked(False)
    view.show_page(_page(), Image.new("RGB", (100, 100)), show_boxes=True)
    assert view.boxes_check.isChecked()
    assert len(view.canvas._highlight_items) == 2


def test_json_view_tree(qapp):
    view = OcrJsonView()
    view.show_result({"parsing_res_list": [
        {"block_label": "paragraph", "block_content": "Hello"}]})
    # 树中应包含键与值文本
    all_text = "\n".join(view.topLevelItem(i).text(0)
                         for i in range(view.topLevelItemCount()))
    assert "parsing_res_list" in all_text


def test_json_view_scalar_leaves_keep_keys(qapp):
    """叶子节点键值同显：col0 为 "键: 值"，键不被值覆盖"""
    view = OcrJsonView()
    view.show_result({"parsing_res_list": [
        {"block_label": "paragraph", "block_content": "Hello"},
        {"score": 0.97}]})

    def collect(item):
        yield item.text(0)
        for i in range(item.childCount()):
            yield from collect(item.child(i))

    all_text = "\n".join(t
                         for i in range(view.topLevelItemCount())
                         for t in collect(view.topLevelItem(i)))
    assert "parsing_res_list" in all_text          # 顶层键仍在
    assert "block_label: paragraph" in all_text    # 嵌套标量键值同显
    assert "block_content: Hello" in all_text
    assert "score: 0.97" in all_text


def test_doc_view_empty_result_placeholder(qapp):
    """T11：无 markdown 无 blocks → 灰色占位文案，不渲染空视图"""
    view = OcrDocView()
    view.show_page(PageResult(blocks=[], markdown="", image_size=(10, 10)),
                   Image.new("RGB", (10, 10)))
    assert "无可解析内容" in view.text()
    # 有内容时占位不出现
    view.show_page(PageResult(blocks=[], markdown="Hello", image_size=(10, 10)),
                   Image.new("RGB", (10, 10)))
    assert "无可解析内容" not in view.text()


def test_json_view_empty_placeholder(qapp):
    """T11：空 dict → 占位行（无 JSON 数据）"""
    view = OcrJsonView()
    view.show_result({})
    assert view.topLevelItemCount() == 1
    assert "（无 JSON 数据）" in view.topLevelItem(0).text(0)


def test_json_view_scalar_root_single_row(qapp):
    """T11：非 dict 标量根值单行显示（不逐字符展开）"""
    view = OcrJsonView()
    view.show_result(42)
    assert view.topLevelItemCount() == 1
    assert view.topLevelItem(0).text(0) == "42"
    view.show_result("hello")
    assert view.topLevelItemCount() == 1
    assert view.topLevelItem(0).text(0) == "hello"


def test_json_view_list_root_expands(qapp):
    """T11：list 根值按索引铺开（标量叶子键值同显）"""
    view = OcrJsonView()
    view.show_result(["a", 1])
    assert view.topLevelItemCount() == 2
    assert view.topLevelItem(0).text(0) == "[0]: a"
    assert view.topLevelItem(1).text(0) == "[1]: 1"
    assert view.topLevelItem(0).text(1) == "str"


def test_json_view_ndarray_marker_single_line(qapp):
    """T11：__ndarray__ 降级标记 → 单行 shape/dtype 显示，不展开 shape 列表"""
    view = OcrJsonView()
    view.show_result({"output_img": {"__ndarray__": [1, 3, 1920, 1080],
                                     "dtype": "float32"}})
    item = view.topLevelItem(0)
    assert item.childCount() == 0                     # 不展开子节点
    assert "（数组已降级）" in item.text(0)
    assert "shape=[1, 3, 1920, 1080]" in item.text(0)
    assert "dtype=float32" in item.text(0)


def test_render_markdown_heading_requires_space(qapp):
    """T11：标题要求 # 后随空白——"#Title"、"###" 不渲染为标题"""
    html = _render_markdown("#Title\n###\n# Real\n")
    assert "<h2>Real</h2>" in html
    assert "<h2>Title</h2>" not in html
    assert "<h2></h2>" not in html
    assert "<p>#Title</p>" in html                    # 无空格 # 按段落渲染


def test_render_markdown_table_requires_both_pipes(qapp):
    """T11：表格行要求两侧 |——"| a | b |" 等宽，"中|间" 按段落"""
    html = _render_markdown("| a | b |\nmid|dle\nno|pipe\n")
    assert "<pre>| a | b |</pre>" in html
    assert "<pre>mid|dle</pre>" not in html
    assert "<p>mid|dle</p>" in html
    assert "<p>no|pipe</p>" in html
