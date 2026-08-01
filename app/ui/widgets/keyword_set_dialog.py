"""关键字集管理对话框 — 列出/保存/删除命名集合"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QLineEdit, QPushButton, QMessageBox, QLabel)

from app.ui.theme_manager import ThemeManager


class KeywordSetDialog(QDialog):
    """管理对话框：左列表 + 右操作。静态 ask_name() 用于快速命名保存。"""

    def __init__(self, set_manager, parent=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self.setWindowTitle("管理关键字集")
        self.setMinimumSize(420, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("已保存的集合:"))
        self.list_widget = QListWidget()
        self._refresh_list()
        layout.addWidget(self.list_widget)
        btns = QHBoxLayout()
        self.btn_load = QPushButton("加载")
        self.btn_load.clicked.connect(self._on_load)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_load, self.btn_delete, self.btn_close):
            btns.addWidget(b)
        layout.addLayout(btns)

    def _refresh_list(self):
        self.list_widget.clear()
        self.list_widget.addItems(self.set_manager.list_sets())

    def _on_load(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        kws = self.set_manager.load(item.text())
        if kws:
            self.accept()
            self._loaded = (item.text(), kws)
        else:
            self._loaded = None

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "确认", f"删除集合「{item.text()}」？") \
                == QMessageBox.StandardButton.Yes:
            self.set_manager.delete(item.text())
            self._refresh_list()

    def result_value(self):
        return getattr(self, "_loaded", None)

    @staticmethod
    def ask_name(parent, existing: list):
        """快速命名保存对话框：返回 (name, ok)"""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            parent, "保存为集合", "集合名称：", text="")
        if not ok or not name.strip():
            return None, False
        return name.strip(), True
