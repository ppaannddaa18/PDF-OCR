"""PaddleOCR-VL 模型设置页 — 表单 + 操作带（保存并应用/重启引擎/重置）

仿 GgufSettingsPage 模式：表单（可嵌入页面）+ 操作带；
信号 save_requested / restart_requested 由主窗口处理（合并补丁 + 写盘 + 重启引擎）。
"""
import copy

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QScrollArea,
                             QGridLayout, QLineEdit)
from qfluentwidgets import (BodyLabel, SubtitleLabel, HorizontalSeparator,
                            SwitchButton, PushButton)

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss

TOOLTIPS = {
    "block_spotting": "布局切块 + 每块 Spotting（坐标自动映射回整页）。"
                      "纯文本文档可省 ~25% 时间；表格文档收益有限（表格是单一大块）",
    "max_new_tokens": "生成上限。native 无重复惩罚，上限过大时重复循环会拖长耗时",
    "repetition_penalty": "重复抑制，注入 generation_config 打破 greedy 重复循环（0 = 禁用）",
    "vision_sdpa": "视觉注意力 SDPA（flash）：显存峰值 6.4→4.2GB，质量无损",
    "spotting_max_pixels": "图像像素上限（默认官方 1605632，坐标精度优先；"
                          "8GB 卡显存紧张时可降低，代价是坐标精度下降）",
}

_DEFAULTS = {
    "max_new_tokens": 4096,
    "repetition_penalty": 1.1,
    "vision_sdpa": 1,
    "spotting_max_pixels": 1605632,
    "block_spotting": 0,
}


