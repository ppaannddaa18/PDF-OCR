# tests/ui/widgets/test_slidable_panel.py
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget, QLabel
from app.ui.widgets.slidable_panel import SlidablePanel


class TestSlidablePanel:
    def test_create_panel(self, qapp):
        panel = SlidablePanel()
        # 未显示/未布局的 QWidget 的 width() 不反映宽度约束（可能返回默认值），
        # 按 Qt 语义显式 resize 到 panel_width 后再断言，保持"初始宽度 = 320"的意图
        panel.resize(320, panel.height())
        assert panel.width() == 320
        assert panel.minimumWidth() == 280
        assert panel.maximumWidth() == 480

    def test_set_content(self, qapp):
        panel = SlidablePanel()
        content = QLabel('Test Content')
        panel.set_content(content)
        assert panel._content_widget == content

    def test_set_title(self, qapp):
        panel = SlidablePanel()
        panel.set_title('测试标题')
        assert panel.title_label.text() == '测试标题'

    def test_slide_out(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        panel = SlidablePanel(parent)
        panel.slide_out()
        assert not panel.is_visible()

    def test_signal(self, qapp):
        panel = SlidablePanel()
        signals = []
        panel.visible_changed.connect(lambda x: signals.append(x))
        panel.slide_out()
        assert signals == [False]

    def test_custom_widths(self, qapp):
        panel = SlidablePanel(panel_width=400, min_width=360, max_width=600)
        assert panel._panel_width == 400
        assert panel._min_width == 360
        assert panel._max_width == 600

    def test_panel_width_param_effective(self, qapp):
        """回归：panel_width 构造参数必须真实生效（曾被后续 min/max 覆盖失效）

        不能只靠构造后先 resize 再断言——resize 值在 [min, max] 范围内会被约束
        合法化，区分不出参数是否生效。修复前 setFixedWidth(panel_width) 的固定
        约束在 show 前被后续 min/max 覆盖，show() 触发布局激活后宽度塌缩到
        minimumWidth（280）；修复后初始宽度显式设为 panel_width，show 后保持。
        """
        panel = SlidablePanel(panel_width=300)
        panel.show()
        assert panel.width() == 300

        default_panel = SlidablePanel()
        default_panel.show()
        assert default_panel.width() == 320

    def test_slide_animation_moves_panel_in_and_out(self, qapp):
        """动画验证：滑出后移出右边界并隐藏，滑入后回到右边缘内侧"""
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        panel = SlidablePanel(parent)
        panel.resize(320, 480)
        parent.show()
        panel.show()

        panel.slide_out()
        QTest.qWait(400)  # 等待 250ms 动画完成
        assert not panel.is_visible()
        assert panel.x() == 800

        panel.slide_in()
        QTest.qWait(400)
        assert panel.is_visible()
        assert panel.x() == 800 - 320

    def test_slide_in_emits_visible_changed(self, qapp):
        panel = SlidablePanel()
        signals = []
        panel.visible_changed.connect(lambda x: signals.append(x))
        panel.slide_out()
        panel.slide_in()
        assert signals == [False, True]
