"""LayoutVisualizer — 在PDF图片上叠加彩色block覆盖层"""
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem
from PyQt6.QtGui import QPixmap, QPen, QColor, QBrush, QPainter, QImage
from PyQt6.QtCore import Qt, QRectF, pyqtSignal as Signal
from typing import List
from PIL import Image

from app.models.page_result import Block

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


def _pil_to_qpixmap(pil_image: Image.Image) -> QPixmap:
    """将PIL Image转换为QPixmap"""
    if pil_image.mode != "RGBA":
        pil_image = pil_image.convert("RGBA")
    data = pil_image.tobytes("raw", "RGBA")
    qimage = QImage(data, pil_image.width, pil_image.height, QImage.Format.Format_RGBA8888)
    return QPixmap.fromImage(qimage)


class LayoutVisualizer(QGraphicsView):
    """同步滚动的版面块覆盖层视图"""
    scrolled = Signal(int)  # 垂直滚动值（同步用）

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

    def set_page_image(self, pixmap: QPixmap):
        """设置当前页图片（与PDF预览同步）"""
        self._scene.clear()
        self._block_items = []
        self._bg_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()

    def set_page_image_from_pil(self, pil_image: Image.Image):
        """从PIL Image设置当前页图片"""
        self.set_page_image(_pil_to_qpixmap(pil_image))

    def update_blocks(self, blocks: List[Block]):
        """根据blocks绘制彩色覆盖层"""
        # 移除旧覆盖层
        for item in self._block_items:
            self._scene.removeItem(item)
        self._block_items = []

        for block in blocks:
            if block.bbox is None:
                continue
            x1, y1, x2, y2 = block.bbox
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            color = BLOCK_COLORS.get(block.block_type, QColor("#999999"))
            fill = BLOCK_FILL.get(block.block_type, QColor(150, 150, 150, 40))

            item = self._scene.addRect(rect, QPen(color, 2), QBrush(fill))
            item.setToolTip(f"[{block.block_type}] {block.content[:100]}")
            self._block_items.append(item)

    def scroll_to(self, value: int):
        """外部同步滚动"""
        self.verticalScrollBar().setValue(value)

    def wheelEvent(self, event):
        """转发滚动事件"""
        super().wheelEvent(event)
        self.scrolled.emit(self.verticalScrollBar().value())
