"""核对面板：渲染+文本层高亮+OCR 行盒兜底+单元格表回写"""
from PIL import Image

from app.models.keyword_result import PageKeywordResult, KeywordCell
from app.models.page_result import Block
from app.ui.widgets.keyword_inspection_panel import KeywordInspectionPanel


class FakeLoader:
    def render_page(self, path, page_num):
        return Image.new("RGB", (200, 100), "white")


def _cells():
    return {
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="", status="not_found"),
    }


def test_show_inspection_fills_table_and_title(qapp):
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells(), "报关单号")
    assert "a.pdf" in panel.title_label.text()
    assert panel.cell_table.rowCount() == 2
    assert panel.cell_table.item(0, 0).text() == "报关单号"
    assert panel.cell_table.item(0, 1).text() == "0908"


def test_no_text_layer_renders_without_highlight(qapp):
    """无文本层的图（fake）→ 只渲染不高亮，不崩溃"""
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells())
    assert panel.canvas.pixmap_item is not None


def test_edit_cell_emits_value_edited(qapp):
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells())
    emitted = []
    panel.value_edited.connect(lambda *a: emitted.append(a))
    panel.cell_table.item(0, 1).setText("9999")  # 触发 itemChanged → value_edited
    assert emitted == [(0, 1, "报关单号", "9999")]


# ── OCR 检测层行盒兜底高亮 ───────────────────────────────────

def _boxes():
    return [
        Block(block_type="text", content="报关单号：090820241000039736",
              bbox=[100, 100, 400, 140]),
        Block(block_type="text", content="价税合计：100.00",
              bbox=[100, 200, 350, 240]),
    ]


def test_no_text_layer_with_line_boxes_draws_highlight(qapp, monkeypatch):
    """无文本层 + line_boxes → 画 OCR 行盒（focus 命中行主题色，其余淡色）"""
    panel = KeywordInspectionPanel()
    drawn = []
    monkeypatch.setattr(panel.canvas, "highlight_bbox",
                        lambda bbox, color=None: drawn.append((list(bbox), color)))
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells(),
                          "报关单号", _boxes())
    # 文本层定位必然失败（fake pdf）→ 走 OCR 行盒；焦点值 "0908" 命中行1
    assert len(drawn) == 2
    hit_bbox, hit_color = drawn[0]
    assert hit_bbox == [100.0, 100.0, 400.0, 140.0]
    assert hit_color is None  # None = 主题色 primary
    assert drawn[1][1] is not None  # 未命中行淡色


def test_line_boxes_no_focus_match_all_muted(qapp, monkeypatch):
    """focus 值与关键字都未命中任何行 → 全部行淡色画出（识别版面兜底）"""
    panel = KeywordInspectionPanel()
    drawn = []
    monkeypatch.setattr(panel.canvas, "highlight_bbox",
                        lambda bbox, color=None: drawn.append((list(bbox), color)))
    cells = {"不存在的关键字": KeywordCell(keyword="不存在的关键字", value="9999",
                                           status="confirmed")}
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, cells,
                          "不存在的关键字", _boxes())
    assert len(drawn) == 2
    assert all(color is not None for _, color in drawn)


def test_line_boxes_focus_matches_keyword_not_value(qapp, monkeypatch):
    """值未命中时退而匹配关键字本身（"价税合计" → 行2 高亮）"""
    panel = KeywordInspectionPanel()
    drawn = []
    monkeypatch.setattr(panel.canvas, "highlight_bbox",
                        lambda bbox, color=None: drawn.append((list(bbox), color)))
    cells = {"价税合计": KeywordCell(keyword="价税合计", value="ABC 跨行值",
                                     status="confirmed")}
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, cells,
                          "价税合计", _boxes())
    assert len(drawn) == 2
    assert drawn[0][1] is not None  # 行1 未命中 → 淡色
    assert drawn[1][0] == [100.0, 200.0, 350.0, 240.0]  # 关键字所在行
    assert drawn[1][1] is None  # 命中 → 主题色


def test_no_line_boxes_no_draw(qapp, monkeypatch):
    """无 line_boxes → 不画任何 OCR 框（兼容旧调用）"""
    panel = KeywordInspectionPanel()
    drawn = []
    monkeypatch.setattr(panel.canvas, "highlight_bbox",
                        lambda bbox, color=None: drawn.append(bbox))
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells(), "报关单号")
    assert drawn == []
