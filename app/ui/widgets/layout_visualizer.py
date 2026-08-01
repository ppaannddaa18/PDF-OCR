"""LayoutVisualizer — 在PDF图片上叠加彩色block覆盖层（兼作导航图）

Task 2 增强：
- 导航图模式：整页 fit-in-view（缩放系数 m），叠加视口指示矩形
- set_viewport_rect(scene_rect) 同步画布视口矩形（经 _scene_rect_to_minimap 换算）
- navigate 信号：点击导航图任意位置发射图像像素坐标，供主窗口 centerOn
- close_requested 信号 + 右上角 ✕ 按钮：关闭导航图
- update_blocks 跳过覆盖 >=99% 页面的整页大框（GGUF 单块整页框）
"""
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QPushButton
from PyQt6.QtGui import QPixmap, QPen, QColor, QBrush, QPainter, QImage
from PyQt6.QtCore import Qt, QRectF, QPointF, pyqtSignal as Signal
from typing import List
from PIL import Image

from app.models.page_result import Block
from app.ui.theme_manager import ThemeManager

# 颜色映射
BLOCK_COLORS = {
    "text": QColor("#4A90D9"),
    "table": QColor("#27AE60"),
    "formula": QColor("#E67E22"),
    "chart": QColor("#8E44AD"),
    "seal": QColor("#E74C3C"),
}
# 透明填充色（半透明）
BLOCK_FILL = {
    k: QColor(c.red(), c.green(), c.blue(), 40) for k, c in BLOCK_COLORS.items()
}

# 整页大框跳过阈值：bbox 覆盖页面面积 >=99% 视为 GGUF 整页框，不绘制覆盖层
WHOLE_PAGE_COVERAGE_THRESHOLD = 0.99


def _pil_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    """将PIL Image转换为QPixmap"""
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


def _scene_rect_to_minimap(scene_rect: QRectF, m: float) -> QRectF:
    """将画布场景矩形换算为导航图场景坐标（纯函数，便于单测）

    当前画布与导航图均为 1:1 图像像素场景（导航图的 fitInView 只缩放视图
    transform，不改变场景坐标），因此恒等返回 scene_rect。

    m 参数（导航图视图缩放系数）保留，用于未来的缩放场景（如 DPI 缩略图
    场景坐标放大后需将画布场景矩形按 1/m 映射）。当前 1:1 场景下返回原矩形。
    """
    return QRectF(scene_rect)


