"""解析配置弹窗（参考 AI Studio 解析配置：辅助内容过滤 + 模型参数 + 采样参数）

方向/扭曲矫正是 PaddleOCRVL 构造期参数：开启会加载 DocPreprocessor 子
管线（额外显存占用），修改后需重启引擎生效（窗口层 apply_config 返回
True 时自动重启）。"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QFormLayout, QCheckBox, QDoubleSpinBox, QSpinBox,
                             QPushButton, QLabel)

# 模型参数组内提示（灰色小字）
_UNSUPPORTED_HINT = "开启将加载文档预处理模块（额外显存占用）；修改后需重启引擎生效"

# 辅助内容标签 → (显示名, 默认恢复解析?)
_AUX_ITEMS = [
    ("header", "页眉", False),
    ("header_image", "页眉图片", False),
    ("footer", "页脚", False),
    ("footer_image", "页脚图片", False),
    ("number", "页码", True),
    ("footnote", "脚注", False),
    ("aside_text", "旁注文本", False),
]

# 模型参数开关：配置键 → (显示名, 默认值)
_MODEL_SWITCHES = [
    ("use_doc_orientation_classify", "图片方向矫正", False),
    ("use_doc_unwarping", "图片扭曲矫正", False),
    ("use_layout_detection", "版面分析", False),
    ("use_chart_recognition", "图表识别", True),
    ("use_seal_recognition", "印章识别", True),
    ("use_ocr_for_image_block", "图片文字识别", True),
    ("merge_layout_blocks", "跨页表格合并", True),
]


class OcrParseConfigDialog(QDialog):
    """解析配置弹窗：应用 → apply_requested(patch)；重置 → 恢复默认"""

    apply_requested = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解析配置")
        self.setMinimumWidth(520)
        pv = config.get("ocr", {}).get("paddle_vl", {})
        self._build_ui(pv)

    # —— 构建 ——
    def _build_ui(self, pv: dict):
        # 辅助内容过滤组：check = 恢复解析（不忽略）
        # 空配置（键缺失）回退默认忽略集（与 defaults() 一致：仅页码默认恢复）
        ignore = set(pv.get(
            "markdown_ignore_labels",
            [label for label, _, default in _AUX_ITEMS if not default]))
        self._aux_checks = {}
        aux_group = QGroupBox("辅助内容解析")
        form = QFormLayout(aux_group)
        for label, name, _ in _AUX_ITEMS:
            chk = QCheckBox(name)
            chk.setChecked(label not in ignore)
            self._aux_checks[label] = chk
            form.addRow(chk)
        # 灰色小字提示：辅助内容过滤仅逐块模式（开启版面分析）生效，
        # 整页模式输出整页 markdown 无布局标签，该组配置不参与过滤
        aux_hint = QLabel("仅开启版面分析（逐块模式）时生效")
        aux_hint.setStyleSheet("color: gray; font-size: 11px;")
        form.addRow(aux_hint)
        # 模型参数组（开关）
        self._model_switches = {}
        model_group = QGroupBox("模型参数设置")
        mform = QFormLayout(model_group)
        for key, name, default in _MODEL_SWITCHES:
            chk = QCheckBox(name)
            checked = bool(pv.get(key, default))
            # 兼容读点：既有设置页（paddle_vl_settings_page）与引擎读写的是
            # block_spotting（与 use_layout_detection 等价），任一开启即勾选，
            # 避免用户在设置页开启后本弹窗应用时静默写回关闭
            if key == "use_layout_detection":
                checked = checked or bool(pv.get("block_spotting", False))
            chk.setChecked(checked)
            self._model_switches[key] = chk
            mform.addRow(chk)
        hint = QLabel(_UNSUPPORTED_HINT)
        hint.setStyleSheet("color: gray; font-size: 11px;")
        mform.addRow(hint)
        # 采样参数组
        self._rep_spin = QDoubleSpinBox()
        self._rep_spin.setRange(0.0, 2.0)
        self._rep_spin.setSingleStep(0.1)
        self._rep_spin.setDecimals(1)  # 显示 1.1 而非 1.10
        self._rep_spin.setValue(float(pv.get("repetition_penalty", 1.1) or 0))
        self._min_px = QSpinBox()
        self._min_px.setRange(0, 100_000_000)
        self._min_px.setValue(int(pv.get("spotting_min_pixels", 0) or 0))
        self._max_px = QSpinBox()
        self._max_px.setRange(0, 100_000_000)
        self._max_px.setValue(int(pv.get("spotting_max_pixels", 1605632) or 1605632))
        sample_group = QGroupBox("文本检测与识别")
        sform = QFormLayout(sample_group)
        sform.addRow("重复抑制强度", self._rep_spin)
        sform.addRow("图像最小总像素数", self._min_px)
        sform.addRow("图像最大总像素数", self._max_px)
        # 按钮：取消 / 重置 / 应用
        apply_btn = QPushButton("应用")
        reset_btn = QPushButton("重置")
        cancel_btn = QPushButton("取消")
        apply_btn.clicked.connect(self._on_apply)
        reset_btn.clicked.connect(self.reset_to_defaults)
        cancel_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(apply_btn)
        # 组装
        layout = QVBoxLayout(self)
        layout.addWidget(aux_group)
        layout.addWidget(model_group)
        layout.addWidget(sample_group)
        layout.addLayout(btn_row)

    # —— 读取 ——
    def get_config_patch(self) -> dict:
        """收集当前表单值 → 只含改动键的完整 paddle_vl 补丁"""
        pv = {}
        ignore = [label for label, _, _ in _AUX_ITEMS
                  if not self._aux_checks[label].isChecked()]
        pv["markdown_ignore_labels"] = ignore
        for key, chk in self._model_switches.items():
            pv[key] = chk.isChecked()
        # 引擎兼容：use_layout_detection 与既有 block_spotting 等价，双键并存
        pv["block_spotting"] = pv["use_layout_detection"]
        pv["repetition_penalty"] = self._rep_spin.value()
        pv["spotting_min_pixels"] = self._min_px.value()
        pv["spotting_max_pixels"] = self._max_px.value()
        return {"ocr": {"paddle_vl": pv}}

    def reset_to_defaults(self):
        """恢复默认：统一复用 defaults() 字段值（消除与重置逻辑重复的死代码）"""
        d = self.defaults()
        for label, _, _ in _AUX_ITEMS:
            self._aux_checks[label].setChecked(
                label not in d["markdown_ignore_labels"])
        for key, _ in self._model_switches.items():
            self._model_switches[key].setChecked(bool(d.get(key, False)))
        self._rep_spin.setValue(d["repetition_penalty"])
        self._min_px.setValue(d["spotting_min_pixels"])
        self._max_px.setValue(d["spotting_max_pixels"])

    @staticmethod
    def defaults() -> dict:
        """paddle_vl 默认解析配置（与弹窗重置后状态一致）"""
        return {
            "markdown_ignore_labels": [label for label, _, default in _AUX_ITEMS
                                       if not default],
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_layout_detection": False,
            "block_spotting": False,
            "use_chart_recognition": True,
            "use_seal_recognition": True,
            "use_ocr_for_image_block": True,
            "merge_layout_blocks": True,
            "repetition_penalty": 1.1,
            "spotting_min_pixels": 0,
            "spotting_max_pixels": 1605632,
        }

    def _on_apply(self):
        self.apply_requested.emit(self.get_config_patch())
        self.accept()