class PaddleVlSettingsForm(QWidget):
    """PaddleOCR-VL 引擎参数设置表单"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._config = copy.deepcopy(config)
        self._init_ui()
        self._load_settings()
        ThemeManager.register_refresh_callback(self._apply_theme_styles)

    # ── UI 构建 ────────────────────────────────────────────────

    def _init_ui(self):
        self.setMinimumSize(560, 420)
        self._theme_inputs = []  # QLineEdit（数值输入框）

        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("""
            QScrollArea { border: none; background: transparent; }
            QScrollArea > QWidget > QWidget { background: transparent; }
        """)

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title_layout = QHBoxLayout()
        title = SubtitleLabel("PaddleOCR-VL 模型设置")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        content_layout.addLayout(title_layout)

        self._hint_label = BodyLabel(
            "参数保存后需重启引擎生效（重新加载管线 ~15s）")
        self._hint_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')}; font-size: 12px;")
        content_layout.addWidget(self._hint_label)

        content_layout.addWidget(HorizontalSeparator())

        # ===== 识别模式 =====
        content_layout.addLayout(self._create_section_title("识别模式"))
        mode_grid = QGridLayout()
        mode_grid.setSpacing(10)
        mode_grid.setColumnStretch(1, 1)
        sw = self._create_switch("逐块 Spotting（布局切块）",
                                 TOOLTIPS["block_spotting"])
        self.sw_block_spotting = sw["switch"]
        mode_grid.addLayout(sw["layout"], 0, 0, 1, 3)
        content_layout.addLayout(mode_grid)

        # ===== 生成参数 =====
        content_layout.addLayout(self._create_section_title("生成参数"))
        gen_grid = QGridLayout()
        gen_grid.setSpacing(10)
        gen_grid.setColumnStretch(1, 1)

        self.ed_max_tokens = self._make_value_edit("4096")
        self._add_value_row(gen_grid, 0, "生成上限 (max_new_tokens)",
                            self.ed_max_tokens, TOOLTIPS["max_new_tokens"])

        self.ed_repetition_penalty = self._make_value_edit("1.1")
        self._add_value_row(gen_grid, 1, "重复抑制 (repetition_penalty)",
                            self.ed_repetition_penalty,
                            TOOLTIPS["repetition_penalty"])

        sw = self._create_switch("视觉注意力 SDPA（flash）",
                                 TOOLTIPS["vision_sdpa"])
        self.sw_vision_sdpa = sw["switch"]
        gen_grid.addLayout(sw["layout"], 2, 0, 1, 3)

        self.ed_spotting_max_pixels = self._make_value_edit("1605632")
        self._add_value_row(gen_grid, 3, "图像像素上限 (spotting_max_pixels)",
                            self.ed_spotting_max_pixels,
                            TOOLTIPS["spotting_max_pixels"])

        content_layout.addLayout(gen_grid)
        content_layout.addStretch()

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    # ── helpers ────────────────────────────────────────────────

    def _create_section_title(self, text: str) -> QHBoxLayout:
        layout = QHBoxLayout()
        label = SubtitleLabel(text)
        label.setStyleSheet("font-weight: bold; font-size: 15px; margin-top: 8px;")
        layout.addWidget(label)
        layout.addStretch()
        return layout

    def _create_switch(self, text: str, tooltip: str = "") -> dict:
        layout = QHBoxLayout()
        layout.setSpacing(8)
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
        switch = SwitchButton()
        switch.setOnText("开")
        switch.setOffText("关")
        if tooltip:
            switch.setToolTip(tooltip)
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(switch)
        return {"layout": layout, "switch": switch, "label": label}

    def _make_value_edit(self, default: str) -> QLineEdit:
        edit = QLineEdit(default)
        edit.setFixedWidth(140)
        self._theme_inputs.append(edit)
        return edit

    def _add_value_row(self, grid, row, text, line_edit, tooltip: str = ""):
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
            line_edit.setToolTip(tooltip)
        grid.addWidget(label, row, 0)
        grid.addWidget(line_edit, row, 1, 1, 2)

    @staticmethod
    def _parse_int(text: str, default: int) -> int:
        try:
            return int(text.strip())
        except (ValueError, AttributeError):
            return default

    @staticmethod
    def _parse_float(text: str, default: float) -> float:
        try:
            return float(text.strip())
        except (ValueError, AttributeError):
            return default

    def _load_settings(self):
        cfg = self._config.get("ocr", {}).get("paddle_vl", {})
        self.sw_block_spotting.setChecked(bool(cfg.get("block_spotting", 0)))
        self.ed_max_tokens.setText(str(cfg.get("max_new_tokens", 4096)))
        self.ed_repetition_penalty.setText(
            str(cfg.get("repetition_penalty", 1.1)))
        self.sw_vision_sdpa.setChecked(bool(cfg.get("vision_sdpa", 1)))
        self.ed_spotting_max_pixels.setText(
            str(cfg.get("spotting_max_pixels", 1605632)))

    def get_config_patch(self) -> dict:
        """获取配置补丁（用于合并到主配置）"""
        patch = {
            "ocr": {"paddle_vl": {
                "block_spotting": 1 if self.sw_block_spotting.isChecked() else 0,
                "max_new_tokens": self._parse_int(self.ed_max_tokens.text(), 4096),
                "repetition_penalty": self._parse_float(
                    self.ed_repetition_penalty.text(), 1.1),
                "vision_sdpa": 1 if self.sw_vision_sdpa.isChecked() else 0,
                "spotting_max_pixels": self._parse_int(
                    self.ed_spotting_max_pixels.text(), 1605632),
            }},
        }
        return patch

    def _on_default(self):
        """恢复默认值（不写盘，需点击保存生效）"""
        self.sw_block_spotting.setChecked(bool(_DEFAULTS["block_spotting"]))
        self.ed_max_tokens.setText(str(_DEFAULTS["max_new_tokens"]))
        self.ed_repetition_penalty.setText(str(_DEFAULTS["repetition_penalty"]))
        self.sw_vision_sdpa.setChecked(bool(_DEFAULTS["vision_sdpa"]))
        self.ed_spotting_max_pixels.setText(str(_DEFAULTS["spotting_max_pixels"]))

    def _apply_theme_styles(self):
        hint = getattr(self, '_hint_label', None)
        if hint is not None:
            hint.setStyleSheet(
                f"color: {ThemeManager.get_color('text_secondary')}; font-size: 12px;")
        border = ThemeManager.get_color('border')
        bg = ThemeManager.get_color('bg_surface')
        primary = ThemeManager.get_color('primary')
        for line_edit in self._theme_inputs:
            line_edit.setStyleSheet(f"""
                QLineEdit {{
                    border: 1px solid {border};
                    border-radius: 4px;
                    padding: 4px 8px;
                    background: {bg};
                    color: {ThemeManager.get_color('text_primary')};
                    selection-background-color: {primary};
                    selection-color: {ThemeManager.get_color('on_accent')};
                }}
            """)


class PaddleVlSettingsPage(QWidget):
    """PaddleOCR-VL 模型设置页：表单 + 操作带（重启引擎/保存并应用/重置）"""

    save_requested = Signal(dict)      # patch
    restart_requested = Signal(dict)   # patch

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.form = PaddleVlSettingsForm(config, self)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.form, 1)

        # 操作带
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 8, 24, 12)
        bar_layout.setSpacing(12)
        bar_layout.addStretch()

        self.btn_restart = PushButton("重启引擎")
        self.btn_restart.setFixedWidth(110)
        self.btn_restart.clicked.connect(
            lambda: self.restart_requested.emit(self.get_config_patch()))
        bar_layout.addWidget(self.btn_restart)

        self.btn_save = PushButton("保存并应用")
        self.btn_save.setFixedWidth(120)
        self.btn_save.setStyleSheet(primary_qss())
        self.btn_save.clicked.connect(
            lambda: self.save_requested.emit(self.get_config_patch()))
        bar_layout.addWidget(self.btn_save)

        self.btn_reset = PushButton("重置")
        self.btn_reset.setFixedWidth(80)
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        bar_layout.addWidget(self.btn_reset)

        layout.addWidget(bar)

    def get_config_patch(self) -> dict:
        return self.form.get_config_patch()

    def _on_reset_clicked(self):
        self.form._on_default()
