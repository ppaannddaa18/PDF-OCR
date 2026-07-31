import pytest
from PyQt6.QtWidgets import QApplication
from app.ui.widgets.empty_state import EmptyState


class TestEmptyState:
    def test_create_empty_state(self, qapp):
        state = EmptyState()
        assert state is not None

    def test_apply_variant_no_files(self, qapp):
        state = EmptyState('no_files')
        state.show()  # isVisible() 需要控件已显示（有效可见性含祖先链）
        assert state.icon_label.text() == '📄'
        assert state.title_label.text() == '暂无 PDF 文件'
        assert state.action_button.isVisible()
        assert state.action_button.text() == '上传 PDF'

    def test_apply_variant_no_preview(self, qapp):
        state = EmptyState('no_preview')
        state.show()
        assert state.icon_label.text() == '👁️'
        assert state.title_label.text() == 'PDF 预览区域'
        assert not state.action_button.isVisible()

    def test_custom_content(self, qapp):
        state = EmptyState()
        state.set_icon('🎯')
        state.set_title('自定义标题')
        state.set_description('自定义说明')
        assert state.icon_label.text() == '🎯'
        assert state.title_label.text() == '自定义标题'
        assert state.desc_label.text() == '自定义说明'

    def test_unknown_variant(self, qapp):
        with pytest.raises(ValueError, match="Unknown variant"):
            EmptyState('unknown')
