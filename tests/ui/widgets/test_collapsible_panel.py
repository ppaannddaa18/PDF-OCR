# tests/ui/widgets/test_collapsible_panel.py
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QLabel
from app.ui.widgets.collapsible_panel import CollapsiblePanel


class TestCollapsiblePanel:
    def test_create_panel(self, qapp):
        panel = CollapsiblePanel()
        # 未显示/未布局的 QWidget 的 width() 不反映宽度约束（可能返回默认值），
        # 按 Qt 语义显式 resize 到 minimumWidth 后再断言，保持"初始宽度 = expanded_width"的意图
        panel.resize(panel.minimumWidth(), panel.height())
        assert panel.width() == 240
        assert not panel.is_collapsed()

    def test_set_content(self, qapp):
        panel = CollapsiblePanel()
        content = QLabel('Test Content')
        panel.set_content(content)
        assert panel._content_widget == content

    def test_collapse(self, qapp):
        panel = CollapsiblePanel()
        panel.collapse()
        assert panel.is_collapsed()
        assert panel.toggle_button.text() == '▶'

    def test_expand(self, qapp):
        panel = CollapsiblePanel()
        panel.collapse()
        panel.expand()
        assert not panel.is_collapsed()
        assert panel.toggle_button.text() == '◀'

    def test_toggle(self, qapp):
        panel = CollapsiblePanel()
        panel.toggle()
        assert panel.is_collapsed()
        panel.toggle()
        assert not panel.is_collapsed()

    def test_signal(self, qapp):
        panel = CollapsiblePanel()
        signals = []
        panel.collapsed_changed.connect(lambda x: signals.append(x))
        panel.collapse()
        assert signals == [True]
        panel.expand()
        assert signals == [True, False]

    def test_custom_widths(self, qapp):
        panel = CollapsiblePanel(expanded_width=300, collapsed_width=60)
        assert panel._expanded_width == 300
        assert panel._collapsed_width == 60

    def test_width_actually_changes_after_collapse_and_expand(self, qapp):
        """动画修复验证：折叠/展开后面板宽度必须真实变化到目标值"""
        panel = CollapsiblePanel()
        panel.show()
        panel.resize(panel.minimumWidth(), panel.height())
        assert panel.width() == 240

        panel.collapse()
        QTest.qWait(400)  # 等待 300ms 动画完成
        assert panel.width() == 48

        panel.expand()
        QTest.qWait(400)
        assert panel.width() == 240
