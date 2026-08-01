"""核对面板：渲染+文本层高亮+单元格表回写"""
from PIL import Image

from app.models.keyword_result import PageKeywordResult, KeywordCell
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
