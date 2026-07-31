# tests/ui/widgets/test_field_panel.py
"""Task 11 重构回归测试：紧凑版 FieldPanel

覆盖核心行为：
- 空状态（EmptyState 'no_fields'）显示/隐藏
- 32px 行高与表格数据（add_region 行/列内容）
- 清空操作（clear_current / clear_all / _delete 及对应信号）
- 字段名编辑、字段类型变更的信号与数据同步
- build_template / load_template 往返
- show_preview_result（验证失败/低置信度样式 + tooltip + 详情展示）
"""
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QPushButton

from app.models.region import Region
from app.models.ocr_result import FieldResult, FileResult
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.field_panel import FieldPanel, ROW_HEIGHT


def make_region(rid: str, name: str, ftype: str = "text") -> Region:
    return Region(
        id=rid, field_name=name,
        x=0.1, y=0.1, w=0.2, h=0.2, field_type=ftype,
    )


def make_result(rid: str, name: str, text: str, confidence: float = 0.95):
    return FileResult(
        source_file="a.pdf",
        fields={name: FieldResult(
            field_name=name, text=text, confidence=confidence, region_id=rid,
        )},
    )


class TestEmptyState:
    def test_empty_state_visible_initially(self, qapp):
        panel = FieldPanel()
        panel.show()
        assert panel.empty_state.isVisible()
        assert not panel.table.isVisible()

    def test_empty_state_hidden_after_add(self, qapp):
        panel = FieldPanel()
        panel.show()
        panel.add_region(make_region('r1', '姓名'))
        assert not panel.empty_state.isVisible()
        assert panel.table.isVisible()

    def test_empty_state_returns_after_clear_all(self, qapp):
        panel = FieldPanel()
        panel.show()
        panel.add_region(make_region('r1', '姓名'))
        panel.clear_all()
        assert panel.empty_state.isVisible()
        assert not panel.table.isVisible()

    def test_empty_state_returns_after_delete(self, qapp):
        panel = FieldPanel()
        panel.show()
        panel.add_region(make_region('r1', '姓名'))
        panel._delete('r1')
        assert panel.empty_state.isVisible()
        assert not panel.table.isVisible()


class TestCompactTable:
    def test_row_height_is_32(self, qapp):
        """32px 行高（brief 核心视觉要求，确定性断言）"""
        panel = FieldPanel()
        panel.show()
        assert panel.table.verticalHeader().defaultSectionSize() == ROW_HEIGHT
        panel.add_region(make_region('r1', '姓名'))
        qapp.processEvents()
        assert panel.table.rowHeight(0) == ROW_HEIGHT

    def test_add_region_populates_row(self, qapp):
        panel = FieldPanel()
        panel.add_region(make_region('r1', '姓名', 'text'))
        assert panel.table.rowCount() == 1
        name_item = panel.table.item(0, 0)
        assert name_item.text() == '姓名'
        assert name_item.data(Qt.ItemDataRole.UserRole) == 'r1'
        combo = panel.table.cellWidget(0, 1)
        assert combo.currentText() == 'text'
        delete_btn = panel.table.cellWidget(0, 3)
        assert isinstance(delete_btn, QPushButton)
        assert delete_btn.text() == '删除'

    def test_vertical_header_hidden(self, qapp):
        """紧凑设计：隐藏行号列"""
        panel = FieldPanel()
        assert not panel.table.verticalHeader().isVisible()

    def test_hardcoded_color_absent_from_stylesheets(self, qapp):
        """样式表颜色全部来自 ThemeManager（用主题色反查，防止硬编码回归）"""
        panel = FieldPanel()
        qss = panel.table.styleSheet() + panel.clear_current_btn.styleSheet()
        for role in ('bg_surface', 'bg_hover', 'border', 'text_primary',
                     'text_secondary', 'bg_selected'):
            assert ThemeManager.get_color(role) in qss, f"角色 {role} 未出现在样式表中"


