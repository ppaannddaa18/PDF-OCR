from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QFont
from PyQt6.QtCore import Qt, QRectF, pyqtSignal as Signal, QPointF
from PIL import Image
import uuid
import random
from app.models.region import Region


# 预定义的明显区分颜色列表
DISTINCT_COLORS = [
    "#FF5733",  # 红橙
    "#33A8FF",  # 蓝
    "#33FF57",  # 绿
    "#FF33A8",  # 粉红
    "#A833FF",  # 紫
    "#FFA833",  # 橙
    "#33FFF5",  # 青
    "#F5FF33",  # 黄绿
    "#FF6B6B",  # 浅红
    "#6B6BFF",  # 浅蓝
    "#6BFF6B",  # 浅绿
    "#FFB86B",  # 浅橙
]


def get_random_color() -> str:
    """获取随机颜色"""
    return random.choice(DISTINCT_COLORS)


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
        self.regions_data = []   # 保存 Region 列表，用于切换 PDF 时恢复

        # 右键拖动相关
        self.right_dragging = False
        self.last_mouse_pos = None

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
        # 保存当前的框选区域数据
        saved_regions = self.regions_data

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

        # 恢复框选区域
        if saved_regions:
            self.update_regions(saved_regions)

    def mousePressEvent(self, event):
        # 右键拖动
        if event.button() == Qt.MouseButton.RightButton and self.pixmap_item:
            self.right_dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        # 左键框选
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap_item:
            self.drawing = True
            self.start_pt = self.mapToScene(event.pos())
            self.temp_rect = QGraphicsRectItem()
            color = get_random_color()
            pen = QPen(QColor(color), 2, Qt.PenStyle.DashLine)
            self.temp_rect.setPen(pen)
            self.temp_rect.setData(0, color)  # 存储颜色
            self.scene_.addItem(self.temp_rect)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        # 右键拖动 - 通过滚动条实现平移
        if self.right_dragging and self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            # 通过滚动条平移
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            return

        # 左键框选
        if self.drawing and self.temp_rect:
            cur = self.mapToScene(event.pos())
            rect = QRectF(self.start_pt, cur).normalized()
            self.temp_rect.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        # 右键释放
        if event.button() == Qt.MouseButton.RightButton:
            self.right_dragging = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # 左键释放
        if self.drawing and self.temp_rect:
            self.drawing = False
            rect = self.temp_rect.rect()
            if rect.width() > 5 and rect.height() > 5 and self.img_w > 0 and self.img_h > 0:
                color = self.temp_rect.data(0)  # 获取颜色
                region = Region(
                    id=str(uuid.uuid4())[:8],
                    field_name=f"字段{len(self.region_items)+1}",
                    x=rect.x() / self.img_w,
                    y=rect.y() / self.img_h,
                    w=rect.width() / self.img_w,
                    h=rect.height() / self.img_h,
                    color=color,
                )
                # 正式加入
                pen = QPen(QColor(region.color), 2)
                self.temp_rect.setPen(pen)
                self.region_items[region.id] = self.temp_rect
                # 保存到 regions_data
                self.regions_data.append(region)
                self.region_drawn.emit(region)
            else:
                self.scene_.removeItem(self.temp_rect)
            self.temp_rect = None
        super().mouseReleaseEvent(event)

    def update_regions(self, regions: list):
        # 保存区域数据
        self.regions_data = list(regions)  # 复制一份，避免引用问题

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
        # 同步删除 regions_data
        self.regions_data = [r for r in self.regions_data if r.id != region_id]

    def wheelEvent(self, event):
        # 滚轮缩放
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
