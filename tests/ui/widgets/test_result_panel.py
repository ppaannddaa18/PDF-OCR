# tests/ui/widgets/test_result_panel.py
"""Task 12 重构回归测试：QTabBar 标签页版 ResultPanel

覆盖核心行为：
- 3 个标签页（Markdown预览/字段提取/表格数据）与 QStackedWidget 切换联动
- set_view 接口（按索引/名称切换；未知名称抛 ValueError）
- 导出按钮存在（📥 导出）
- load_result 填充三个视图（Markdown、字段表格、表格数据）及空数据兜底文案
- clear 清空所有视图
- 暗色主题下样式来自 ThemeManager（无硬编码颜色）
"""
import pandas as pd
import pytest
from PyQt6.QtGui import QColor

from app.models.page_result import PageResult, FinanceField, FinanceResult
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


class TestTabBar:
    def test_three_tabs_with_labels(self, qapp):
        panel = ResultPanel()
        assert panel.tab_bar.count() == 3
        assert [panel.tab_bar.tabText(i) for i in range(3)] == \
            ["Markdown预览", "字段提取", "表格数据"]

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
        assert panel.tab_bar.currentIndex() == 1
        assert panel.content_stack.currentIndex() == 1

    def test_set_view_unknown_name_raises(self, qapp):
        panel = ResultPanel()
        with pytest.raises(ValueError):
            panel.set_view("不存在的视图")

    def test_export_button_present(self, qapp):
        panel = ResultPanel()
        assert panel.export_btn.text() == "📥 导出"


class TestViews:
    def test_markdown_view_populated(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown="# 发票\n\n发票号码：12345678"))
        assert "发票号码：12345678" in panel._md_view.toPlainText()

    def test_markdown_fallback_empty(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(markdown=""))
        assert "(无内容)" in panel._md_view.toPlainText()

    def test_field_table_populated(self, qapp):
        panel = ResultPanel()
        panel.load_result(make_page(), make_finance())
        panel.set_view(1)
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
        panel.set_view(1)
        assert panel._field_table.rowCount() == 0

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
