"""左侧文件列表：文件名 + 状态徽章 + 耗时 + 时间（参考 AI Studio 最近上传）"""
import os
import uuid
from datetime import datetime
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                             QListWidgetItem, QLabel, QPushButton, QMenu)

from app.ui.theme_manager import ThemeManager

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


class OcrFilePanel(QWidget):
    file_selected = pyqtSignal(str)          # path
    file_remove_requested = pyqtSignal(str)  # path
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # file_id -> (item, meta)
        self._status = {}  # file_id -> (status, detail)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        head = QHBoxLayout()
        title = QLabel("解析队列")
        title.setStyleSheet(f"color: {ThemeManager.get_color('text_secondary')};"
                            f"font-size: 13px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        self.clear_btn = QPushButton("清空")
        self.clear_btn.setFixedHeight(24)
        self.clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(self.clear_btn)
        layout.addLayout(head)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        # 右键菜单：删除单个文件
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._on_context_menu)
        layout.addWidget(self.list, 1)

    def add_file(self, path: str) -> str:
        fid = uuid.uuid4().hex
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self._items[fid] = (item, {"path": path, "time": datetime.now()})
        self._status[fid] = ("queued", "")
        item.setText(f"{os.path.basename(path)}\n{self.status_text(fid)}")
        self.list.addItem(item)
        return fid

    def select_file(self, fid: str) -> None:
        entry = self._items.get(fid)
        if entry is None:
            return
        item, _ = entry
        self.list.setCurrentItem(item)
        self._on_item_clicked(item)

    def set_status(self, fid: str, status: str, detail: str = "") -> None:
        self._status[fid] = (status, detail)
        item, meta = self._items[fid]
        item.setText(f"{os.path.basename(meta['path'])}\n{self.status_text(fid)}")
        # 徽章颜色：状态 → ThemeManager 角色 → 前景色（setText 不受影响）
        role = _STATUS_COLOR.get(status, "text_secondary")
        item.setForeground(QColor(ThemeManager.get_color(role)))

    def status_text(self, fid: str) -> str:
        status, detail = self._status.get(fid, ("queued", ""))
        text = _STATUS_TEXT.get(status, status)
        return f"{text}" + (f" · {detail}" if detail else "")

    def remove_file(self, fid: str) -> None:
        entry = self._items.pop(fid, None)
        if entry is None:
            return
        item, meta = entry
        self._status.pop(fid, None)
        self.list.takeItem(self.list.row(item))
        self.file_remove_requested.emit(meta["path"])

    def clear(self) -> None:
        self.list.clear()
        self._items.clear()
        self._status.clear()

    def paths(self) -> List[str]:
        return [m["path"] for _, m in self._items.values()]

    def file_id_by_path(self, path: str):
        """按路径查 file_id（不存在返回 None）"""
        for fid, (_, meta) in self._items.items():
            if meta["path"] == path:
                return fid
        return None

    def selected_path(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_item_clicked(self, item):
        self.file_selected.emit(item.data(Qt.ItemDataRole.UserRole))

    def _on_context_menu(self, pos):
        """右键菜单：删除该文件（item 为 None 不弹菜单）"""
        item = self.list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        menu.addAction("删除该文件", lambda: self._remove_item(item))
        menu.exec(self.list.mapToGlobal(pos))

    def _remove_item(self, item):
        fid = self._fid_by_item(item)
        if fid is not None:
            self.remove_file(fid)

    def _fid_by_item(self, item):
        for fid, (it, _) in self._items.items():
            if it is item:
                return fid
        return None
