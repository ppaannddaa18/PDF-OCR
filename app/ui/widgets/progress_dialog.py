from PySide6.QtWidgets import QProgressDialog
from PySide6.QtCore import Signal


class ProgressDialog(QProgressDialog):
    cancelled = Signal()

    def __init__(self, title: str = "处理中", parent=None):
        super().__init__(title, "取消", 0, 100, parent)
        self.setWindowTitle(title)
        self.setAutoClose(True)
        self.setAutoReset(True)
        self.canceled.connect(self._on_cancel)

    def _on_cancel(self):
        self.cancelled.emit()

    def update_progress(self, current: int, total: int, message: str = ""):
        self.setMaximum(total)
        self.setValue(current)
        if message:
            self.setLabelText(message)
