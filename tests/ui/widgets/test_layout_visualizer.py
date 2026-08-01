# tests/ui/widgets/test_layout_visualizer.py
"""Task 2 导航图测试：LayoutVisualizer

覆盖：
- _scene_rect_to_minimap 纯函数：1:1 图像像素场景下恒等映射 + 确定性
- set_viewport_rect 更新指示矩形（primary 半透明填充/边框）
- navigate 信号发射图像像素场景坐标
- update_blocks 跳过 GGUF 整页大框（纯导航模式）
"""
import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QRectF, QEvent
from PyQt6.QtGui import QMouseEvent
from PIL import Image

from app.models.page_result import Block
from app.ui.widgets.layout_visualizer import (
    LayoutVisualizer,
    _scene_rect_to_minimap,
)


def make_visualizer(qapp, size=(200, 300)):
    """创建已加载 200x300 图片的导航图"""
    viz = LayoutVisualizer()
    viz.resize(*size)
    viz.show()
    qapp.processEvents()
    img = Image.new('RGB', size, 'white')
    viz.set_page_image_from_pil(img)
    qapp.processEvents()
    return viz


class TestSceneRectToMinimap:
    def test_identity_mapping(self):
        """1:1 图像像素场景：恒等映射"""
        rect = QRectF(10, 20, 100, 50)
        out = _scene_rect_to_minimap(rect, 0.5)
        assert isinstance(out, QRectF)
        assert out == rect

    def test_returns_copy_not_same_object(self):
        rect = QRectF(1, 2, 3, 4)
        out = _scene_rect_to_minimap(rect, 1.0)
        out.setX(99)  # 修改返回值不影响输入
        assert rect.x() == 1.0

    def test_deterministic(self):
        """相同输入两次调用结果一致"""
        rect = QRectF(1.5, 2.5, 33.3, 44.4)
        m = 0.3
        assert _scene_rect_to_minimap(rect, m) == _scene_rect_to_minimap(rect, m)


class TestViewportIndicator:
    def test_indicator_created_on_top(self, qapp):
        viz = make_visualizer(qapp)
        assert viz.viewport_indicator is not None
        assert viz.viewport_indicator.zValue() >= 10

    def test_set_viewport_rect_updates_indicator(self, qapp):
        viz = make_visualizer(qapp)
        viz.set_viewport_rect(QRectF(10, 10, 100, 80))
        assert viz.viewport_indicator.rect() == QRectF(10, 10, 100, 80)
        assert viz.viewport_indicator.isVisible()

    def test_set_viewport_rect_hidden_by_default(self, qapp):
        viz = make_visualizer(qapp)
        assert not viz.viewport_indicator.isVisible()

    def test_set_viewport_rect_is_guarded_against_reentry(self, qapp):
        """_is_syncing 重入保护：内部不会再触发同步"""
        viz = make_visualizer(qapp)
        viz._is_syncing = True
        viz.set_viewport_rect(QRectF(5, 5, 20, 20))
        assert viz.viewport_indicator.rect() == QRectF(0, 0, 0, 0)  # 未更新
        assert not viz.viewport_indicator.isVisible()


class TestNavigate:
    def test_mouse_press_emits_scene_coords(self, qapp):
        """点击导航图发射 mapToScene 的场景坐标（即图像像素坐标）"""
        viz = make_visualizer(qapp)
        navigated = []
        viz.navigate.connect(navigated.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(50, 40),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        viz.mousePressEvent(press)
        assert len(navigated) == 1
        expected = viz.mapToScene(QPoint(50, 40))
        assert navigated[0] == expected

    def test_navigate_emits_qpointf(self, qapp):
        viz = make_visualizer(qapp)
        navigated = []
        viz.navigate.connect(navigated.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(10, 10),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        viz.mousePressEvent(press)
        assert isinstance(navigated[0], QPointF)


class TestUpdateBlocks:
    def test_whole_page_block_skipped(self, qapp):
        """GGUF 整页大框（覆盖 >=99% 页面）不绘制覆盖层"""
        viz = make_visualizer(qapp)
        viz.update_blocks([
            Block(block_type="text", content="whole page", bbox=[0, 0, 200, 300])
        ])
        assert viz._block_items == []

    def test_small_blocks_drawn(self, qapp):
        viz = make_visualizer(qapp)
        viz.update_blocks([
            Block(block_type="text", content="line", bbox=[10, 10, 100, 30])
        ])
        assert len(viz._block_items) == 1

    def test_none_bbox_skipped(self, qapp):
        viz = make_visualizer(qapp)
        viz.update_blocks([Block(block_type="table", content="x", bbox=None)])
        assert viz._block_items == []


class TestCloseButton:
    def test_close_button_emits_close_requested(self, qapp):
        viz = make_visualizer(qapp)
        emitted = []
        viz.close_requested.connect(lambda: emitted.append(True))
        viz._close_btn.click()
        assert emitted == [True]
