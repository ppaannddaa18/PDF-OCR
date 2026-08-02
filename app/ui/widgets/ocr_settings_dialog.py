"""
OCR 引擎设置对话框（Deprecated，Task P5）

OcrSettingsDialog 已重构为可嵌入的 GgufSettingsForm（gguf_settings_page.py）。
本文件保留 thin wrapper：内部包一层 GgufSettingsForm（show_theme_options=True，
保留主题三单选供旧 MainWindow / Rapid 窗口使用），并通过 __getattr__ 代理
表单属性（rb_theme_* / sw_animations / _theme_sliders / _on_default 等），
保证旧引用与 tests/ui/test_theme_refresh.py 不断。P7 统一删除。
"""
import warnings

from PyQt6.QtCore import pyqtSignal as Signal
from PyQt6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout
from qfluentwidgets import PushButton

from app.ui.animation_manager import AnimationManager
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.gguf_settings_page import GgufSettingsForm


class OcrSettingsDialog(QDialog):
    """OCR 引擎设置对话框（Deprecated: use GgufSettingsPage/GgufSettingsForm）"""

    settings_applied = Signal(dict)

    def __init__(self, config: dict, parent=None):
        warnings.warn(
            "OcrSettingsDialog is deprecated; use GgufSettingsPage/GgufSettingsForm",
            DeprecationWarning,
            stacklevel=2,
        )
        super().__init__(parent)
        self.setWindowTitle("PaddleOCR-VL-1.6 解析配置")
        self.setMinimumSize(600, 700)
        self.resize(650, 750)
        self.setModal(True)

        self.form = GgufSettingsForm(config, self, show_theme_options=True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.form, 1)

        # 底部按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.setContentsMargins(24, 12, 24, 24)

        self.btn_default = PushButton("恢复默认")
        self.btn_default.setFixedWidth(100)
        self.btn_default.clicked.connect(self.form._on_default)
        btn_layout.addWidget(self.btn_default)

        btn_layout.addStretch()

        self.btn_apply = PushButton("应用并重启")
        self.btn_apply.setFixedWidth(120)
        self.btn_apply.setStyleSheet(f"""
            PushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: {ThemeManager.get_color('white')};
                font-weight: bold;
            }}
            PushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)

        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        layout.addLayout(btn_layout)

        # 主题切换后重烘焙 btn_apply QSS（与旧对话框行为一致）
        ThemeManager.register_refresh_callback(self._refresh_apply_button)

    def _refresh_apply_button(self):
        """重建应用按钮主题色 QSS"""
        btn_apply = getattr(self, 'btn_apply', None)
        if btn_apply is None:
            return
        btn_apply.setStyleSheet(f"""
            PushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: {ThemeManager.get_color('white')};
                font-weight: bold;
            }}
            PushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)

    def __getattr__(self, name: str):
        """代理表单属性（rb_theme_* / sw_animations / _theme_sliders / _on_default…）"""
        if name.startswith('__'):
            raise AttributeError(name)
        form = object.__getattribute__(self, 'form')
        return getattr(form, name)

    def _on_apply(self):
        """应用设置"""
        self.settings_applied.emit(self.form._get_settings())
        self.form.apply_animations()
        self.accept()

    def get_config_patch(self) -> dict:
        """获取配置补丁（用于合并到主配置）"""
        return self.form.get_config_patch()
