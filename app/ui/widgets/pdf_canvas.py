from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsTextItem, QGraphicsEllipseItem
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage, QFont, QCursor
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

# 调整手柄大小
HANDLE_SIZE = 8


def get_random_color(used_colors: set = None) -> str:
    """获取随机颜色 - [修复] 避免与已使用颜色重复"""
    if used_colors is None:
        used_colors = set()

    # 过滤掉已使用的颜色
    available_colors = [c for c in DISTINCT_COLORS if c not in used_colors]

    if available_colors:
        return random.choice(available_colors)
    else:
        # 如果所有颜色都已使用，随机生成一个颜色
        return "#{:06x}".format(random.randint(0, 0xFFFFFF))


class ResizeHandle(QGraphicsEllipseItem):
    """调整大小的手柄"""
    def __init__(self, x, y, size, handle_type, parent=None):
        super().__init__(-size/2, -size/2, size, size, parent)
        self.setPos(x, y)
        self.handle_type = handle_type  # 'tl', 'tr', 'bl', 'br' 或 'move'
        self.setBrush(QColor("#0078d4"))
        self.setPen(QPen(QColor("#fff"), 2))
        self.setZValue(100)
        self.setCursor(self._get_cursor())

    def _get_cursor(self):
        if self.handle_type == 'tl' or self.handle_type == 'br':
            return Qt.CursorShape.SizeFDiagCursor
        elif self.handle_type == 'tr' or self.handle_type == 'bl':
            return Qt.CursorShape.SizeBDiagCursor
        elif self.handle_type == 'move':
            return Qt.CursorShape.SizeAllCursor
        return Qt.CursorShape.ArrowCursor