class TestClearOperations:
    def test_clear_current_emits_current_cleared(self, qapp):
        panel = FieldPanel()
        emitted = []
        panel.current_cleared.connect(lambda: emitted.append(True))
        panel.add_region(make_region('r1', '姓名'))
        panel.clear_current()
        assert emitted == [True]

    def test_clear_all_empties_regions_and_table(self, qapp):
        panel = FieldPanel()
        changed = []
        panel.region_changed.connect(changed.append)
        panel.add_region(make_region('r1', '姓名'))
        panel.add_region(make_region('r2', '金额', 'number'))
        panel.clear_all()
        assert panel.regions == {}
        assert panel._preview_results == {}
        assert panel.table.rowCount() == 0
        assert changed[-1] == []

    def test_delete_emits_region_deleted(self, qapp):
        panel = FieldPanel()
        deleted = []
        panel.region_deleted.connect(deleted.append)
        panel.add_region(make_region('r1', '姓名'))
        panel._delete('r1')
        assert deleted == ['r1']
        assert 'r1' not in panel.regions
        assert panel.table.rowCount() == 0


class TestFieldEdit:
    def test_field_name_edit_updates_region_and_signal(self, qapp):
        panel = FieldPanel()
        changed = []
        panel.field_name_changed.connect(
            lambda rid, old, new: changed.append((rid, old, new)))
        panel.add_region(make_region('r1', '姓名'))
        # 编辑字段名（触发 itemChanged）
        panel.table.item(0, 0).setText('客户姓名')
        assert panel.regions['r1'].field_name == '客户姓名'
        assert changed == [('r1', '姓名', '客户姓名')]

    def test_field_type_change_updates_region(self, qapp):
        panel = FieldPanel()
        changed = []
        panel.region_changed.connect(changed.append)
        panel.add_region(make_region('r1', '金额', 'text'))
        combo = panel.table.cellWidget(0, 1)
        combo.setCurrentText('number')
        assert panel.regions['r1'].field_type == 'number'
        assert len(changed) == 1  # 类型变更触发一次保存信号


class TestTemplate:
    def test_build_template_roundtrip(self, qapp):
        panel = FieldPanel()
        panel.add_region(make_region('r1', '姓名', 'text'))
        panel.add_region(make_region('r2', '金额', 'number'))
        template = panel.build_template()
        assert len(template.regions) == 2
        # 修改返回的模板不应影响面板内数据（深拷贝）
        template.regions[0].field_name = '改过的名字'
        assert panel.regions['r1'].field_name == '姓名'

        # 载入新面板
        panel2 = FieldPanel()
        changed = []
        panel2.region_changed.connect(changed.append)
        panel2.load_template(template)
        assert panel2.table.rowCount() == 2
        assert panel2.regions['r1'].field_name == '改过的名字'
        assert len(changed) == 1  # load_template 仅发射一次信号


class TestPreviewResult:
    def test_show_preview_result_valid(self, qapp):
        panel = FieldPanel()
        panel.add_region(make_region('r1', '姓名', 'text'))
        panel.show_preview_result(make_result('r1', '姓名', '张三'))
        item = panel.table.item(0, 2)
        assert item.text() == '张三'
        assert '置信度' in item.toolTip()
        assert 'r1' in panel._preview_results

    def test_show_preview_result_validation_error_styled(self, qapp):
        """数字类型收到非数字内容 → 错误色样式（ThemeManager 角色色）"""
        panel = FieldPanel()
        panel.add_region(make_region('r1', '金额', 'number'))
        panel.show_preview_result(make_result('r1', '金额', 'abc123'))
        item = panel.table.item(0, 2)
        assert item.background().color().name() == \
            ThemeManager.get_color('error').lower()
        assert item.foreground().color().name() == \
            ThemeManager.get_color('error').lower()
        assert '格式错误' in item.toolTip()

    def test_show_preview_result_low_confidence_styled(self, qapp):
        """低置信度 → 警告色背景"""
        panel = FieldPanel()
        panel.add_region(make_region('r1', '姓名', 'text'))
        panel.show_preview_result(make_result('r1', '姓名', '张三', 0.5))
        item = panel.table.item(0, 2)
        assert item.background().color().name() == \
            ThemeManager.get_color('warning').lower()
        assert '置信度较低' in item.toolTip()

    def test_cell_click_shows_detail(self, qapp):
        panel = FieldPanel()
        panel.show()
        panel.add_region(make_region('r1', '姓名', 'text'))
        panel.show_preview_result(make_result('r1', '姓名', '张三'))
        panel._on_cell_clicked(0, 2)
        assert panel.detail_widget.isVisible()
        assert '内容' in panel.detail_content.text()
        assert '置信度' in panel.detail_confidence.text()
