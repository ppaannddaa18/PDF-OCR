"""
历史记录面板组件
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QListWidget, QListWidgetItem, QLabel, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from qfluentwidgets import SubtitleLabel, BodyLabel, PushButton, InfoBar, InfoBarPosition


class HistoryPanel(QWidget):
    """历史记录面板"""
    record_selected = Signal(str)  # 选中记录ID
    record_restored = Signal(str)  # 恢复记录

    def __init__(self, history_manager, parent=None):
        super().__init__(parent)
        self.history_manager = history_manager
        self._init_ui()
        self.refresh_list()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(8)

        # 标题
        title = SubtitleLabel("识别历史")
        layout.addWidget(title)

        # 说明文字
        desc = BodyLabel("最近10次识别任务，点击可查看详情")
        desc.setStyleSheet("color: #666;")
        layout.addWidget(desc)

        # 历史列表
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        # 详情区域
        self.detail_widget = QWidget()
        detail_layout = QVBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        detail_layout.setSpacing(4)

        self.detail_time = BodyLabel("")
        detail_layout.addWidget(self.detail_time)

        self.detail_stats = BodyLabel("")
        detail_layout.addWidget(self.detail_stats)

        self.detail_fields = BodyLabel("")
        detail_layout.addWidget(self.detail_fields)

        self.detail_export = BodyLabel("")
        detail_layout.addWidget(self.detail_export)

        # 恢复按钮
        self.btn_restore = PushButton("恢复此结果")
        self.btn_restore.setEnabled(False)
        self.btn_restore.clicked.connect(self._on_restore)
        detail_layout.addWidget(self.btn_restore)

        layout.addWidget(self.detail_widget)

        # 底部按钮
        btn_layout = QHBoxLayout()

        self.btn_refresh = PushButton("刷新")
        self.btn_refresh.clicked.connect(self.refresh_list)
        btn_layout.addWidget(self.btn_refresh)

        self.btn_clear = PushButton("清空历史")
        self.btn_clear.clicked.connect(self._on_clear_history)
        btn_layout.addWidget(self.btn_clear)

        layout.addLayout(btn_layout)

        self._current_record_id = None

    def refresh_list(self):
        """刷新历史列表"""
        self.list_widget.clear()
        history = self.history_manager.get_history()

        if not history:
            item = QListWidgetItem("暂无历史记录")
            item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEnabled)
            self.list_widget.addItem(item)
            return

        for record in history:
            text = f"{record.timestamp} - {record.file_count}个文件"
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, record.id)
            self.list_widget.addItem(item)

    def _on_item_clicked(self, item):
        """列表项点击"""
        record_id = item.data(Qt.ItemDataRole.UserRole)
        if not record_id:
            return

        self._current_record_id = record_id
        record = self.history_manager.get_record(record_id)
        if not record:
            return

        self.detail_time.setText(f"时间: {record.timestamp}")
        self.detail_stats.setText(f"文件数: {record.file_count} | 成功: {record.success_count}")
        self.detail_fields.setText(f"字段: {', '.join(record.field_names[:5])}{'...' if len(record.field_names) > 5 else ''}")

        if record.export_path:
            self.detail_export.setText(f"导出: {record.export_path}")
            self.detail_export.setVisible(True)
        else:
            self.detail_export.setVisible(False)

        self.btn_restore.setEnabled(True)
        self.record_selected.emit(record_id)

    def _on_restore(self):
        """恢复按钮点击"""
        if self._current_record_id:
            self.record_restored.emit(self._current_record_id)

    def _on_clear_history(self):
        """清空历史"""
        self.history_manager.clear_history()
        self.refresh_list()
        self.detail_widget.setVisible(False)
        self.btn_restore.setEnabled(False)
        self._current_record_id = None
