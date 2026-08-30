"""左侧文件列表：会话/历史分组 + 状态徽章 + 耗时（观片台白卡容器）

数据层（_items/_status/_order）与展示层分离：列表每次变更后整体重绘
（_rebuild），会话文件置顶、历史记录分组折叠，公共 API/信号语义不变。
"""
import os
import uuid
from datetime import datetime
from typing import List

from PyQt6.QtCore import Qt, QEvent, pyqtSignal
from PyQt6.QtGui import QColor, QFont
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                             QListWidgetItem, QLabel, QPushButton, QMenu)

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import secondary_qss

# 拖拽上传接受的文件扩展名（与「+ 加文件」文件过滤器一致）
_DROP_EXTS = {".pdf", ".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}

_STATUS_TEXT = {
    "queued": "等待",
    "processing": "识别中",
    "done": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}
_STATUS_COLOR = {
    "queued": "text_secondary",
    "processing": "primary",
    "done": "success",
    "failed": "error",
    "cancelled": "text_secondary",
}

# 分组标题行的标记数据角色（UserRole 存路径，UserRole+1 标记分组行）
_GROUP_ROLE = Qt.ItemDataRole.UserRole + 1


class OcrFilePanel(QWidget):
    file_selected = pyqtSignal(str)          # path
    file_remove_requested = pyqtSignal(str)  # path
    clear_requested = pyqtSignal()
    add_files_requested = pyqtSignal()       # 点击「+ 加文件」
    files_dropped = pyqtSignal(list)         # 拖拽上传的文件路径

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # fid -> {"path", "time", "history"}
        self._status = {}  # fid -> (status, detail)
        self._order = []  # 加入顺序 fid 列表
        self._history_open = False  # 历史分组折叠态
        self._history_header_item = None
        self._drag_active = False  # 拖拽悬停高亮态
        self._build_ui()
        self.apply_theme()
        ThemeManager.register_refresh_callback(self.apply_theme)
        self._rebuild()

    def apply_theme(self):
        """设计刷新回调：重建卡片容器/标题/列表 QSS（只依赖 default 兼容角色）"""
        if not hasattr(self, 'list'):
            return
        t = ThemeManager
        self.setObjectName('panelCard')
        self.setStyleSheet(
            f"QWidget#panelCard {{ background: {t.get_color('bg_surface')};"
            f"border: 1px solid {t.get_color('border')};"
            f"border-radius: {t.get_radius('md')}px; }}")
        self.title.setStyleSheet(
            f"color: {t.get_color('text_primary')};"
            f"font-size: 13px; font-weight: 600;")
        self.count_badge.setStyleSheet(
            f"background: {t.get_color('bg_hover')};"
            f"color: {t.get_color('text_secondary')};"
            f"border-radius: 9px; padding: 0 7px; font-size: 11px;")
        # 「+ 加文件」主操作小号蓝色（default 用 primary，design 下=accent）
        self.add_btn.setStyleSheet(
            f"QPushButton {{ background: {t.get_color('primary')};"
            f"color: {t.get_color('on_accent')}; border: none;"
            f"border-radius: {t.get_radius('sm')}px; padding: 0 10px;"
            f"font-size: 12px; }}"
            f"QPushButton:hover {{ background: "
            f"{t.get_color('primary_hover')}; }}")
        self.clear_btn.setStyleSheet(secondary_qss())
        self.list.setStyleSheet(
            f"QListWidget#fileList {{ background: transparent; border: none;"
            f"outline: none; padding: 4px; }}"
            f"QListWidget#fileList::item {{ border-radius: "
            f"{t.get_radius('sm')}px; padding: 8px 10px; margin: 2px 0; }}"
            f"QListWidget#fileList::item:hover {{ background: "
            f"{t.get_color('bg_hover')}; }}"
            f"QListWidget#fileList::item:selected {{ background: "
            f"{t.get_color('bg_selected')}; }}"
            f"QScrollBar:vertical {{ background: transparent; width: 8px;"
            f"margin: 0; }}"
            f"QScrollBar::handle:vertical {{ background: "
            f"{t.get_color('border')}; border-radius: 4px; min-height: 24px; }}"
            f"QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}"
            f"QScrollBar::add-page, QScrollBar::sub-page "
            f"{{ background: transparent; }}")

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 12, 8, 12)
        head = QHBoxLayout()
        head.setSpacing(6)
        self.title = QLabel("解析队列")
        head.addWidget(self.title)
        self.count_badge = QLabel("0")
        self.count_badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        head.addWidget(self.count_badge)
        head.addStretch(1)
        self.add_btn = QPushButton("+ 加文件")
        self.add_btn.setFixedHeight(24)
        self.add_btn.clicked.connect(self.add_files_requested)
        head.addWidget(self.add_btn)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(self.clear_btn)
        layout.addLayout(head)
        self.list = QListWidget()
        self.list.setObjectName('fileList')
        self.list.itemClicked.connect(self._on_item_clicked)
        # 右键菜单：删除单个文件
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)
        # 拖拽上传：面板与列表都接受 drop，列表事件经 eventFilter 转发
        self.setAcceptDrops(True)
        self.list.setAcceptDrops(True)
        self.list.installEventFilter(self)

    # ── 展示层 ───────────────────────────────────────────────

    def _rebuild(self):
        """按数据层整体重绘列表：分组标题 + 会话文件 + 历史分组（可折叠）"""
        selected = self.selected_path()
        self.list.blockSignals(True)
        self.list.clear()
        self._history_header_item = None
        session_ids = [f for f in self._order
                       if not self._items[f]["history"]]
        hist_ids = [f for f in self._order if self._items[f]["history"]]

        if not session_ids and not hist_ids:
            hint = QListWidgetItem("队列为空，点击「+ 加文件」添加文档")
            hint.setFlags(Qt.ItemFlag.NoItemFlags)
            hint.setData(_GROUP_ROLE, "empty")
            self.list.addItem(hint)
        else:
            if session_ids:
                self.list.addItem(self._title_item(
                    f"本次会话 ({len(session_ids)})"))
                for fid in session_ids:
                    self.list.addItem(self._make_item(fid))
            if hist_ids:
                arrow = "▾" if self._history_open else "▸"
                self._history_header_item = self._title_item(
                    f"历史记录 ({len(hist_ids)}) {arrow}", toggler=True)
                self.list.addItem(self._history_header_item)
                if self._history_open:
                    for fid in hist_ids:
                        self.list.addItem(self._make_item(fid))

        # 恢复原选中项（重绘后 item 对象已替换）
        if selected:
            for i in range(self.list.count()):
                it = self.list.item(i)
                if it.data(Qt.ItemDataRole.UserRole) == selected:
                    self.list.setCurrentItem(it)
                    break
        self.list.blockSignals(False)
        self._update_count()

    def _title_item(self, text: str, toggler: bool = False) -> QListWidgetItem:
        """分组标题行：不可选、灰色小字；toggler 行可点击折叠/展开"""
        item = QListWidgetItem(text)
        item.setFlags(Qt.ItemFlag.NoItemFlags)
        f = item.font()
        f.setPointSize(11)
        f.setWeight(QFont.Weight.DemiBold)
        item.setFont(f)
        item.setForeground(QColor(ThemeManager.get_color('text_disabled')))
        item.setData(Qt.ItemDataRole.UserRole, None)
        if toggler:
            item.setToolTip("点击展开历史文件；选中后点「重试」单独解析")
            item.setData(_GROUP_ROLE, "history")
        return item

    def _make_item(self, fid: str) -> QListWidgetItem:
        """文件行：两行文案（文件名 + 状态·详情），状态色映射到整行前景"""
        meta = self._items[fid]
        item = QListWidgetItem(os.path.basename(meta["path"]))
        item.setData(Qt.ItemDataRole.UserRole, meta["path"])
        item.setToolTip(meta["path"])
        item.setText(f"{os.path.basename(meta['path'])}\n{self.status_text(fid)}")
        status, _ = self._status.get(fid, ("queued", ""))
        role = _STATUS_COLOR.get(status, "text_secondary")
        item.setForeground(QColor(ThemeManager.get_color(role)))
        return item

    # ── 数据层 API（语义保持不变） ───────────────────────────

    def add_file(self, path: str, history: bool = False) -> str:
        """加入文件：history=False 为本次会话（优先置顶），True 进历史分组"""
        fid = uuid.uuid4().hex
        self._items[fid] = {"path": path, "time": datetime.now(),
                            "history": history}
        self._status[fid] = ("queued", "")
        self._order.append(fid)
        self._rebuild()
        return fid

    def select_file(self, fid: str) -> None:
        meta = self._items.get(fid)
        if meta is None:
            return
        for i in range(self.list.count()):
            it = self.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == meta["path"]:
                self.list.setCurrentItem(it)
                self._on_item_clicked(it)
                return

    def set_status(self, fid: str, status: str, detail: str = "") -> None:
        self._status[fid] = (status, detail)
        self._rebuild()

    def status_text(self, fid: str) -> str:
        status, detail = self._status.get(fid, ("queued", ""))
        text = _STATUS_TEXT.get(status, status)
        return f"{text}" + (f" · {detail}" if detail else "")

    def remove_file(self, fid: str) -> None:
        if fid not in self._items:
            return
        path = self._items[fid]["path"]
        del self._items[fid]
        self._status.pop(fid, None)
        if fid in self._order:
            self._order.remove(fid)
        self._rebuild()
        self.file_remove_requested.emit(path)

    def clear(self) -> None:
        self._items.clear()
        self._status.clear()
        self._order.clear()
        self._rebuild()

    def paths(self) -> List[str]:
        return [self._items[fid]["path"] for fid in self._order]

    def file_id_by_path(self, path: str):
        """按路径查 file_id（不存在返回 None）"""
        for fid, meta in self._items.items():
            if meta["path"] == path:
                return fid
        return None

    def session_paths(self) -> List[str]:
        """仅本次会话文件的路径（计数角标/会话分组依据）"""
        return [self._items[fid]["path"] for fid in self._order
                if not self._items[fid]["history"]]

    def queued_paths(self) -> List[str]:
        """状态为等待（queued）的本次会话文件路径——「解析」按钮的处理对象。

        历史分组文件不参与批量解析（避免误处理恢复的旧文件），
        需要时选中后点「重试」单独解析。"""
        return [self._items[fid]["path"] for fid in self._order
                if not self._items[fid]["history"]
                and self._status.get(fid, ("queued", ""))[0] == "queued"]

    def is_history_file(self, fid) -> bool:
        """该 fid 是否属于历史分组（不属于面板时返回 False）"""
        meta = self._items.get(fid)
        return bool(meta and meta["history"])

    def selected_path(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _update_count(self):
        self.count_badge.setText(str(len(self.session_paths())))
        # 队列空时「清空」无意义 → 禁用（数据变化即刷新）
        self.clear_btn.setEnabled(bool(self._items))

    # ── 拖拽上传 ─────────────────────────────────────────────

    def eventFilter(self, obj, event):
        """列表的拖拽事件转发到面板处理（统一高亮/过滤/信号语义）"""
        if obj is self.list and event.type() in (
                QEvent.Type.DragEnter, QEvent.Type.DragLeave,
                QEvent.Type.Drop):
            if event.type() == QEvent.Type.DragEnter:
                self.dragEnterEvent(event)
            elif event.type() == QEvent.Type.DragLeave:
                self.dragLeaveEvent(event)
            else:
                self.dropEvent(event)
            return True
        return super().eventFilter(obj, event)

    def _droppable_paths(self, event) -> List[str]:
        """从 MIME urls 过滤出白名单扩展名的本地文件路径（空列表 = 不可拖入）"""
        if not event.mimeData().hasUrls():
            return []
        paths = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path and os.path.splitext(path)[1].lower() in _DROP_EXTS:
                paths.append(path)
        return paths

    def dragEnterEvent(self, event):
        if self._droppable_paths(event):
            self._drag_active = True
            self._update_drag_style()
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragLeaveEvent(self, event):
        if self._drag_active:
            self._drag_active = False
            self._update_drag_style()

    def dropEvent(self, event):
        paths = self._droppable_paths(event)
        if self._drag_active:
            self._drag_active = False
            self._update_drag_style()
        if paths:
            event.acceptProposedAction()
            self.files_dropped.emit(paths)
        else:
            event.ignore()

    def _update_drag_style(self):
        """拖拽悬停高亮：accent 8% 底 + accent 边框；复位时恢复默认卡片样式"""
        t = ThemeManager
        if self._drag_active:
            c = QColor(t.get_color('primary'))
            c.setAlphaF(0.08)
            self.setStyleSheet(
                f"QWidget#panelCard {{ background: rgba({c.red()}, {c.green()}, "
                f"{c.blue()}, {round(c.alphaF() * 255)});"
                f"border: 1px solid {t.get_color('primary')};"
                f"border-radius: {t.get_radius('md')}px; }}")
        else:
            self.apply_theme()

    # ── 交互 ─────────────────────────────────────────────────

    def _on_item_clicked(self, item):
        """点文件行→选中；点分组标题行→折叠/展开历史"""
        if item.data(_GROUP_ROLE) == "history":
            self._history_open = not self._history_open
            self._rebuild()
            return
        path = item.data(Qt.ItemDataRole.UserRole)
        if path is not None:
            self.file_selected.emit(path)

    def _on_context_menu(self, pos):
        """右键菜单：删除该文件（分组标题/占位行不弹菜单）"""
        item = self.list.itemAt(pos)
        if item is None:
            return
        fid = self._fid_by_item(item)
        if fid is None:
            return
        menu = QMenu(self)
        menu.addAction("删除该文件", lambda: self._remove_item(item))
        menu.exec(self.list.mapToGlobal(pos))

    def _remove_item(self, item):
        fid = self._fid_by_item(item)
        if fid is not None:
            self.remove_file(fid)

    def _fid_by_item(self, item):
        path = item.data(Qt.ItemDataRole.UserRole)
        if path is None:
            return None
        return self.file_id_by_path(path)