class SelectableRectItem(QGraphicsRectItem):
    """可选中的矩形区域项"""
    def __init__(self, rect, color, region_id, parent=None):
        super().__init__(rect, parent)
        self.region_id = region_id
        self.color = color
        self.setPen(QPen(QColor(color), 2))
        self.setAcceptHoverEvents(True)
        self.handles = []
        self._create_handles()
        self.setZValue(10)

    def _create_handles(self):
        """创建调整手柄"""
        rect = self.rect()
        # 四个角
        self.handles.append(ResizeHandle(rect.left(), rect.top(), HANDLE_SIZE, 'tl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.top(), HANDLE_SIZE, 'tr', self))
        self.handles.append(ResizeHandle(rect.left(), rect.bottom(), HANDLE_SIZE, 'bl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.bottom(), HANDLE_SIZE, 'br', self))
        # 移动手柄（中心点）
        self.handles.append(ResizeHandle(rect.center().x(), rect.center().y(), HANDLE_SIZE, 'move', self))
        self._update_handles_visibility(False)

    def _update_handles_visibility(self, visible):
        """更新手柄可见性"""
        for handle in self.handles:
            handle.setVisible(visible)

    def setSelected(self, selected):
        """设置选中状态"""
        super().setSelected(selected)
        self._update_handles_visibility(selected)
        if selected:
            self.setPen(QPen(QColor(self.color), 3))
        else:
            self.setPen(QPen(QColor(self.color), 2))

    def update_handle_positions(self):
        """更新手柄位置"""
        rect = self.rect()
        self.handles[0].setPos(rect.left(), rect.top())  # tl
        self.handles[1].setPos(rect.right(), rect.top())  # tr
        self.handles[2].setPos(rect.left(), rect.bottom())  # bl
        self.handles[3].setPos(rect.right(), rect.bottom())  # br
        self.handles[4].setPos(rect.center().x(), rect.center().y())  # move


class PdfCanvas(QGraphicsView):
    region_drawn = Signal(object)          # 用户完成框选 -> Region
    region_updated = Signal(str, object)   # 区域更新 -> (region_id, Region)
    region_selected = Signal(str)          # 区域被选中 -> region_id

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

        # 框选状态
        self.drawing = False
        self.start_pt = None
        self.temp_rect = None

        # 区域管理
        self.region_items = {}   # region_id -> SelectableRectItem
        self.regions_data = {}   # region_id -> Region
        self.selected_region_id = None

        # 调整状态
        self.resizing = False
        self.moving = False
        self.resize_handle = None
        self.resize_start_rect = None
        self.move_start_pos = None
        self.move_start_rect = None

        # 右键拖动相关
        self.right_dragging = False
        self.last_mouse_pos = None

        # 空状态提示
        self.empty_text = None
        self._show_empty_state()

    def _show_empty_state(self):
        """显示空状态提示 - [修复] 使用视图中心坐标"""
        if self.empty_text:
            return
        self.empty_text = QGraphicsTextItem()
        self.empty_text.setPlainText("上传 PDF 后在此显示\n\n拖拽鼠标框选识别区域")
        self.empty_text.setDefaultTextColor(QColor("#888"))
        self.empty_text.setFont(QFont("Microsoft YaHei", 14))
        self.scene_.addItem(self.empty_text)
        # [修复] 使用视图中心坐标，而不是固定坐标
        self._center_empty_text()

    def _center_empty_text(self):
        """[修复] 将空状态文本居中显示"""
        if self.empty_text:
            # 获取视图可视区域中心
            view_rect = self.viewport().rect()
            center = self.mapToScene(view_rect.center())
            # 计算文本尺寸并居中
            text_rect = self.empty_text.boundingRect()
            self.empty_text.setPos(
                center.x() - text_rect.width() / 2,
                center.y() - text_rect.height() / 2
            )

    def _hide_empty_state(self):
        """隐藏空状态提示"""
        if self.empty_text:
            self.scene_.removeItem(self.empty_text)
            self.empty_text = None

    def clear(self):
        """清空画布，恢复到初始状态"""
        self.scene_.clear()
        self.pixmap_item = None
        self.img_w = 0
        self.img_h = 0
        self.region_items.clear()
        self.regions_data.clear()
        self.selected_region_id = None
        self.drawing = False
        self.start_pt = None
        self.temp_rect = None
        self.resizing = False
        self.moving = False
        self.resize_handle = None
        self.resize_start_rect = None
        self.move_start_pos = None
        self.move_start_rect = None
        self.right_dragging = False
        self.last_mouse_pos = None
        self.empty_text = None
        self._show_empty_state()

    def load_image(self, pil_image: Image.Image):
        # 保存当前的框选区域数据
        saved_regions = list(self.regions_data.values())

        self.scene_.clear()
        self.region_items.clear()
        self.selected_region_id = None
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

    def _get_handle_at_pos(self, pos):
        """获取指定位置的手柄"""
        items = self.scene_.items(pos)
        for item in items:
            if isinstance(item, ResizeHandle):
                return item
        return None

    def _get_region_item_at_pos(self, pos):
        """获取指定位置的区域项"""
        items = self.scene_.items(pos)
        for item in items:
            if isinstance(item, SelectableRectItem):
                return item
        return None

    def mousePressEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # 右键拖动
        if event.button() == Qt.MouseButton.RightButton and self.pixmap_item:
            # 检查是否点击在手柄上
            handle = self._get_handle_at_pos(scene_pos)
            if handle and handle.handle_type == 'move':
                # 右键在手柄上，开始移动
                self.moving = True
                self.move_start_pos = scene_pos
                self.move_start_rect = handle.parentItem().rect()
                self.moved_item = handle.parentItem()
                self.setCursor(Qt.CursorShape.SizeAllCursor)
                return
            self.right_dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return

        # 左键
        if event.button() == Qt.MouseButton.LeftButton and self.pixmap_item:
            # 检查是否点击在手柄上
            handle = self._get_handle_at_pos(scene_pos)
            if handle:
                self.resizing = True
                self.resize_handle = handle
                self.resize_start_rect = handle.parentItem().rect()
                self.resized_item = handle.parentItem()
                return

            # 检查是否点击在区域上
            region_item = self._get_region_item_at_pos(scene_pos)
            if region_item:
                self._select_region(region_item.region_id)
                # 开始移动
                self.moving = True
                self.move_start_pos = scene_pos
                self.move_start_rect = region_item.rect()
                self.moved_item = region_item
                return

            # 点击在空白处，取消选中
            self._deselect_all()

            # 开始框选
            self.drawing = True
            self.start_pt = scene_pos
            self.temp_rect = QGraphicsRectItem()
            # [修复] 获取已使用的颜色，避免重复
            used_colors = {r.color for r in self.regions_data.values()}
            color = get_random_color(used_colors)
            pen = QPen(QColor(color), 2, Qt.PenStyle.DashLine)
            self.temp_rect.setPen(pen)
            self.temp_rect.setData(0, color)  # 存储颜色
            self.scene_.addItem(self.temp_rect)

        super().mousePressEvent(event)

    def _select_region(self, region_id):
        """选中指定区域"""
        # 取消之前的选中
        if self.selected_region_id and self.selected_region_id in self.region_items:
            self.region_items[self.selected_region_id].setSelected(False)

        self.selected_region_id = region_id
        if region_id in self.region_items:
            self.region_items[region_id].setSelected(True)
            self.region_selected.emit(region_id)

    def _deselect_all(self):
        """取消所有选中"""
        if self.selected_region_id and self.selected_region_id in self.region_items:
            self.region_items[self.selected_region_id].setSelected(False)
        self.selected_region_id = None

    def mouseMoveEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # 移动区域
        if self.moving and self.moved_item:
            delta = scene_pos - self.move_start_pos
            new_rect = QRectF(
                self.move_start_rect.x() + delta.x(),
                self.move_start_rect.y() + delta.y(),
                self.move_start_rect.width(),
                self.move_start_rect.height()
            )
            # 限制在图片范围内
            new_rect = self._constrain_rect(new_rect)
            self.moved_item.setRect(new_rect)
            self.moved_item.update_handle_positions()
            return

        # 调整大小
        if self.resizing and self.resize_handle and self.resized_item:
            rect = self.resize_start_rect
            handle_type = self.resize_handle.handle_type

            if handle_type == 'tl':
                new_rect = QRectF(scene_pos.x(), scene_pos.y(),
                                  rect.right() - scene_pos.x(),
                                  rect.bottom() - scene_pos.y())
            elif handle_type == 'tr':
                new_rect = QRectF(rect.left(), scene_pos.y(),
                                  scene_pos.x() - rect.left(),
                                  rect.bottom() - scene_pos.y())
            elif handle_type == 'bl':
                new_rect = QRectF(scene_pos.x(), rect.top(),
                                  rect.right() - scene_pos.x(),
                                  scene_pos.y() - rect.top())
            elif handle_type == 'br':
                new_rect = QRectF(rect.left(), rect.top(),
                                  scene_pos.x() - rect.left(),
                                  scene_pos.y() - rect.top())
            else:
                return

            new_rect = new_rect.normalized()
            # 最小尺寸限制
            if new_rect.width() >= 5 and new_rect.height() >= 5:
                new_rect = self._constrain_rect(new_rect)
                self.resized_item.setRect(new_rect)
                self.resized_item.update_handle_positions()
            return

        # 右键拖动
        if self.right_dragging and self.last_mouse_pos:
            delta = event.pos() - self.last_mouse_pos
            self.last_mouse_pos = event.pos()
            h_bar = self.horizontalScrollBar()
            v_bar = self.verticalScrollBar()
            h_bar.setValue(h_bar.value() - delta.x())
            v_bar.setValue(v_bar.value() - delta.y())
            return

        # 框选中
        if self.drawing and self.temp_rect:
            cur = scene_pos
            rect = QRectF(self.start_pt, cur).normalized()
            self.temp_rect.setRect(rect)

        super().mouseMoveEvent(event)

    def _constrain_rect(self, rect: QRectF) -> QRectF:
        """限制矩形在图片范围内"""
        if self.img_w <= 0 or self.img_h <= 0:
            return rect

        # 限制在图片边界内
        left = max(0, min(rect.left(), self.img_w))
        top = max(0, min(rect.top(), self.img_h))
        right = max(0, min(rect.right(), self.img_w))
        bottom = max(0, min(rect.bottom(), self.img_h))

        return QRectF(left, top, right - left, bottom - top)

    def mouseReleaseEvent(self, event):
        scene_pos = self.mapToScene(event.pos())

        # 结束移动
        if self.moving:
            if self.moved_item:
                # 更新 Region 数据
                region_id = self.moved_item.region_id
                if region_id in self.regions_data:
                    rect = self.moved_item.rect()
                    region = self.regions_data[region_id]
                    region.x = rect.x() / self.img_w
                    region.y = rect.y() / self.img_h
                    region.w = rect.width() / self.img_w
                    region.h = rect.height() / self.img_h
                    self.region_updated.emit(region_id, region)
            self.moving = False
            self.moved_item = None
            self.move_start_pos = None
            self.move_start_rect = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            super().mouseReleaseEvent(event)
            return

        # 结束调整大小
        if self.resizing:
            if self.resized_item:
                # 更新 Region 数据
                region_id = self.resized_item.region_id
                if region_id in self.regions_data:
                    rect = self.resized_item.rect()
                    region = self.regions_data[region_id]
                    region.x = rect.x() / self.img_w
                    region.y = rect.y() / self.img_h
                    region.w = rect.width() / self.img_w
                    region.h = rect.height() / self.img_h
                    self.resized_item.update_handle_positions()
                    self.region_updated.emit(region_id, region)
            self.resizing = False
            self.resize_handle = None
            self.resized_item = None
            self.resize_start_rect = None
            super().mouseReleaseEvent(event)
            return

        # 右键释放
        if event.button() == Qt.MouseButton.RightButton:
            self.right_dragging = False
            self.last_mouse_pos = None
            self.setCursor(Qt.CursorShape.ArrowCursor)
            return

        # 左键释放 - 完成框选
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
                # 创建正式的 SelectableRectItem
                self.scene_.removeItem(self.temp_rect)
                self._add_region_item(region)
                self.region_drawn.emit(region)
            else:
                self.scene_.removeItem(self.temp_rect)
            self.temp_rect = None

        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        """[修复] 视图大小变化时重新居中显示空状态文本"""
        super().resizeEvent(event)
        if self.empty_text:
            self._center_empty_text()

    def _add_region_item(self, region: Region):
        """添加区域项到场景"""
        rect = QRectF(region.x * self.img_w, region.y * self.img_h,
                      region.w * self.img_w, region.h * self.img_h)
        item = SelectableRectItem(rect, region.color, region.id)
        self.scene_.addItem(item)
        self.region_items[region.id] = item
        self.regions_data[region.id] = region

    def update_regions(self, regions: list):
        """更新所有区域显示（增量更新）"""
        if self.img_w <= 0 or self.img_h <= 0:
            return

        # 计算差异
        current_ids = set(self.region_items.keys())
        new_ids = {r.id for r in regions}

        # 删除不再存在的区域
        for rid in current_ids - new_ids:
            self.remove_region(rid)

        # 更新或添加区域
        for r in regions:
            if r.id in self.region_items:
                # 更新现有区域
                self.update_region(r.id, r)
            else:
                # 添加新区域
                self._add_region_item(r)

    def update_region(self, region_id: str, region: Region):
        """增量更新单个区域"""
        if region_id in self.region_items:
            item = self.region_items[region_id]
            rect = QRectF(region.x * self.img_w, region.y * self.img_h,
                         region.w * self.img_w, region.h * self.img_h)
            item.setRect(rect)
            # 更新手柄位置
            item._create_handles()
            item._update_handles_visibility(item.isSelected())
            self.regions_data[region_id] = region
        else:
            # 新增区域
            self._add_region_item(region)

    def remove_region(self, region_id: str):
        """删除指定区域"""
        if region_id in self.region_items:
            self.scene_.removeItem(self.region_items[region_id])
            del self.region_items[region_id]
        if region_id in self.regions_data:
            del self.regions_data[region_id]
        if self.selected_region_id == region_id:
            self.selected_region_id = None

    def get_region(self, region_id: str) -> Region:
        """获取指定区域数据"""
        return self.regions_data.get(region_id)

    def wheelEvent(self, event):
        # 滚轮缩放 - [修复] 添加缩放范围限制
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        current_scale = self.transform().m11()  # 获取当前缩放比例
        new_scale = current_scale * factor

        # [修复] 限制缩放范围：0.1x 到 10x
        if new_scale < 0.1:
            factor = 0.1 / current_scale
        elif new_scale > 10:
            factor = 10 / current_scale

        self.scale(factor, factor)
