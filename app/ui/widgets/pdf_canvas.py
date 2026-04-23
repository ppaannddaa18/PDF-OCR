from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal as Signal, QPointF
from PIL import Image
import uuid
from app.models.region import Region


class PdfCanvas(QGraphicsView):
    region_drawn = Signal(object)          # 用户完成框选 -> Region

    def __init__(self):
        super().__init__()
        self.scene_ = QGraphicsScene()
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setStyleSheet("background: #fafafa;")

        self.pixmap_item = None
        self.img_w = 0
        self.img_h = 0

        self.drawing = False
        self.start_pt = None
        self.temp_rect = None
        self.region_items = {}   # region_id -> QGraphicsRectItem

        # 空状态提示
        self.empty_text = None
        self._show_empty_state()

    def _show_empty_state(self):
        """显示空状态提示"""
        if self.empty_text:
            return
        self.empty_text = QGraphicsTextItem()
        self.empty_text.setPlainText("上传 PDF 后在此显示\n\n拖拽鼠标框选识别区域")
        self.empty_text.setDefaultTextColor(QColor("#888"))
        self.empty_text.setFont(QFont("Microsoft YaHei", 14))
        self.scene_.addItem(self.empty_text)
        # 居中显示
        self.empty_text.setPos(-100, -30)

    def _hide_empty_state(self):
        """隐藏空状态提示"""
        if self.empty_text:
            self.scene_.removeItem(self.empty_text)
            self.empty_text = None

    def load_image(self, pil_image: Image.Image):
        self.scene_.clear()
        self.region_items.clear()
        self.empty_text = None
        self.img_w, self.img_h = pil_image.size
        qimg = QImage(pil_image.tobytes("raw", "RGB"), self.img_w, self.img_h,
                      self.img_w * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.pixmap_item = self.scene_.addPixmap(pix)
        self.setSceneRect(QRectF(pix.rect()))
        self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap_item:
            self.drawing = True
            self.start_pt = self.mapToScene(event.pos())
            self.temp_rect = QGraphicsRectItem()
            pen = QPen(QColor("#FF5733"), 2, Qt.PenStyle.DashLine)
            self.temp_rect.setPen(pen)
            self.scene_.addItem(self.temp_rect)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing and self.temp_rect:
            cur = self.mapToScene(event.pos())
            rect = QRectF(self.start_pt, cur).normalized()
            self.temp_rect.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drawing and self.temp_rect:
            self.drawing = False
            rect = self.temp_rect.rect()
            if rect.width() > 5 and rect.height() > 5 and self.img_w > 0 and self.img_h > 0:
                region = Region(
                    id=str(uuid.uuid4())[:8],
                    field_name=f"字段{len(self.region_items)+1}",
                    x=rect.x() / self.img_w,
                    y=rect.y() / self.img_h,
                    w=rect.width() / self.img_w,
                    h=rect.height() / self.img_h,
                )
                # 正式加入
                pen = QPen(QColor(region.color), 2)
                self.temp_rect.setPen(pen)
                self.region_items[region.id] = self.temp_rect
                self.region_drawn.emit(region)
            else:
                self.scene_.removeItem(self.temp_rect)
            self.temp_rect = None
        super().mouseReleaseEvent(event)

    def update_regions(self, regions: list):
        # 清理所有已有框再重绘
        for item in self.region_items.values():
            self.scene_.removeItem(item)
        self.region_items.clear()

        if self.img_w <= 0 or self.img_h <= 0:
            return

        for r in regions:
            rect = QRectF(r.x * self.img_w, r.y * self.img_h,
                          r.w * self.img_w, r.h * self.img_h)
            item = QGraphicsRectItem(rect)
            item.setPen(QPen(QColor(r.color), 2))
            self.scene_.addItem(item)
            self.region_items[r.id] = item

    def remove_region(self, region_id: str):
        if region_id in self.region_items:
            self.scene_.removeItem(self.region_items[region_id])
            del self.region_items[region_id]

    def wheelEvent(self, event):
        # 滚轮缩放
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
