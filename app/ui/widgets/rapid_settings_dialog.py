"""RapidOCR 设置对话框（Task P7）

Rapid 窗口无模型参数（固定 rapidocr），设置入口只保留外观项：
动画开关（禁用动画）。原 OcrSettingsDialog（GGUF 参数对话框）已在 P7
删除，其 GGUF 功能由 GgufSettingsPage 承担。
"""
import copy

from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
from qfluentwidgets import PushButton, BodyLabel, HorizontalSeparator, SwitchButton

from app.ui.animation_manager import AnimationManager


class RapidSettingsDialog(QDialog):
    """Rapid 设置对话框：仅外观（动画开关）"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = copy.deepcopy(config)
        self.setWindowTitle("设置")
        self.setMinimumSize(420, 220)
        self.setModal(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 20)
        layout.setSpacing(14)

        title = BodyLabel("外观设置")
        title.setStyleSheet("font-weight: bold; font-size: 15px;")
        layout.addWidget(title)
        layout.addWidget(HorizontalSeparator())

        # 动画开关（勾选 = 禁用动画）
        row_layout = QHBoxLayout()
        row_layout.setSpacing(8)
        label = BodyLabel("禁用动画")
        label.setToolTip(
            "关闭折叠、滑入滑出等界面动画，界面变化即时生效（尊重系统动画偏好）")
        switch = SwitchButton()
        switch.setOnText("开")
        switch.setOffText("关")
        appearance = self._config.get("appearance", {})
        switch.setChecked(not appearance.get("animations_enabled", True))
        self.sw_animations = switch
        row_layout.addWidget(label)
        row_layout.addStretch()
        row_layout.addWidget(switch)
        layout.addLayout(row_layout)

        layout.addStretch()

        btn_layout = QHBoxLayout()
        btn_layout.addStretch()
        self.btn_ok = PushButton("保存")
        self.btn_ok.setFixedWidth(100)
        self.btn_ok.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_ok)
        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)
        layout.addLayout(btn_layout)

    def _on_apply(self):
        """保存并应用动画设置"""
        AnimationManager.set_enabled(not self.sw_animations.isChecked())
        self.accept()

    def get_config_patch(self) -> dict:
        """获取配置补丁（合并到主配置）"""
        return {
            "appearance": {
                "animations_enabled": not self.sw_animations.isChecked(),
            },
        }