class LayoutVisualizer(QGraphicsView):
    """同步滚动的版面块覆盖层视图（导航图）"""
    scrolled = Signal(int)  # 垂直滚动值（同步用）
    navigate = Signal(QPointF)  # 点击导航图 -> 图像像素坐标
    close_requested = Signal()  # 点击右上角 ✕ -> 请求关闭

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._bg_item = None  # 背景图片（与左面板相同PDF页）
        self._block_items = []  # block覆盖矩形
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._scale = 1.0
        self._is_syncing = False  # 防振荡标志

        # 视口指示矩形（scene.clear() 会销毁旧对象，set_page_image 时重建）
        self.viewport_indicator = None
        self._create_viewport_indicator()
        self._setup_close_button()

    # ------------------------------------------------------------------
    # 视口指示矩形（导航图）
    # ------------------------------------------------------------------
    def _create_viewport_indicator(self):
        """创建并加入视口指示矩形（半透明 primary 填充 + 边框，置于顶层）"""
        primary = QColor(ThemeManager.get_color('primary'))
        brush = QColor(primary)
        brush.setAlpha(40)
        item = QGraphicsRectItem(0, 0, 0, 0)
        item.setBrush(brush)
        item.setPen(QPen(primary, 2))
        item.setZValue(10)
        item.setVisible(False)
        self._scene.addItem(item)
        self.viewport_indicator = item

    def set_viewport_rect(self, scene_rect: QRectF):
        """同步画布视口矩形到导航图（防振荡）

        scene_rect 为画布场景/图像像素坐标；经 _scene_rect_to_minimap 换算后
        设置指示矩形。只更新指示矩形，不写滚动条，保证单向同步。
        """
        if self._is_syncing or self.viewport_indicator is None:
            return
        self._is_syncing = True
        try:
            mapped = _scene_rect_to_minimap(scene_rect, self._scale)
            self.viewport_indicator.setRect(mapped)
            self.viewport_indicator.setVisible(True)
        finally:
            self._is_syncing = False

    def _setup_close_button(self):
        """右上角 ✕ 关闭按钮（viewport 子控件）"""
        self._close_btn = QPushButton('✕', self.viewport())
        self._close_btn.setFixedSize(24, 24)
        self._close_btn.setToolTip('关闭导航图')
        self._close_btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._close_btn.clicked.connect(self.close_requested.emit)
        self._close_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('bg_surface')};
                color: {ThemeManager.get_color('text_secondary')};
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('sm')}px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)

    def _layout_close_button(self):
        """将 ✕ 按钮定位到视口右上角"""
        self._close_btn.adjustSize()
        self._close_btn.move(self.viewport().width() - self._close_btn.width() - 8, 8)

    # ------------------------------------------------------------------
    # 页面/块数据
    # ------------------------------------------------------------------
    def set_page_image(self, pixmap: QPixmap):
        """设置当前页图片（与PDF预览同步）"""
        self._scene.clear()
        self._block_items = []
        self._bg_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()
        # scene.clear() 已销毁旧指示矩形，重建（zValue 置顶）
        self._create_viewport_indicator()
        self._layout_close_button()

    def set_page_image_from_pil(self, pil_image: Image.Image):
        """从PIL Image设置当前页图片"""
        self.set_page_image(_pil_to_qpixmap(pil_image))

    def update_blocks(self, blocks: List[Block]):
        """根据blocks绘制彩色覆盖层

        跳过覆盖 >=99% 页面的整页大框（GGUF 单块整页框），此时导航图退化为
        纯导航（P0 无 line_boxes 时导航图不绘制任何块覆盖层）。
        """
        # 移除旧覆盖层
        for item in self._block_items:
            self._scene.removeItem(item)
        self._block_items = []

        img_w = img_h = None
        if self._bg_item is not None:
            bg_rect = self._bg_item.boundingRect()
            img_w, img_h = bg_rect.width(), bg_rect.height()

        for block in blocks:
            if block.bbox is None:
                continue
            x1, y1, x2, y2 = block.bbox
            if img_w and img_h:
                coverage = ((x2 - x1) * (y2 - y1)) / max(1.0, float(img_w * img_h))
                if coverage >= WHOLE_PAGE_COVERAGE_THRESHOLD:
                    continue  # GGUF 整页大框跳过
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            color = BLOCK_COLORS.get(block.block_type, QColor("#999999"))
            fill = BLOCK_FILL.get(block.block_type, QColor(150, 150, 150, 40))

            item = self._scene.addRect(rect, QPen(color, 2), QBrush(fill))
            item.setToolTip(f"[{block.block_type}] {block.content[:100]}")
            self._block_items.append(item)

    # ------------------------------------------------------------------
    # 事件/滚动
    # ------------------------------------------------------------------
    def mousePressEvent(self, event):
        """点击导航图任意位置 -> navigate.emit(图像像素场景坐标)"""
        if event.button() == Qt.MouseButton.LeftButton:
            scene_pt = self.mapToScene(event.position().toPoint())
            self.navigate.emit(QPointF(scene_pt))
        super().mousePressEvent(event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._layout_close_button()

    def showEvent(self, event):
        # 首次显示即布局 ✕ 按钮，避免加载前停留在 (0,0) 闪位
        super().showEvent(event)
        self._layout_close_button()

    def scroll_to(self, value: int):
        """外部同步滚动（防振荡）"""
        if self._is_syncing:
            return
        self._is_syncing = True
        self.verticalScrollBar().setValue(value)
        self._is_syncing = False

    def wheelEvent(self, event):
        """转发滚动事件（防振荡）"""
        super().wheelEvent(event)
        if not self._is_syncing:
            self.scrolled.emit(self.verticalScrollBar().value())
