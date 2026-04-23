from PyQt6.QtWidgets import QWidget, QVBoxLayout
from PyQt6.QtCore import pyqtSignal as Signal, Qt
from qfluentwidgets import SubtitleLabel, ListWidget, PushButton, BodyLabel
from pathlib import Path


class FileListPanel(QWidget):
    file_selected = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setSpacing(8)

        # Fluent 标题
        title = SubtitleLabel("文件列表")
        layout.addWidget(title)

        # Fluent 列表
        self.list_widget = ListWidget()
        self.list_widget.itemClicked.connect(
            lambda item: self.file_selected.emit(item.data(256))
        )
        layout.addWidget(self.list_widget, 1)

        # 空状态提示
        self.empty_label = BodyLabel("暂无文件\n点击上方「上传」按钮添加")
        self.empty_label.setStyleSheet("color: #888; text-align: center;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        layout.addWidget(self.empty_label)
        self.empty_label.setVisible(True)

        # 操作按钮
        self.btn_remove = PushButton("移除选中")
        self.btn_remove.clicked.connect(self.remove_selected)
        layout.addWidget(self.btn_remove)

        self.btn_clear = PushButton("清空全部")
        self.btn_clear.clicked.connect(self.clear_files)
        layout.addWidget(self.btn_clear)

        self.files = []
        self._update_empty_state()

    def _update_empty_state(self):
        has_files = len(self.files) > 0
        self.empty_label.setVisible(not has_files)
        self.list_widget.setVisible(has_files)
        self.btn_remove.setEnabled(has_files)
        self.btn_clear.setEnabled(has_files)

    def add_files(self, paths: list):
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.list_widget.addItem(Path(p).name)
                self.list_widget.item(self.list_widget.count()-1).setData(256, p)
        self._update_empty_state()

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item:
            path = item.data(256)
            if path in self.files:
                self.files.remove(path)
            self.list_widget.takeItem(self.list_widget.row(item))
            self._update_empty_state()

    def current_file(self):
        item = self.list_widget.currentItem()
        return item.data(256) if item else None

    def all_files(self):
        return list(self.files)

    def clear_files(self):
        self.files.clear()
        self.list_widget.clear()
        self._update_empty_state()
