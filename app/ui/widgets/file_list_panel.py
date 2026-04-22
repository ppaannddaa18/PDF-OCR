from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QLabel
from PySide6.QtCore import Signal
from pathlib import Path


class FileListPanel(QWidget):
    file_selected = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PDF 文件列表"))
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(
            lambda item: self.file_selected.emit(item.data(256))
        )
        layout.addWidget(self.list_widget)
        self.files = []

    def add_files(self, paths: list):
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.list_widget.addItem(Path(p).name)
                self.list_widget.item(self.list_widget.count()-1).setData(256, p)

    def current_file(self):
        item = self.list_widget.currentItem()
        return item.data(256) if item else None

    def all_files(self):
        return list(self.files)

    def clear_files(self):
        self.files.clear()
        self.list_widget.clear()
