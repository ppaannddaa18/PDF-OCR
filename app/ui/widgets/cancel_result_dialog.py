"""
批量取消结果对话框
用于显示批量识别取消后的部分结果统计
支持保存进度，下次启动时恢复
"""
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from qfluentwidgets import BodyLabel, PushButton, SubtitleLabel, CheckBox, InfoBar, InfoBarPosition
from pathlib import Path
import json
import logging
from datetime import datetime

from app.ui.theme_manager import ThemeManager

logger = logging.getLogger("PDFOCR")


# qtawesome 延迟加载（避免启动开销与字体警告）
_qta = None


def _get_qta():
    """获取 qtawesome 实例（延迟加载）"""
    global _qta
    if _qta is None:
        import qtawesome
        _qta = qtawesome
    return _qta


class CancelResultDialog(QDialog):
    """批量取消结果对话框"""

    # 返回值枚举
    VIEW_RESULTS = 1
    EXPORT = 2
    CONTINUE = 3
    CLOSE = 4
    SAVE_AND_EXIT = 5  # 新增：保存并退出

    # 待恢复任务文件路径
    PENDING_TASK_FILE = Path.home() / ".pdfocr" / "pending_task.json"

    def __init__(self, completed: int, success: int, failed: int, total: int,
                 pending_files: list = None, results: list = None, parent=None):
        super().__init__(parent)
        self.completed = completed
        self.success = success
        self.failed = failed
        self.total = total
        self.pending_files = pending_files or []
        self.results = results or []
        self._init_ui()

    def _init_ui(self):
        """初始化UI"""
        self.setWindowTitle("批量识别已取消")
        self.setFixedSize(400, 340)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(24, 24, 24, 24)

        # 标题区域
        title_layout = QHBoxLayout()
        self.icon_label = QLabel()
        self.icon_label.setPixmap(_get_qta().icon(
            'fa5s.exclamation-triangle',
            color=ThemeManager.get_color('warning')).pixmap(28, 28))
        title_layout.addWidget(self.icon_label)

        title = SubtitleLabel("批量识别已取消")
        title.setStyleSheet("font-weight: bold;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        layout.addLayout(title_layout)

        # 统计信息（Task 15：背景/富文本颜色走 ThemeManager，暗色模式适配；
        # 模态对话框构造时解析当前主题即可）
        self.stats_widget = QLabel()
        self.stats_widget.setStyleSheet(f"""
            background: {ThemeManager.get_color('bg_hover')};
            border-radius: 8px;
            padding: 12px;
        """)
        remaining = self.total - self.completed
        stats_text = f"""
<p style="margin: 0; font-size: 13px;">
    <b>已完成:</b> {self.completed}/{self.total} 个文件<br>
    <span style="color: {ThemeManager.get_color('success')};"><b>成功:</b> {self.success} 个</span><br>
    <span style="color: {ThemeManager.get_color('error')};"><b>失败:</b> {self.failed} 个</span><br>
    <span style="color: {ThemeManager.get_color('text_secondary')};"><b>剩余:</b> {remaining} 个未处理</span>
</p>
"""
        self.stats_widget.setText(stats_text)
        self.stats_widget.setWordWrap(True)
        layout.addWidget(self.stats_widget)

        # 提示信息
        tip_label = BodyLabel("已完成的识别结果已保存，您可以:")
        tip_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        layout.addWidget(tip_label)

        # 保存进度选项
        self.save_progress_checkbox = CheckBox("保存进度，下次启动时恢复")
        self.save_progress_checkbox.setChecked(True)
        self.save_progress_checkbox.setStyleSheet("margin-top: 8px;")
        layout.addWidget(self.save_progress_checkbox)

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

        # 底部按钮区域
        bottom_layout = QHBoxLayout()
        bottom_layout.setSpacing(8)

        self.btn_save_exit = PushButton("保存并退出")
        self.btn_save_exit.setFixedWidth(100)
        self.btn_save_exit.clicked.connect(self._on_save_and_exit)
        bottom_layout.addWidget(self.btn_save_exit)

        bottom_layout.addStretch()

        self.btn_close = PushButton("关闭")
        self.btn_close.setFixedWidth(80)
        self.btn_close.clicked.connect(lambda: self.done(self.CLOSE))
        bottom_layout.addWidget(self.btn_close)

        layout.addLayout(bottom_layout)

        # 如果没有已完成的结果，禁用相关按钮
        if self.completed == 0:
            self.btn_view.setEnabled(False)
            self.btn_export.setEnabled(False)

        # 如果所有文件都已处理，禁用继续和保存按钮
        if self.completed >= self.total:
            self.btn_continue.setEnabled(False)
            self.btn_save_exit.setEnabled(False)
            self.save_progress_checkbox.setEnabled(False)

        # 如果没有待处理文件，禁用保存选项
        if not self.pending_files:
            self.save_progress_checkbox.setEnabled(False)
            self.btn_save_exit.setEnabled(False)

    def _on_save_and_exit(self):
        """保存进度并退出"""
        if self.save_progress_checkbox.isChecked():
            self._save_pending_task()
        self.done(self.SAVE_AND_EXIT)

    def _save_pending_task(self):
        """保存待恢复的任务"""
        try:
            # 确保目录存在
            self.PENDING_TASK_FILE.parent.mkdir(parents=True, exist_ok=True)

            task_data = {
                "timestamp": datetime.now().isoformat(),
                "completed": self.completed,
                "total": self.total,
                "success": self.success,
                "failed": self.failed,
                "pending_files": self.pending_files,
                "results": [
                    {
                        "source_file": r.source_file if hasattr(r, 'source_file') else r.get('source_file', ''),
                        "fields": {
                            k: (
                                {"text": v.text, "confidence": v.confidence}
                                if hasattr(v, 'text') else
                                {"text": v.get('text', ''), "confidence": v.get('confidence', 0.0)}
                                if isinstance(v, dict) else
                                {"text": str(v), "confidence": 0.0}
                            )
                            for k, v in (r.fields.items() if hasattr(r, 'fields') else r.get('fields', {}).items())
                        } if (hasattr(r, 'fields') or isinstance(r, dict)) else {}
                    }
                    for r in self.results
                ]
            }

            with open(self.PENDING_TASK_FILE, 'w', encoding='utf-8') as f:
                json.dump(task_data, f, indent=2, ensure_ascii=False)

        except Exception as e:
            logger.error(f"保存待恢复任务失败: {e}", exc_info=True)
            InfoBar.error(
                title="保存失败",
                content=f"无法保存任务进度: {e}",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=5000,
                parent=self.parent() if self.parent() else self
            )

    @classmethod
    def has_pending_task(cls) -> bool:
        """检查是否存在待恢复的任务"""
        return cls.PENDING_TASK_FILE.exists()

    @classmethod
    def load_pending_task(cls) -> dict:
        """加载待恢复的任务"""
        try:
            if cls.PENDING_TASK_FILE.exists():
                with open(cls.PENDING_TASK_FILE, 'r', encoding='utf-8') as f:
                    return json.load(f)
        except Exception as e:
            import logging
            logging.getLogger("PDFOCR").warning(f"加载待恢复任务失败: {e}")
        return None

    @classmethod
    def clear_pending_task(cls):
        """清除待恢复的任务"""
        try:
            if cls.PENDING_TASK_FILE.exists():
                cls.PENDING_TASK_FILE.unlink()
        except Exception:
            pass
