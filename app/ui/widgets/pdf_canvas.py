"""PdfCanvas - PDF 预览画布（Task 9 重构版）

Task 9 增强内容：
- 背景色/控件配色统一走 ThemeManager（支持暗色主题，去除硬编码 #fafafa 等）
- 空状态集成统一 EmptyState 组件（'no_preview' 变体）
- 底部常驻缩放条（适应宽度 / 适应页面 / 100% + 百分比标签，点击标签恢复 100%）
- 视口矩形信号 viewport_rect_changed（供导航图同步，单一发射源 scrollContentsBy）
- 高亮行盒 API highlight_bbox / clear_highlights / bbox_clicked（P1 hook）
- 框选/调整大小时显示区域尺寸提示（宽×高 px）
- 框选起始/结束点 10px 网格吸附（微小区域 <10px 保持精确不吸附；
  移动/调整既有区域保持精确行为）

对外接口保持不变：region_drawn / region_updated / region_selected 信号，
load_image / clear / update_regions / update_region / remove_region / get_region /
set_drawing_enabled / regions_data / region_items 等。
"""
from PyQt6.QtWidgets import (
    QGraphicsView, QGraphicsScene, QGraphicsRectItem, QGraphicsEllipseItem,
    QLabel, QWidget, QPushButton, QHBoxLayout,
)
from PyQt6.QtGui import QPixmap, QPainter, QPen, QColor, QImage
from PyQt6.QtCore import Qt, QRectF, QPointF, QEvent, pyqtSignal as Signal
from PIL import Image
import uuid
import random

from app.models.region import Region
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.empty_state import EmptyState


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

