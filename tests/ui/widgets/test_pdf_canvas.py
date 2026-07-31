# tests/ui/widgets/test_pdf_canvas.py
"""Task 9 重构回归测试：PdfCanvas

覆盖核心新行为：
- 空状态（EmptyState 'no_preview'）显示/隐藏
- 缩放比例标签与 transform 同步、滚轮更新、点击恢复 100%
- 10px 网格吸附（函数级 + 框选集成）
- 框选/调整大小时区域尺寸提示显示与隐藏
- 浮动工具栏悬停显隐与按钮功能
- 主题化背景（禁止硬编码 #fafafa）
"""
import pytest
from PyQt6.QtCore import Qt, QPoint, QPointF, QEvent, QRectF
from PyQt6.QtGui import QMouseEvent, QWheelEvent
from PyQt6.QtTest import QTest
from PIL import Image

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.pdf_canvas import PdfCanvas, GRID_SIZE


def make_canvas(qapp, size=(200, 100)):
    """创建已加载图片的画布，视图缩放复位为 1:1（场景坐标 == 视口坐标）

    关键：视口尺寸 == 场景尺寸 且无边框，避免 QGraphicsView 默认 AlignCenter
    在场景小于视口时引入 (-offset, -offset) 的设备坐标偏移。
    """
    from PyQt6.QtWidgets import QFrame

    canvas = PdfCanvas()
    canvas.setFrameShape(QFrame.Shape.NoFrame)
    canvas.setFixedSize(*size)
    canvas.show()
    qapp.processEvents()
    img = Image.new('RGB', size, 'white')
    canvas.load_image(img)
    canvas.resetTransform()
    canvas._update_zoom_label()  # 复位后同步缩放标签为 '100%'
    qapp.processEvents()
    return canvas


class TestEmptyState:
    def test_empty_state_visible_initially(self, qapp):
        canvas = PdfCanvas()
        canvas.show()
        assert canvas.empty_state.isVisible()
        assert not canvas.zoom_label.isVisible()
        assert not canvas.floating_toolbar.isVisible()

    def test_empty_state_hidden_after_load_image(self, qapp):
        canvas = make_canvas(qapp)
        assert not canvas.empty_state.isVisible()
        assert canvas.zoom_label.isVisible()

    def test_clear_restores_empty_state(self, qapp):
        canvas = make_canvas(qapp)
        canvas.clear()
        assert canvas.empty_state.isVisible()
        assert not canvas.zoom_label.isVisible()
        assert canvas.region_items == {}

    def test_canvas_background_uses_theme(self, qapp):
        canvas = PdfCanvas()
        assert ThemeManager.get_color('bg_primary') in canvas.styleSheet()
        assert '#fafafa' not in canvas.styleSheet()


class TestZoomLabel:
    def test_zoom_label_matches_transform(self, qapp):
        canvas = make_canvas(qapp)
        scale = canvas.transform().m11()
        assert canvas.zoom_label.text() == f"{round(scale * 100)}%"

    def test_zoom_label_updates_after_zoom(self, qapp):
        canvas = make_canvas(qapp)
        canvas._zoom_by(1.15)
        scale = canvas.transform().m11()
        assert scale > 1.0
        assert canvas.zoom_label.text() == f"{round(scale * 100)}%"

    def test_wheel_zoom_updates_zoom_label(self, qapp):
        canvas = make_canvas(qapp)
        before = canvas.transform().m11()
        ev = QWheelEvent(
            QPointF(10, 10), QPointF(10, 10), QPoint(0, 0), QPoint(0, 120),
            Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier,
            Qt.ScrollPhase.NoScrollPhase, False)
        qapp.sendEvent(canvas.viewport(), ev)
        after = canvas.transform().m11()
        assert after > before
        assert canvas.zoom_label.text() == f"{round(after * 100)}%"

    def test_zoom_label_click_resets_to_100(self, qapp):
        canvas = make_canvas(qapp)
        canvas._zoom_by(1.5)
        assert canvas.zoom_label.text() != '100%'
        QTest.mouseClick(canvas.zoom_label, Qt.MouseButton.LeftButton)
        assert canvas.zoom_label.text() == '100%'
        assert canvas.transform().m11() == pytest.approx(1.0)


