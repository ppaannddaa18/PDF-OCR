# tests/ui/widgets/test_preprocess_toolbar.py
"""ImagePreprocessToolbar 可折叠设计测试（Task 10）"""
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QVBoxLayout, QWidget

from app.ui.widgets.preprocess_toolbar import ImagePreprocessToolbar

ANIM_WAIT = 300  # 200ms 动画时长 + 余量


def _shown_toolbar(qapp):
    """创建并显示工具栏（嵌入容器，使高度受 min/max 约束管理）"""
    container = QWidget()
    layout = QVBoxLayout(container)
    toolbar = ImagePreprocessToolbar()
    layout.addWidget(toolbar)
    container.resize(1000, 400)
    container.show()
    QTest.qWait(50)
    return container, toolbar


class TestCollapseExpand:
    def test_initial_collapsed_state(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        assert not toolbar.is_expanded()
        assert toolbar.height() == ImagePreprocessToolbar.COLLAPSED_HEIGHT
        assert not toolbar.detail_widget.isVisible()
        assert toolbar.expand_btn.text() == '▼'
        # 折叠态图标按钮可见
        assert all(btn.isVisible() for btn in toolbar.icon_buttons)

    def test_expand(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        assert toolbar.is_expanded()
        assert toolbar.height() == ImagePreprocessToolbar.EXPANDED_HEIGHT
        assert toolbar.detail_widget.isVisible()
        assert toolbar.expand_btn.text() == '▲'
        # 展开态图标按钮隐藏
        assert not any(btn.isVisible() for btn in toolbar.icon_buttons)

    def test_collapse_back(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        assert not toolbar.is_expanded()
        assert toolbar.height() == ImagePreprocessToolbar.COLLAPSED_HEIGHT
        assert not toolbar.detail_widget.isVisible()
        assert toolbar.expand_btn.text() == '▼'
        assert all(btn.isVisible() for btn in toolbar.icon_buttons)

    def test_icon_click_does_not_toggle_expand(self, qapp):
        """图标按钮只触发操作，不切换展开状态（仅展开按钮切换）"""
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.icon_buttons[0], Qt.MouseButton.LeftButton)
        assert not toolbar.is_expanded()
        assert toolbar.height() == ImagePreprocessToolbar.COLLAPSED_HEIGHT


class TestIconQuickActions:
    def test_rotate_icon_cycles_and_emits(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        emissions = []
        toolbar.image_changed.connect(lambda: emissions.append(1))
        QTest.mouseClick(toolbar.icon_buttons[0], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['rotation'] == 90
        assert toolbar.rotation_combo.currentIndex() == 1
        assert emissions == [1]
        QTest.mouseClick(toolbar.icon_buttons[0], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['rotation'] == 180
        assert emissions == [1, 1]

    def test_brightness_icon_cycles(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        emissions = []
        toolbar.image_changed.connect(lambda: emissions.append(1))
        QTest.mouseClick(toolbar.icon_buttons[1], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['brightness'] == 1.3
        assert toolbar.brightness_label.text() == '130%'
        QTest.mouseClick(toolbar.icon_buttons[1], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['brightness'] == 0.7
        assert emissions == [1, 1]

    def test_contrast_icon_cycles(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.icon_buttons[2], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['contrast'] == 1.3
        QTest.mouseClick(toolbar.icon_buttons[2], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['contrast'] == 0.7

    def test_threshold_icon_cycles(self, qapp):
        """二值化图标循环：关闭→128→180→自动→关闭"""
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.icon_buttons[3], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['threshold'] == 128
        QTest.mouseClick(toolbar.icon_buttons[3], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['threshold'] == 180
        QTest.mouseClick(toolbar.icon_buttons[3], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['threshold'] == -1
        QTest.mouseClick(toolbar.icon_buttons[3], Qt.MouseButton.LeftButton)
        assert toolbar.get_params()['threshold'] is None


class TestExistingControls:
    def test_slider_emits_image_changed(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        emissions = []
        toolbar.image_changed.connect(lambda: emissions.append(1))
        toolbar.brightness_slider.setValue(150)
        assert toolbar.get_params()['brightness'] == 1.5
        assert toolbar.brightness_label.text() == '150%'
        assert emissions == [1]

    def test_apply_to_all_signal(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        signals = []
        toolbar.apply_to_all.connect(lambda: signals.append(1))
        QTest.mouseClick(toolbar.btn_apply_all, Qt.MouseButton.LeftButton)
        assert signals == [1]

    def test_reset_signal_and_params(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        toolbar.brightness_slider.setValue(150)
        toolbar.rotation_combo.setCurrentIndex(1)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        signals = []
        toolbar.reset_requested.connect(lambda: signals.append(1))
        QTest.mouseClick(toolbar.btn_reset, Qt.MouseButton.LeftButton)
        assert signals == [1]
        params = toolbar.get_params()
        assert params['rotation'] == 0
        assert params['brightness'] == 1.0
        assert params['contrast'] == 1.0
        assert params['threshold'] is None
        assert params['auto_contrast_applied'] is False

    def test_auto_contrast_and_sharpen_signals(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        QTest.mouseClick(toolbar.expand_btn, Qt.MouseButton.LeftButton)
        QTest.qWait(ANIM_WAIT)
        signals = {'auto': 0, 'sharpen': 0}
        toolbar.apply_auto_contrast.connect(
            lambda: signals.__setitem__('auto', signals['auto'] + 1))
        toolbar.apply_sharpen.connect(
            lambda: signals.__setitem__('sharpen', signals['sharpen'] + 1))
        QTest.mouseClick(toolbar.btn_auto, Qt.MouseButton.LeftButton)
        QTest.mouseClick(toolbar.btn_sharpen, Qt.MouseButton.LeftButton)
        assert signals == {'auto': 1, 'sharpen': 1}
        assert toolbar.get_params()['auto_contrast_applied'] is True
        assert toolbar.get_params()['sharpen_applied'] is True

    def test_set_params_restores_without_emitting(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        emissions = []
        toolbar.image_changed.connect(lambda: emissions.append(1))
        toolbar.set_params({
            'rotation': 90,
            'brightness': 1.3,
            'contrast': 0.7,
            'threshold': 128,
            'auto_contrast_applied': True,
            'sharpen_applied': False,
        })
        assert emissions == []
        assert toolbar.get_params()['rotation'] == 90
        assert toolbar.rotation_combo.currentIndex() == 1
        assert toolbar.brightness_slider.value() == 130
        assert toolbar.contrast_slider.value() == 70
        assert toolbar.threshold_combo.currentIndex() == 1

    def test_set_enabled(self, qapp):
        _, toolbar = _shown_toolbar(qapp)
        toolbar.set_enabled(False)
        assert not toolbar.btn_auto.isEnabled()
        assert not toolbar.btn_apply_all.isEnabled()
        assert not toolbar.icon_buttons[0].isEnabled()
        assert not toolbar.expand_btn.isEnabled()
        toolbar.set_enabled(True)
        assert toolbar.btn_auto.isEnabled()
        assert toolbar.icon_buttons[0].isEnabled()
