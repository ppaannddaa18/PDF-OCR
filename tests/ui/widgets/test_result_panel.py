# tests/ui/widgets/test_result_panel.py
"""ResultPanel 回归测试（Task 12 QTabBar 版 + P0-a 结构化默认视图）

覆盖核心行为：
- 3 个标签页（字段提取/Markdown预览/表格数据），字段提取为默认 Tab 0，
  QStackedWidget 内容区顺序与标签顺序一致
- set_view 接口（按索引/名称切换；未知名称抛 ValueError）
- 结构化字段渲染：✓ 已确认 / ⚠ 待确认 / ⚠ 冲突 / — 未找到（主题色）
- 空回退：无结构化数据 → 字段表 0 行
- load_result 兼容：1 参（回退用 page_result.structured）与 2 参（旧 FinanceResult）
- field_selected 信号（Phase 4 hook）
- 导出按钮存在（📥 导出）
- clear 清空所有视图
- 暗色主题下样式来自 ThemeManager（无硬编码颜色）
"""
import pandas as pd
import pytest
from PyQt6.QtGui import QColor

from app.models.page_result import (
    PageResult, FinanceField, FinanceResult,
    StructuredField, StructuredResult,
)
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.result_panel import ResultPanel


def make_page(markdown="# 发票", tables=None):
    return PageResult(blocks=[], markdown=markdown, tables=tables or [])


def make_finance():
    return FinanceResult(fields=[
        FinanceField(label="发票号码", value="12345678", validated=True),
        FinanceField(label="开票日期", value="2024-01-01", validated=False,
                     validation_msg="格式不符"),
    ])


def make_structured():
    return StructuredResult(fields=[
        StructuredField(label="报关单号", value="090820241000039736", status="confirmed"),
        StructuredField(label="海关编号", value="0908", status="pending"),
        StructuredField(label="预录入编号", value="X1", status="conflict"),
        StructuredField(label="备注", value="", status="not_found"),
    ])


class TestTabBar:
    def test_three_tabs_new_order_default_field_tab(self, qapp):
        panel = ResultPanel()
        assert panel.tab_bar.count() == 3
        assert [panel.tab_bar.tabText(i) for i in range(3)] == \
            ["字段提取", "Markdown预览", "表格数据"]
        # 默认 Tab 0 = 字段提取
        assert panel.tab_bar.currentIndex() == 0

    def test_content_stack_order_matches_tabs(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown="# 发票"), make_finance())
        # 内容区顺序必须与 TAB_LABELS 一致（字段表在索引0）
        assert panel.content_stack.widget(0) is panel._field_table
        assert panel.content_stack.widget(1) is panel._md_view
        assert panel.content_stack.widget(2) is panel._table_view

    def test_tab_switch_syncs_stack(self, qapp):
        panel = ResultPanel()
        panel.tab_bar.setCurrentIndex(1)  # 先离开默认页0，确保信号触发
        for idx in range(3):
            panel.tab_bar.setCurrentIndex(idx)
            assert panel.content_stack.currentIndex() == idx

    def test_set_view_by_index(self, qapp):
        panel = ResultPanel()
        panel.set_view(2)
        assert panel.tab_bar.currentIndex() == 2
        assert panel.content_stack.currentIndex() == 2

    def test_set_view_by_name(self, qapp):
        panel = ResultPanel()
        panel.set_view("字段提取")
        assert panel.tab_bar.currentIndex() == 0
        assert panel.content_stack.currentIndex() == 0

    def test_set_view_unknown_name_raises(self, qapp):
        panel = ResultPanel()
        with pytest.raises(ValueError):
            panel.set_view("不存在的视图")

    def test_export_button_present(self, qapp):
        panel = ResultPanel()
        assert panel.export_btn.text() == "📥 导出"

    def test_export_button_uses_shared_primary_style(self, qapp):
        """P2-a：导出按钮复用共享 primary_qss（单一事实源）"""
        from app.ui.widgets.button_style import primary_qss
        panel = ResultPanel()
        assert panel.export_btn.styleSheet().strip() == primary_qss().strip()