class TestGridSnap:
    def test_snap_to_grid_rounds_to_10px(self, qapp):
        canvas = PdfCanvas()
        assert canvas._snap_to_grid(QPointF(13, 27)) == QPointF(10, 30)
        assert canvas._snap_to_grid(QPointF(7, 5)) == QPointF(10, 10)
        assert canvas._snap_to_grid(QPointF(0, 0)) == QPointF(0, 0)

    def test_snap_to_grid_clamps_to_image_bounds(self, qapp):
        canvas = PdfCanvas()
        canvas.img_w, canvas.img_h = 200, 100
        assert canvas._snap_to_grid(QPointF(198, 97)) == QPointF(200, 100)
        assert canvas._snap_to_grid(QPointF(-4, -7)) == QPointF(0, 0)

    def test_drawing_snaps_start_and_end(self, qapp):
        canvas = make_canvas(qapp)
        drawn = []
        canvas.region_drawn.connect(drawn.append)

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(105, 55),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        assert canvas.drawing
        assert canvas.start_pt == QPointF(110, 60)  # 105→110, 55→60

        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(163, 84),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        assert canvas.temp_rect.rect() == QRectF(110, 60, 50, 20)  # 163→160, 84→80

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(163, 84),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)
        assert len(drawn) == 1
        region = drawn[0]
        assert region.w == pytest.approx(50 / 200)
        assert region.h == pytest.approx(20 / 100)


class TestRegionSizeHint:
    def test_size_label_shown_during_drawing_hidden_on_release(self, qapp):
        canvas = make_canvas(qapp)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(105, 55),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(163, 84),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        assert canvas._size_label.isVisible()
        assert canvas._size_label.text() == '50×20px'

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(163, 84),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)
        assert not canvas._size_label.isVisible()

    def test_size_label_shown_during_resize(self, qapp):
        canvas = make_canvas(qapp)
        # 先画一个区域（110,60,50,20）
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(105, 55),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(163, 84),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(163, 84),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)

        # 拖拽右下角手柄放大区域（手柄仅在区域选中时可见/可命中）
        region_id = list(canvas.region_items.keys())[0]
        canvas._select_region(region_id)
        item = canvas.region_items[region_id]
        br = item.handles[3]  # 'br'
        base = br.scenePos()
        press2 = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(base.x(), base.y()),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press2)
        assert canvas.resizing
        move2 = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(base.x() + 30, base.y() + 20),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move2)
        assert canvas._size_label.isVisible()
        assert canvas._size_label.text() == '80×40px'

        release2 = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(base.x() + 30, base.y() + 20),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release2)
        assert not canvas._size_label.isVisible()


class TestFloatingToolbar:
    def test_toolbar_not_shown_without_pdf(self, qapp):
        canvas = PdfCanvas()
        canvas.show()
        canvas._on_viewport_enter()
        assert not canvas.floating_toolbar.isVisible()

    def test_toolbar_shows_on_viewport_enter(self, qapp):
        canvas = make_canvas(qapp)
        canvas._on_viewport_enter()
        assert canvas.floating_toolbar.isVisible()

    def test_toolbar_hides_after_viewport_leave(self, qapp):
        canvas = make_canvas(qapp)
        canvas._on_viewport_enter()
        assert canvas.floating_toolbar.isVisible()
        canvas._on_viewport_leave()
        QTest.qWait(300)
        assert not canvas.floating_toolbar.isVisible()

    def test_toolbar_zoom_in_button_zooms(self, qapp):
        canvas = make_canvas(qapp)
        canvas._on_viewport_enter()
        before = canvas.transform().m11()
        QTest.mouseClick(canvas._btn_zoom_in, Qt.MouseButton.LeftButton)
        after = canvas.transform().m11()
        assert after > before
        assert canvas.zoom_label.text() == f"{round(after * 100)}%"

    def test_toolbar_fit_button_fits_view(self, qapp):
        canvas = make_canvas(qapp)
        canvas._on_viewport_enter()
        QTest.mouseClick(canvas._btn_fit, Qt.MouseButton.LeftButton)
        scale = canvas.transform().m11()
        # 适应窗口后的实际缩放与标签一致
        assert canvas.zoom_label.text() == f"{round(scale * 100)}%"

    def test_toolbar_reset_button_restores_100_percent(self, qapp):
        canvas = make_canvas(qapp)
        canvas._on_viewport_enter()
        canvas._zoom_by(1.5)
        QTest.mouseClick(canvas._btn_reset, Qt.MouseButton.LeftButton)
        assert canvas.zoom_label.text() == '100%'
        assert canvas.transform().m11() == pytest.approx(1.0)
