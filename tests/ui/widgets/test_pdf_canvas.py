# tests/ui/widgets/test_pdf_canvas.py
"""Task 9 重构回归测试：PdfCanvas

覆盖核心新行为：
- 空状态（EmptyState 'no_preview'）显示/隐藏
- 缩放比例标签与 transform 同步、滚轮更新、点击恢复 100%
- 常驻缩放条（有图即显示 / 各按钮触发对应缩放 / fit-width 夹在 [0.1,10]）
- 高亮行盒 API（highlight_bbox / clear_highlights / bbox_clicked）
- 10px 网格吸附（函数级 + 框选集成）
- 框选/调整大小时区域尺寸提示显示与隐藏
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
        assert not canvas.zoom_bar.isVisible()
        assert not canvas.zoom_label.isVisible()

    def test_empty_state_hidden_after_load_image(self, qapp):
        canvas = make_canvas(qapp)
        assert not canvas.empty_state.isVisible()
        assert canvas.zoom_bar.isVisible()
        assert canvas.zoom_label.isVisible()

    def test_clear_restores_empty_state(self, qapp):
        canvas = make_canvas(qapp)
        canvas.clear()
        assert canvas.empty_state.isVisible()
        assert not canvas.zoom_bar.isVisible()
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
        """大尺寸拖拽（≥10px）：起止点吸附到 10px 网格"""
        canvas = make_canvas(qapp)
        drawn = []
        canvas.region_drawn.connect(drawn.append)

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(105, 55),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        assert canvas.drawing
        assert canvas.raw_start_pt == QPointF(105, 55)  # 原始点保留
        assert canvas.start_pt == QPointF(105, 55)  # 吸附在移动时按尺寸决定

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

    def test_small_drawing_keeps_exact_position(self, qapp):
        """微小区域（起止点 <10px）：保持精确，不吸附网格"""
        canvas = make_canvas(qapp)
        drawn = []
        canvas.region_drawn.connect(drawn.append)

        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(103, 57),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(109, 66),
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        # 原始 6×9px，未吸附（若吸附则为 100,60,10,10）
        assert canvas.temp_rect.rect() == QRectF(103, 57, 6, 9)

        release = QMouseEvent(
            QEvent.Type.MouseButtonRelease, QPointF(109, 66),
            Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseReleaseEvent(release)
        assert len(drawn) == 1
        region = drawn[0]
        assert region.w == pytest.approx(6 / 200)
        assert region.h == pytest.approx(9 / 100)

    def test_drawing_snaps_at_10px_boundary(self, qapp):
        """拖拽达到 10px：开始吸附网格"""
        canvas = make_canvas(qapp)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(103, 57),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        move = QMouseEvent(
            QEvent.Type.MouseMove, QPointF(113, 67),  # 原始恰好 10×10
            Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mouseMoveEvent(move)
        # 103→100, 57→60；113→110, 67→70
        assert canvas.temp_rect.rect() == QRectF(100, 60, 10, 10)


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


class TestZoomBar:
    """常驻缩放条：有图片即显示，各按钮触发对应缩放，百分比实时更新"""

    def test_zoom_bar_hidden_before_load(self, qapp):
        canvas = PdfCanvas()
        canvas.show()
        assert not canvas.zoom_bar.isVisible()

    def test_zoom_bar_visible_after_load(self, qapp):
        canvas = make_canvas(qapp)
        assert canvas.zoom_bar.isVisible()

    def test_zoom_label_lives_inside_zoom_bar(self, qapp):
        canvas = make_canvas(qapp)
        assert canvas.zoom_label.parent() is canvas.zoom_bar

    def test_fit_width_button_scales_to_viewport(self, qapp):
        canvas = make_canvas(qapp)
        canvas._zoom_by(2.0)  # 先放大，再点适应宽度
        QTest.mouseClick(canvas._btn_fit_width, Qt.MouseButton.LeftButton)
        expected = canvas.viewport().width() / max(1, canvas.img_w)
        expected = max(0.1, min(10.0, expected))
        assert canvas.transform().m11() == pytest.approx(expected)
        assert canvas.zoom_label.text() == f"{round(expected * 100)}%"

    def test_fit_page_button_fits_view(self, qapp):
        canvas = make_canvas(qapp)
        canvas._zoom_by(1.5)
        QTest.mouseClick(canvas._btn_fit_page, Qt.MouseButton.LeftButton)
        scale = canvas.transform().m11()
        assert canvas.zoom_label.text() == f"{round(scale * 100)}%"

    def test_reset_button_restores_100_percent(self, qapp):
        canvas = make_canvas(qapp)
        canvas._zoom_by(1.5)
        QTest.mouseClick(canvas._btn_reset_zoom, Qt.MouseButton.LeftButton)
        assert canvas.zoom_label.text() == '100%'
        assert canvas.transform().m11() == pytest.approx(1.0)

    def test_fit_width_clamps_to_min_0_1(self, qapp):
        """超宽图片：scale 低于 0.1 时被夹到 0.1"""
        canvas = PdfCanvas()
        canvas.setFixedSize(200, 100)
        canvas.show()
        img = Image.new('RGB', (20000, 100), 'white')
        canvas.load_image(img)
        assert canvas.transform().m11() == pytest.approx(0.1)

    def test_fit_width_clamps_to_max_10(self, qapp):
        """超小图片：scale 高于 10 时被夹到 10"""
        canvas = PdfCanvas()
        canvas.setFixedSize(200, 100)
        canvas.show()
        img = Image.new('RGB', (5, 5), 'white')
        canvas.load_image(img)
        assert canvas.transform().m11() == pytest.approx(10.0)

    def test_fit_width_math_bounds(self, qapp):
        """纯数学：给定 viewport 宽与 img_w，scale 夹在 [0.1, 10]"""
        for vp_w, img_w in [(200, 5000), (200, 10), (800, 400)]:
            scale = vp_w / max(1, img_w)
            scale = max(0.1, min(10.0, scale))
            assert 0.1 <= scale <= 10.0

    def test_load_image_defaults_to_fit_width(self, qapp):
        """load_image 默认按'适应宽度'（而非 fitInView）设置初始缩放"""
        canvas = PdfCanvas()
        canvas.setFixedSize(200, 100)
        canvas.show()
        img = Image.new('RGB', (400, 100), 'white')  # 宽度是视口 2 倍
        canvas.load_image(img)
        expected = canvas.viewport().width() / max(1, canvas.img_w)
        expected = max(0.1, min(10.0, expected))
        assert canvas.transform().m11() == pytest.approx(expected)


class TestHighlights:
    """高亮行盒（P1 hook）：highlight_bbox / clear_highlights / bbox_clicked"""

    def test_highlight_adds_item_and_clear_removes(self, qapp):
        canvas = PdfCanvas()
        canvas.highlight_bbox([10, 10, 50, 40])
        assert len(canvas._highlight_items) == 1
        canvas.clear_highlights()
        assert canvas._highlight_items == []

    def test_bbox_clicked_emits_in_auto_mode(self, qapp):
        canvas = make_canvas(qapp)  # 已加载 200x100 图片，场景坐标 == 图像像素
        canvas.set_drawing_enabled(False)  # 自动模式
        bbox = [10, 10, 50, 40]
        canvas.highlight_bbox(bbox)
        clicked = []
        canvas.bbox_clicked.connect(clicked.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(30, 25),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        assert clicked == [bbox]

    def test_bbox_clicked_outside_does_not_emit(self, qapp):
        canvas = make_canvas(qapp)
        canvas.set_drawing_enabled(False)
        canvas.highlight_bbox([10, 10, 50, 40])
        clicked = []
        canvas.bbox_clicked.connect(clicked.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(100, 50),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        assert clicked == []

    def test_bbox_clicked_ignored_in_manual_mode(self, qapp):
        """手动模式（框选启用）下高亮点击不触发 bbox_clicked，保持原框选行为"""
        canvas = make_canvas(qapp)
        canvas.highlight_bbox([10, 10, 50, 40])
        clicked = []
        canvas.bbox_clicked.connect(clicked.append)
        press = QMouseEvent(
            QEvent.Type.MouseButtonPress, QPointF(30, 25),
            Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier)
        canvas.mousePressEvent(press)
        assert clicked == []
