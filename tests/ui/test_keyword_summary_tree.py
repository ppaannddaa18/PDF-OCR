"""汇总树：分组折叠/状态底色/命中率徽标/编辑修正/核对信号"""
from PyQt6.QtCore import Qt

from app.models.keyword_result import (FileKeywordResult, PageKeywordResult,
                                       KeywordCell)
from app.ui.widgets.keyword_summary_tree import KeywordSummaryTree
from app.ui.theme_manager import ThemeManager


def _make_results():
    fr = FileKeywordResult(source_file="a.pdf")
    fr.pages.append(PageKeywordResult(page_no=1, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="100", status="pending"),
    }))
    # 页2：报关单号未找到（1/2=50% 低命中 ⚠）；价税合计命中（2/2=100% 无 ⚠）
    fr.pages.append(PageKeywordResult(page_no=2, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="", status="not_found"),
        "价税合计": KeywordCell(keyword="价税合计", value="200", status="confirmed"),
    }))
    return [fr]


def test_group_and_page_rows(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    assert tree.topLevelItemCount() == 1
    group = tree.topLevelItem(0)
    assert "a.pdf" in group.text(0)
    assert group.childCount() == 2
    assert "第 1 页" == group.child(0).text(0)
    assert group.isExpanded() is False  # 默认折叠


def test_cell_values_and_status_bg(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    row = tree.topLevelItem(0).child(0)
    assert row.text(2) == "0908"
    assert row.text(3) == "100"
    # confirmed → success_bg；pending → warning_bg
    assert row.background(2).color().name() == \
        ThemeManager.get_color('success_bg').lower()
    assert row.background(3).color().name() == \
        ThemeManager.get_color('warning_bg').lower()
    # not_found → 无底色、占位符 '—'
    row2 = tree.topLevelItem(0).child(1)
    assert row2.text(2) == "—"
    assert row2.background(2).style() == Qt.BrushStyle.NoBrush


def test_header_has_keyword_and_hit_ratio(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    h = tree.headerItem()
    assert "报关单号" in h.text(2)
    assert "%" in h.text(2)   # 命中率徽标
    assert "50%" in h.text(2)  # 报关单号命中 1/2 页
    assert "⚠" in h.text(2)    # 50% < 60% → 低命中警示
    assert "价税合计" in h.text(3)
    assert "100%" in h.text(3)  # 价税合计命中 2/2
    assert "⚠" not in h.text(3)


def test_double_click_emits_inspect(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    emitted = []
    tree.cell_inspect_requested.connect(lambda *a: emitted.append(a))
    row = tree.topLevelItem(0).child(0)
    tree._on_item_double_clicked(row, 2)
    assert emitted == [(0, 1, "报关单号")]


def test_edit_marks_manually_edited(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    row = tree.topLevelItem(0).child(0)
    col = 2
    cell = tree._results[0].pages[0].cells["报关单号"]
    row.setText(col, "9999")
    tree._on_item_changed(row, col)
    assert cell.value == "9999"
    assert cell.manually_edited is True
    assert row.background(col).color().name() == \
        ThemeManager.get_color('bg_selected').lower()


def test_theme_refresh_recolors(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    ThemeManager.set_theme('dark')
    row = tree.topLevelItem(0).child(0)
    assert row.background(2).color().name() == \
        ThemeManager.get_color('success_bg').lower()