# 网格吸附尺寸（像素）
GRID_SIZE = 10


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
    """调整大小的手柄
    Handles rely on PdfCanvas.mousePressEvent for interaction detection — no independent event handlers.
    """
    def __init__(self, x, y, size, handle_type, parent=None):
        super().__init__(-size/2, -size/2, size, size, parent)
        self.setPos(x, y)
        self.handle_type = handle_type  # 'tl', 'tr', 'bl', 'br' 或 'move'
        self.setBrush(QColor(ThemeManager.get_color('primary')))
        self.setPen(QPen(QColor(ThemeManager.get_color('white')), 2))
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
        """创建或更新调整手柄的位置（首次创建，后续仅移动）"""
        if self.handles:
            # handles 已存在：仅更新位置
            self.update_handle_positions()
            return
        rect = self.rect()
        self.handles.append(ResizeHandle(rect.left(), rect.top(), HANDLE_SIZE, 'tl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.top(), HANDLE_SIZE, 'tr', self))
        self.handles.append(ResizeHandle(rect.left(), rect.bottom(), HANDLE_SIZE, 'bl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.bottom(), HANDLE_SIZE, 'br', self))
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


class _FloatingToolbar(QWidget):
    """浮动工具栏 - 悬停显示；鼠标进入/离开通过信号通知 PdfCanvas 控制显隐"""
    hovered = Signal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)

    def enterEvent(self, event):
        super().enterEvent(event)
        self.hovered.emit(True)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        self.hovered.emit(False)


class PdfCanvas(QGraphicsView):
    region_drawn = Signal(object)          # 用户完成框选 -> Region
    region_updated = Signal(str, object)   # 区域更新 -> (region_id, Region)
    region_selected = Signal(str)          # 区域被选中 -> region_id
    bbox_clicked = Signal(list)            # 自动模式下点击高亮行盒 -> bbox [x1,y1,x2,y2]
    viewport_rect_changed = Signal(QRectF)  # 视口矩形变化（场景/图像像素坐标）

    def __init__(self):
        super().__init__()
        self.scene_ = QGraphicsScene()
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.RenderHint.Antialiasing)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._setup_ui()

        self.pixmap_item = None
        self.img_w = 0
        self.img_h = 0

        # 高亮行盒（P1 hook）：(QGraphicsRectItem, bbox) 列表
        self._highlight_items = []

        # 框选状态
        self.drawing = False
        self.start_pt = None
        self.raw_start_pt = None
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
        self.moved_item = None      # [修复] 初始化移动中的区域项
        self.resized_item = None    # [修复] 初始化调整大小中的区域项

        # 右键拖动相关
        self.right_dragging = False
        self.last_mouse_pos = None

        # VLM模式下禁用框选
        self._drawing_enabled = True

        # 空状态（无 PDF 时显示）
        self._show_empty_state()
        self._layout_overlays()
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    # ------------------------------------------------------------------
    # UI 搭建（主题化）
    # ------------------------------------------------------------------
    def _setup_ui(self):
        """初始化主题化背景与覆盖层控件（空状态/常驻缩放条/尺寸提示）"""
        # 空状态（'no_preview' 变体；自身注册刷新回调）
        self.empty_state = EmptyState('no_preview', self.viewport())
        self.empty_state.setVisible(True)

        # 常驻缩放条（viewport 子控件，底部居中；有图片即显示）
        self.zoom_bar = QWidget(self.viewport())
        zoom_layout = QHBoxLayout(self.zoom_bar)
        zoom_layout.setContentsMargins(6, 4, 6, 4)
        zoom_layout.setSpacing(4)

        self._btn_fit_width = QPushButton('适应宽度', self.zoom_bar)
        self._btn_fit_page = QPushButton('适应页面', self.zoom_bar)
        self._btn_reset_zoom = QPushButton('100%', self.zoom_bar)
        self._zoom_bar_buttons = (self._btn_fit_width, self._btn_fit_page,
                                  self._btn_reset_zoom)
        for btn in self._zoom_bar_buttons:
            btn.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._btn_fit_width.clicked.connect(self.fit_to_width)
        self._btn_fit_page.clicked.connect(self._fit_to_view)
        self._btn_reset_zoom.clicked.connect(self.reset_zoom)
        for btn in self._zoom_bar_buttons:
            zoom_layout.addWidget(btn)

        # 缩放比例显示（并入缩放条，点击恢复 100%）
        self.zoom_label = QLabel('100%', self.zoom_bar)
        self.zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_label.installEventFilter(self)
        zoom_layout.addWidget(self.zoom_label)

        self.zoom_bar.setVisible(False)

        # 区域尺寸提示标签（框选/调整时显示，透明鼠标事件）
        self._size_label = QLabel(self.viewport())
        self._size_label.setAttribute(
            Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._size_label.setVisible(False)

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS 与主题色（Task 15：ThemeManager.set_theme 后调用）

        覆盖：视图背景 + 场景背景刷、缩放标签、浮动工具栏、尺寸提示、
        浮动工具栏按钮、场景中已创建的 ResizeHandle（画笔/画刷主题色）。
        区域框线颜色为区域固有颜色（随机区分色），与主题无关。
        """
        # 视图与场景背景
        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_primary')};"
        )
        self.scene_.setBackgroundBrush(QColor(ThemeManager.get_color('bg_primary')))

        # 缩放条容器
        self.zoom_bar.setStyleSheet(f"""
            background-color: {ThemeManager.get_color('bg_surface')};
            border: 1px solid {ThemeManager.get_color('border')};
            border-radius: {ThemeManager.get_radius('md')}px;
        """)

        # 缩放比例标签
        self.zoom_label.setStyleSheet(f"""
            background-color: transparent;
            color: {ThemeManager.get_color('text_secondary')};
            border-radius: {ThemeManager.get_radius('sm')}px;
            padding: 2px 6px;
            font-size: 11px;
        """)

        # 缩放条按钮
        for btn in self._zoom_bar_buttons:
            self._style_toolbar_button(btn)

        # 区域尺寸提示
        self._size_label.setStyleSheet(f"""
            background-color: {ThemeManager.get_color('primary')};
            color: {ThemeManager.get_color('white')};
            border-radius: {ThemeManager.get_radius('sm')}px;
            padding: 2px 6px;
            font-size: 11px;
        """)

        # 场景中已创建的手柄（新手柄在创建时即用当前主题色）
        handle_brush = QColor(ThemeManager.get_color('primary'))
        handle_pen = QPen(QColor(ThemeManager.get_color('white')), 2)
        for item in self.scene_.items():
            if isinstance(item, ResizeHandle):
                item.setBrush(handle_brush)
                item.setPen(handle_pen)

    def _style_toolbar_button(self, btn: QPushButton):
        """应用浮动工具栏按钮样式（主题化）"""
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_primary')};
                border: none;
                border-radius: {ThemeManager.get_radius('sm')}px;
                padding: 4px 10px;
                font-size: 12px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QPushButton:pressed {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
        """)

    def eventFilter(self, watched, event):
        """缩放标签点击 -> 恢复 100%

        注意：QAbstractScrollArea 会把自己注册为滚动条/视口的事件过滤器，
        setStyleSheet 触发的 polish 事件也会经过本方法（此时 zoom_label 等
        控件可能尚未创建），因此属性访问必须防御式处理，避免在 Qt 原生
        调用栈内抛异常导致死锁。
        """
        if watched is getattr(self, 'zoom_label', None) \
                and event.type() == QEvent.Type.MouseButtonPress:
            self.reset_zoom()
        return super().eventFilter(watched, event)

    # ------------------------------------------------------------------
    # 覆盖层布局
    # ------------------------------------------------------------------
    def _layout_overlays(self):
        """重新布局覆盖层控件（空状态铺满视口、缩放条底部居中）"""
        vp = self.viewport()
        rect = vp.rect()

        self.empty_state.setGeometry(rect)

        self.zoom_bar.adjustSize()
        zb = self.zoom_bar
        zb.move(max(0, (rect.width() - zb.width()) // 2),
                max(0, rect.height() - zb.height() - 8))

    def _viewport_pos_from_scene(self, scene_pt: QPointF):
        """将场景坐标转换为视口坐标（用于定位覆盖层控件）"""
        return self.viewport().mapFrom(self, self.mapFromScene(scene_pt))

    # ------------------------------------------------------------------
    # 空状态（EmptyState 集成）
    # ------------------------------------------------------------------
    def _show_empty_state(self):
        """显示空状态提示（无 PDF 时）"""
        self.empty_state.setVisible(True)

    def _hide_empty_state(self):
        """隐藏空状态提示"""
        self.empty_state.setVisible(False)

    # ------------------------------------------------------------------
    # 缩放控制与缩放比例标签
    # ------------------------------------------------------------------
    def _update_zoom_label(self):
        """更新缩放比例标签，并同步缩放条的显隐（与当前 transform 保持一致）"""
        scale = self.transform().m11()
        self.zoom_label.setText(f"{round(scale * 100)}%")
        self._update_zoom_bar_visibility()
        if self.pixmap_item is not None:
            self._layout_overlays()

    def _is_dragging(self) -> bool:
        """手动模式拖拽/框选进行中（复用旧浮动工具栏的遮挡防护条件）"""
        return self.drawing or self.resizing or self.moving or self.right_dragging

    def _update_zoom_bar_visibility(self):
        """同步缩放条显隐：拖拽/框选期间隐藏（避免遮挡鼠标事件），否则有图即显示"""
        self.zoom_bar.setVisible(self.pixmap_item is not None and not self._is_dragging())

    def _zoom_by(self, factor: float):
        """按比例缩放 - [修复] 添加缩放范围限制（0.1x ~ 10x）"""
        current_scale = self.transform().m11()  # 获取当前缩放比例
        new_scale = current_scale * factor

        # [修复] 限制缩放范围：0.1x 到 10x
        if new_scale < 0.1:
            factor = 0.1 / current_scale
        elif new_scale > 10:
            factor = 10 / current_scale

        self.scale(factor, factor)
        self._update_zoom_label()

    def reset_zoom(self):
        """重置缩放到 100%（缩放标签点击触发）"""
        current_scale = self.transform().m11()
        if current_scale > 0 and current_scale != 1.0:
            self.scale(1.0 / current_scale, 1.0 / current_scale)
        self._update_zoom_label()

    def _fit_to_view(self):
        """适应窗口（缩放条'适应页面'按钮）"""
        if self.pixmap_item:
            self.fitInView(self.pixmap_item, Qt.AspectRatioMode.KeepAspectRatio)
            self._update_zoom_label()

    def fit_to_width(self):
        """适应宽度（默认缩放模式）：等比放大使图片宽度填满视口

        先 resetTransform 再 scale，保证场景 (0,0) 可预测映射；
        缩放夹在 [0.1, 10]。缩放条'适应宽度'按钮触发。
        """
        if not self.pixmap_item:
            return
        scale = self.viewport().width() / max(1, self.img_w)
        scale = max(0.1, min(10.0, scale))
        self.resetTransform()
        self.scale(scale, scale)
        self.verticalScrollBar().setValue(0)
        self._update_zoom_label()

    # ------------------------------------------------------------------
    # 区域尺寸提示
    # ------------------------------------------------------------------
    def _show_region_size(self, rect: QRectF):
        """框选/调整大小时显示区域尺寸提示（宽×高 px，跟随矩形右上角）"""
        if rect.width() < 5 or rect.height() < 5:
            self._hide_region_size()
            return
        # 使用 round 而非 int：归一化坐标重建的矩形存在浮点噪声（如 79.9999...）
        w, h = round(rect.width()), round(rect.height())
        self._size_label.setText(f'{w}×{h}px')
        self._size_label.adjustSize()

        # 定位在矩形右上角旁（视口坐标），并钳制在视口范围内
        vp = self.viewport()
        anchor = self._viewport_pos_from_scene(QPointF(rect.right(), rect.top()))
        x = anchor.x() + 6
        y = anchor.y() - self._size_label.height() - 6
        x = max(4, min(x, vp.width() - self._size_label.width() - 4))
        y = max(4, min(y, vp.height() - self._size_label.height() - 4))
        self._size_label.move(x, y)
        self._size_label.setVisible(True)

    def _hide_region_size(self):
        """隐藏区域尺寸提示"""
        self._size_label.setVisible(False)

    # ------------------------------------------------------------------
    # 网格吸附
    # ------------------------------------------------------------------
    def _snap_to_grid(self, pos: QPointF) -> QPointF:
        """将坐标吸附到 10px 网格（仅用于新建框选的起始/结束点）"""
        x = int(pos.x() / GRID_SIZE + 0.5) * GRID_SIZE
        y = int(pos.y() / GRID_SIZE + 0.5) * GRID_SIZE
        # 钳制到图片范围内，避免越界产生无效矩形
        if self.img_w > 0:
            x = max(0, min(x, self.img_w))
        if self.img_h > 0:
            y = max(0, min(y, self.img_h))
        return QPointF(x, y)

    # ------------------------------------------------------------------
    # 原有功能（框选/平移/缩放/区域编辑，保持行为不变）
    # ------------------------------------------------------------------
    def set_drawing_enabled(self, enabled: bool):
        """启用/禁用框选功能（VLM模式下禁用）"""
        self._drawing_enabled = enabled
        if not enabled:
            self.setCursor(Qt.CursorShape.ArrowCursor)

    def _is_drawing_blocked(self) -> bool:
        """检查框选是否被VLM模式禁用，若禁用则调用super()并返回True"""
        return not self._drawing_enabled

    def clear(self):
        """清空画布，恢复到初始状态"""
        self.scene_.clear()
        self.pixmap_item = None
        self.img_w = 0
        self.img_h = 0
        self.region_items.clear()
        self.regions_data.clear()
        self.selected_region_id = None
        self._highlight_items = []
        self.drawing = False
        self.start_pt = None
        self.raw_start_pt = None
        self.temp_rect = None
        self.resizing = False
        self.moving = False
        self.resize_handle = None
        self.resize_start_rect = None
        self.move_start_pos = None
        self.move_start_rect = None
        self.right_dragging = False
        self.last_mouse_pos = None
        self._hide_region_size()
        self.zoom_bar.setVisible(False)
        self._show_empty_state()

    def load_image(self, pil_image: Image.Image):
        # 保存当前的框选区域数据
        saved_regions = list(self.regions_data.values())

        self.scene_.clear()
        self.region_items.clear()
        self.selected_region_id = None
        self._highlight_items = []
        self._hide_empty_state()
        self._hide_region_size()
        self.img_w, self.img_h = pil_image.size
        qimg = QImage(pil_image.tobytes("raw", "RGB"), self.img_w, self.img_h,
                      self.img_w * 3, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.pixmap_item = self.scene_.addPixmap(pix)
        self.setSceneRect(QRectF(pix.rect()))
        self.fit_to_width()

        # 恢复框选区域
        if saved_regions:
            self.update_regions(saved_regions)

        # 视口矩形单一发射源：加载完成后主动发一次（滚动/缩放/centerOn 经 scrollContentsBy 到达）
        self.viewport_rect_changed.emit(self._current_viewport_rect())

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
        if self._is_drawing_blocked():
            # 自动模式：先检查是否点击在高亮行盒内（P1 hook），命中则发射并短路
            if event.button() == Qt.MouseButton.LeftButton and self._highlight_items:
                scene_pt = self.mapToScene(event.position().toPoint())
                for _, bbox in self._highlight_items:
                    if self._bbox_contains(bbox, scene_pt):
                        self.bbox_clicked.emit(list(bbox))
                        return
            super().mousePressEvent(event)
            return
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
                self._update_zoom_bar_visibility()
                return
            self.right_dragging = True
            self.last_mouse_pos = event.pos()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            self._update_zoom_bar_visibility()
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
                self._update_zoom_bar_visibility()
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
                self._update_zoom_bar_visibility()
                return

            # 点击在空白处，取消选中
            self._deselect_all()

            # 开始框选（保留原始点；是否吸附 10px 网格在拖拽时按尺寸决定）
            self.drawing = True
            self.raw_start_pt = scene_pos
            self.start_pt = scene_pos
            self.temp_rect = QGraphicsRectItem()
            # [修复] 获取已使用的颜色，避免重复
            used_colors = {r.color for r in self.regions_data.values()}
            color = get_random_color(used_colors)
            pen = QPen(QColor(color), 2, Qt.PenStyle.DashLine)
            self.temp_rect.setPen(pen)
            self.temp_rect.setData(Qt.ItemDataRole.UserRole, color)  # 存储颜色
            self.scene_.addItem(self.temp_rect)
            self._update_zoom_bar_visibility()

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
        if self._is_drawing_blocked():
            super().mouseMoveEvent(event)
            return
        scene_pos = self.mapToScene(event.pos())

        # 移动区域（保持精确行为，不做网格吸附）
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

        # 调整大小（保持精确行为，不做网格吸附）
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
                self._show_region_size(new_rect)
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

        # 框选中（微小区域保持精确；任一轴 ≥10px 时起止点吸附 10px 网格）
        if self.drawing and self.temp_rect:
            raw_rect = QRectF(self.raw_start_pt, scene_pos).normalized()
            if raw_rect.width() < GRID_SIZE or raw_rect.height() < GRID_SIZE:
                # 微小区域：不吸附，保持精确（避免破坏小字段框选）
                rect = raw_rect
            else:
                start = self._snap_to_grid(self.raw_start_pt)
                cur = self._snap_to_grid(scene_pos)
                rect = QRectF(start, cur).normalized()
            self.temp_rect.setRect(rect)
            self._show_region_size(rect)

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
        if self._is_drawing_blocked():
            super().mouseReleaseEvent(event)
            return

        scene_pos = self.mapToScene(event.pos())

        # 结束移动
        if self.moving:
            if self.moved_item:
                # 更新 Region 数据
                region_id = self.moved_item.region_id
                if region_id in self.regions_data and self.img_w > 0 and self.img_h > 0:
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
            self._hide_region_size()
            self._update_zoom_bar_visibility()
            super().mouseReleaseEvent(event)
            return

        # 结束调整大小
        if self.resizing:
            if self.resized_item:
                # 更新 Region 数据
                region_id = self.resized_item.region_id
                if region_id in self.regions_data and self.img_w > 0 and self.img_h > 0:
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
            self._hide_region_size()
            self._update_zoom_bar_visibility()
            super().mouseReleaseEvent(event)
            return

        # 右键释放
        if event.button() == Qt.MouseButton.RightButton:
            self.right_dragging = False
            self.setCursor(Qt.CursorShape.ArrowCursor)
            if self.moving and self.moved_item and self.move_start_rect is not None:
                new_rect = self.moved_item.rect()
                if (abs(new_rect.x() - self.move_start_rect.x()) > 2 or
                    abs(new_rect.y() - self.move_start_rect.y()) > 2):
                    old_data = self.regions_data.get(self.moved_item.region_id)
                    if old_data:
                        new_region = Region(
                            id=old_data.id, field_name=old_data.field_name,
                            x=new_rect.x() / self.img_w, y=new_rect.y() / self.img_h,
                            w=new_rect.width() / self.img_w, h=new_rect.height() / self.img_h,
                            field_type=old_data.field_type, ocr_mode=old_data.ocr_mode,
                            color=old_data.color,
                        )
                        self.regions_data[self.moved_item.region_id] = new_region
                        self.region_updated.emit(self.moved_item.region_id, new_region)
            self.last_mouse_pos = None
            self._hide_region_size()
            self._update_zoom_bar_visibility()
            return

        # 左键释放 - 完成框选
        if self.drawing and self.temp_rect:
            self.drawing = False
            rect = self.temp_rect.rect()
            if rect.width() > 5 and rect.height() > 5 and self.img_w > 0 and self.img_h > 0:
                color = self.temp_rect.data(Qt.ItemDataRole.UserRole)
                # 钳制坐标到 [0, 1]，避免浮点边界值导致崩溃
                x = max(0.0, min(1.0, rect.x() / self.img_w))
                y = max(0.0, min(1.0, rect.y() / self.img_h))
                w = max(0.001, min(1.0, rect.width() / self.img_w))
                h = max(0.001, min(1.0, rect.height() / self.img_h))
                region = Region(
                    id=uuid.uuid4().hex,
                    field_name=f"字段{len(self.region_items)+1}",
                    x=x, y=y, w=w, h=h,
                    color=color,
                )
                # 创建正式的 SelectableRectItem
                self.scene_.removeItem(self.temp_rect)
                self._add_region_item(region)
                self.region_drawn.emit(region)
            else:
                self.scene_.removeItem(self.temp_rect)
            self.temp_rect = None
            self._hide_region_size()
            self._update_zoom_bar_visibility()

        super().mouseReleaseEvent(event)

    def resizeEvent(self, event):
        """[修复] 视图大小变化时重新布局覆盖层控件"""
        super().resizeEvent(event)
        self._layout_overlays()

    def wheelEvent(self, event):
        # 滚轮缩放 - [修复] 添加缩放范围限制（0.1x 到 10x）
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self._zoom_by(factor)

    def _current_viewport_rect(self) -> QRectF:
        """当前视口在场景/图像像素坐标系下的矩形（mapToScene(QRect) 返回
        QPolygonF，需手动映射两角构造 QRectF）"""
        r = self.viewport().rect()
        return QRectF(self.mapToScene(r.topLeft()),
                      self.mapToScene(r.bottomRight()))

    def scrollContentsBy(self, dx, dy):
        """视口矩形变化的单一发射源（场景/图像像素坐标 QRectF）

        Qt 在滚动条/centerOn/缩放时都会调用本方法；导航图只消费该信号
        更新指示矩形，不反向写滚动条，保证两视图间无振荡。
        """
        super().scrollContentsBy(dx, dy)
        self.viewport_rect_changed.emit(self._current_viewport_rect())

    # ------------------------------------------------------------------
    # 高亮 API（P1 hook：自动模式下点击行盒）
    # ------------------------------------------------------------------
    def highlight_bbox(self, bbox, color=None):
        """高亮一个行盒（场景坐标 == 图像像素，直接画半透明矩形）

        Args:
            bbox: [x1, y1, x2, y2] 图像像素坐标
            color: 可选颜色字符串；缺省用 ThemeManager primary
        """
        if bbox is None or len(bbox) != 4:
            return
        x1, y1, x2, y2 = bbox
        rect = QRectF(x1, y1, x2 - x1, y2 - y1)
        base = QColor(color) if color else QColor(ThemeManager.get_color('primary'))
        fill = QColor(base)
        fill.setAlpha(40)
        item = QGraphicsRectItem(rect)
        item.setBrush(fill)
        item.setPen(QPen(QColor(base), 2))
        item.setZValue(20)
        self.scene_.addItem(item)
        self._highlight_items.append((item, list(bbox)))
        return item

    def clear_highlights(self):
        """移除全部高亮矩形"""
        for item, _ in self._highlight_items:
            try:
                self.scene_.removeItem(item)
            except RuntimeError:
                pass  # 场景已清空（如 clear/load_image）
        self._highlight_items.clear()

    def _bbox_contains(self, bbox, pt: QPointF) -> bool:
        """行盒（图像像素坐标）是否包含场景点"""
        x1, y1, x2, y2 = bbox
        if x1 > x2:
            x1, x2 = x2, x1
        if y1 > y2:
            y1, y2 = y2, y1
        return x1 <= pt.x() <= x2 and y1 <= pt.y() <= y2

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
            item.update_handle_positions()
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
