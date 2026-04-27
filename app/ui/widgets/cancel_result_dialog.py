"""
批量取消结果对话框
用于显示批量识别取消后的部分结果统计
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from qfluentwidgets import BodyLabel, PushButton, SubtitleLabel


class CancelResultDialog(QDialog):
    """批量取消结果对话框"""

    # 返回值枚举
    VIEW_RESULTS = 1
    EXPORT = 2
    CONTINUE = 3
    CLOSE = 4

    def __init__(self, completed: int, success: int, failed: int, total: int, parent=None):
        super().__init__(parent)
        self.completed = completed
        self.success = success
        self.failed = failed
        self.total = total
        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("批量识别已取消")
        self.setFixedSize(360, 260)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题区域
        title_layout = QHBoxLayout()
        icon_label = QLabel("⚠️")
        icon_label.setStyleSheet("font-size: 24px;")
        title_layout.addWidget(icon_label)

        title = SubtitleLabel("批量识别已取消")
        title.setStyleSheet("font-weight: bold;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 统计信息
        stats_widget = QLabel()
        stats_widget.setStyleSheet("""
            background: #f5f5f5;
            border-radius: 8px;
            padding: 12px;
        """)
        stats_text = f"""
<p style="margin: 0; font-size: 13px;">
    <b>已完成:</b> {self.completed}/{self.total} 个文件<br>
    <span style="color: #107c10;"><b>成功:</b> {self.success} 个</span><br>
    <span style="color: #d83b01;"><b>失败:</b> {self.failed} 个</span>
</p>
"""
        stats_widget.setText(stats_text)
        stats_widget.setWordWrap(True)
        layout.addWidget(stats_widget)

        # 提示信息
        tip_label = BodyLabel("已完成的识别结果已保存，您可以:")
        tip_label.setStyleSheet("color: #666;")
        layout.addWidget(tip_label)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(8)

        self.btn_view = PushButton("查看结果")
        self.btn_view.setFixedWidth(90)
        self.btn_view.clicked.connect(lambda: self.done(self.VIEW_RESULTS))
        btn_layout.addWidget(self.btn_view)

        self.btn_export = PushButton("导出已完成")
        self.btn_export.setFixedWidth(100)
        self.btn_export.clicked.connect(lambda: self.done(self.EXPORT))
        btn_layout.addWidget(self.btn_export)

        self.btn_continue = PushButton("继续识别")
        self.btn_continue.setFixedWidth(90)
        self.btn_continue.clicked.connect(lambda: self.done(self.CONTINUE))
        btn_layout.addWidget(self.btn_continue)

        layout.addLayout(btn_layout)

        # 关闭按钮
        btn_close_layout = QHBoxLayout()
        btn_close_layout.addStretch()
        self.btn_close = PushButton("关闭")
        self.btn_close.setFixedWidth(80)
        self.btn_close.clicked.connect(lambda: self.done(self.CLOSE))
        btn_close_layout.addWidget(self.btn_close)
        layout.addLayout(btn_close_layout)

        # 如果没有已完成的结果，禁用相关按钮
        if self.completed == 0:
            self.btn_view.setEnabled(False)
            self.btn_export.setEnabled(False)

        # 如果所有文件都已处理，禁用继续按钮
        if self.completed >= self.total:
            self.btn_continue.setEnabled(False)