class TestStructuredFields:
    def test_structured_fields_rendered_with_status_colors(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(), make_structured())
        assert panel.tab_bar.currentIndex() == 0  # 默认字段 Tab
        table = panel._field_table
        assert table.rowCount() == 4
        assert table.item(0, 0).text() == "报关单号"
        assert table.item(0, 1).text() == "090820241000039736"
        # confirmed → ✓ 已确认（success 色）
        assert table.item(0, 2).text() == "✓ 已确认"
        assert table.item(0, 2).foreground().color().name() == \
            QColor(ThemeManager.get_color('success')).name()
        # pending → ⚠ 待确认（warning 色）
        assert table.item(1, 2).text() == "⚠ 待确认"
        assert table.item(1, 2).foreground().color().name() == \
            QColor(ThemeManager.get_color('warning')).name()
        # conflict → ⚠ 冲突（error 色）
        assert table.item(2, 2).text() == "⚠ 冲突"
        assert table.item(2, 2).foreground().color().name() == \
            QColor(ThemeManager.get_color('error')).name()
        # not_found → — 未找到（text_disabled 色）
        assert table.item(3, 2).text() == "— 未找到"
        assert table.item(3, 2).foreground().color().name() == \
            QColor(ThemeManager.get_color('text_disabled')).name()

    def test_load_result_uses_page_result_structured(self, qapp):
        pr = make_page()
        pr.structured = make_structured()
        panel = ResultPanel()
        panel.load_result(pr)  # 1 参调用 → 回退用 page_result.structured
        assert panel._field_table.rowCount() == 4
        assert panel._field_table.item(0, 0).text() == "报关单号"

    def test_empty_fallback_none_structured(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page())  # structured_result=None, page_result.structured=None
        assert panel._field_table.rowCount() == 0

    def test_field_clicked_emits_signal(self, qapp):
        panel = ResultPanel()
        received = []
        panel.field_selected.connect(received.append)
        panel.load_result(make_page(), make_structured())
        panel._field_table.cellClicked.emit(2, 1)  # 模拟点击第 2 行
        assert received == [2]


class TestLegacyFinanceCompat:
    """旧 2 参 load_result(pr, FinanceResult) 路径保持可用"""

    def test_field_table_populated(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(), make_finance())
        panel.set_view(0)
        table = panel._field_table
        assert table.rowCount() == 2
        assert table.item(0, 0).text() == "发票号码"
        assert table.item(0, 1).text() == "12345678"
        # 已校验字段：✓
        assert table.item(0, 2).text() == "✓"
        # 未校验字段：⚠ 前缀 + 主题 error 色（非硬编码红色）
        assert table.item(1, 2).text().startswith("⚠")
        assert table.item(1, 2).foreground().color().name() == \
            QColor(ThemeManager.get_color('error')).name()

    def test_field_table_empty_finance(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page())  # finance_result=None
        panel.set_view(0)
        assert panel._field_table.rowCount() == 0


class TestViews:
    def test_markdown_view_populated(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown="# 发票\n\n发票号码：12345678"))
        panel.set_view(1)  # Markdown预览
        assert "发票号码：12345678" in panel._md_view.toPlainText()

    def test_markdown_fallback_empty(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown=""))
        panel.set_view(1)
        assert "(无内容)" in panel._md_view.toPlainText()

    def test_table_view_populated(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(tables=[pd.DataFrame({"a": [1], "b": [2]})]))
        panel.set_view(2)
        text = panel._table_view.toPlainText()
        assert "表格 1" in text
        assert "a" in text

    def test_table_view_no_tables(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(tables=[]))
        panel.set_view(2)
        assert "(未检测到表格)" in panel._table_view.toPlainText()

    def test_clear_empties_all(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown="# 发票"), make_finance())
        panel.set_view(1)
        panel.clear()
        assert panel._md_view.toPlainText() == ""
        assert panel._field_table.rowCount() == 0
        assert panel._table_view.toPlainText() == ""
        assert panel.tab_bar.count() == 3


class TestTheme:
    def test_dark_theme_styles_use_theme_colors(self, qapp):
        ThemeManager.set_theme('dark')
        panel = ResultPanel()
        export_ss = panel.export_btn.styleSheet()
        tab_ss = panel.tab_bar.styleSheet()
        # 暗色主题解析色应出现在样式中
        assert ThemeManager.get_color('primary') in export_ss
        assert ThemeManager.get_color('primary') in tab_ss
        assert ThemeManager.get_color('bg_hover') in tab_ss
        # 浅色主题特有值（硬编码残留）不应出现在暗色主题样式里
        assert "#f3f4f6" not in tab_ss
        assert "#f3f4f6" not in export_ss
