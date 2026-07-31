"""
OCR 引擎设置对话框
类似 PaddleOCR-VL 1.6 官网的解析配置界面
"""
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSlider, QFrame, QButtonGroup, QWidget, QGridLayout,
    QScrollArea, QSizePolicy
)
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtGui import QFont
from qfluentwidgets import (
    SwitchButton, RadioButton, PushButton, SubtitleLabel,
    BodyLabel, InfoBar, InfoBarPosition, HorizontalSeparator
)
import copy

from app.ui.animation_manager import AnimationManager


class OcrSettingsDialog(QDialog):
    """OCR 引擎设置对话框"""

    # 信号：设置已应用
    settings_applied = Signal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self._original_config = copy.deepcopy(config)
        self._config = copy.deepcopy(config)
        self._init_ui()
        self._load_settings()

    def _init_ui(self):
        """初始化 UI"""
        self.setWindowTitle("PaddleOCR-VL-1.6 解析配置")
        self.setMinimumSize(600, 700)
        self.resize(650, 750)
        self.setModal(True)

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域（容纳大量设置项）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        # 内容容器
        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title_layout = QHBoxLayout()
        title = SubtitleLabel("PaddleOCR-VL-1.6 解析配置")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        content_layout.addLayout(title_layout)

        # 提示文本
        hint = BodyLabel("设置变化将自动同步到当前 API")
        hint.setStyleSheet("color: #999; font-size: 12px;")
        content_layout.addWidget(hint)

        content_layout.addWidget(HorizontalSeparator())

        # ===== 外观设置 =====
        content_layout.addLayout(self._create_section_title("外观设置"))
        self.sw_animations = self._create_switch(
            "禁用动画",
            tooltip="关闭折叠、滑入滑出等界面动画，界面变化即时生效（尊重系统动画偏好）"
        )
        content_layout.addLayout(self.sw_animations["layout"])
        content_layout.addWidget(HorizontalSeparator())

        # ===== 辅助内容解析 =====
        content_layout.addLayout(self._create_section_title("辅助内容解析"))
        content_layout.addWidget(BodyLabel("模型自动识别并过滤辅助内容，开启后将恢复解析"))

        aux_grid = QGridLayout()
        aux_grid.setSpacing(12)
        aux_grid.setColumnStretch(0, 1)
        aux_grid.setColumnStretch(1, 1)

        self.sw_header = self._create_switch("页眉")
        self.sw_footer = self._create_switch("页脚")
        self.sw_page_number = self._create_switch("页码")
        self.sw_footnote = self._create_switch("脚注")
        self.sw_margin_text = self._create_switch("旁注文本")
        self.sw_header_image = self._create_switch("页眉图片")
        self.sw_footer_image = self._create_switch("页脚图片")

        aux_grid.addLayout(self.sw_header["layout"], 0, 0)
        aux_grid.addLayout(self.sw_header_image["layout"], 0, 1)
        aux_grid.addLayout(self.sw_footer["layout"], 1, 0)
        aux_grid.addLayout(self.sw_footer_image["layout"], 1, 1)
        aux_grid.addLayout(self.sw_page_number["layout"], 2, 0)
        aux_grid.addLayout(self.sw_footnote["layout"], 2, 1)
        aux_grid.addLayout(self.sw_margin_text["layout"], 3, 0)

        content_layout.addLayout(aux_grid)
        content_layout.addWidget(HorizontalSeparator())

        # ===== 模型参数设置 =====
        content_layout.addLayout(self._create_section_title("模型参数设置"))

        model_grid = QGridLayout()
        model_grid.setSpacing(12)
        model_grid.setColumnStretch(0, 1)
        model_grid.setColumnStretch(1, 1)

        self.sw_orientation = self._create_switch("图片方向矫正", tooltip="自动检测并矫正图片旋转角度")
        self.sw_distortion = self._create_switch("图片扭曲矫正", tooltip="矫正透视扭曲和变形")
        self.sw_layout = self._create_switch("版面分析", tooltip="识别文档版面结构")
        self.sw_chart = self._create_switch("图表识别", tooltip="识别图表和数据可视化")
        self.sw_seal = self._create_switch("印章识别", tooltip="识别印章和签章")
        self.sw_image_text = self._create_switch("图片文字识别", tooltip="识别嵌入图片中的文字")
        self.sw_cross_page = self._create_switch("跨页表格合并", tooltip="合并跨页的表格")
        self.sw_heading = self._create_switch("段落标题级别识别", tooltip="识别标题层级结构")

        model_grid.addLayout(self.sw_orientation["layout"], 0, 0)
        model_grid.addLayout(self.sw_distortion["layout"], 0, 1)
        model_grid.addLayout(self.sw_layout["layout"], 1, 0)
        model_grid.addLayout(self.sw_chart["layout"], 1, 1)
        model_grid.addLayout(self.sw_seal["layout"], 2, 0)
        model_grid.addLayout(self.sw_image_text["layout"], 2, 1)
        model_grid.addLayout(self.sw_cross_page["layout"], 3, 0)
        model_grid.addLayout(self.sw_heading["layout"], 3, 1)

        content_layout.addLayout(model_grid)
        content_layout.addWidget(HorizontalSeparator())

        # ===== 版面检测结果几何形状 =====
        content_layout.addLayout(self._create_section_title("版面检测结果的几何形状"))

        geo_layout = QHBoxLayout()
        geo_layout.setSpacing(16)

        self.bg_geometry = QButtonGroup(self)
        self.rb_geo_auto = RadioButton("自动")
        self.rb_geo_rect = RadioButton("矩形")
        self.rb_geo_quad = RadioButton("四边形")
        self.rb_geo_poly = RadioButton("多边形")

        self.bg_geometry.addButton(self.rb_geo_auto, 0)
        self.bg_geometry.addButton(self.rb_geo_rect, 1)
        self.bg_geometry.addButton(self.rb_geo_quad, 2)
        self.bg_geometry.addButton(self.rb_geo_poly, 3)

        geo_layout.addWidget(self.rb_geo_auto)
        geo_layout.addWidget(self.rb_geo_rect)
        geo_layout.addWidget(self.rb_geo_quad)
        geo_layout.addWidget(self.rb_geo_poly)
        geo_layout.addStretch()

        content_layout.addLayout(geo_layout)
        content_layout.addWidget(HorizontalSeparator())

        # ===== prompt 类型设置 =====
        content_layout.addLayout(self._create_section_title("prompt 类型设置"))

        prompt_layout = QHBoxLayout()
        prompt_layout.setSpacing(12)

        self.bg_prompt = QButtonGroup(self)
        self.rb_prompt_text = RadioButton("文本")
        self.rb_prompt_formula = RadioButton("公式")
        self.rb_prompt_table = RadioButton("表格")
        self.rb_prompt_chart = RadioButton("图表")
        self.rb_prompt_seal = RadioButton("印章")
        self.rb_prompt_detection = RadioButton("文本检测与识别")

        self.bg_prompt.addButton(self.rb_prompt_text, 0)
        self.bg_prompt.addButton(self.rb_prompt_formula, 1)
        self.bg_prompt.addButton(self.rb_prompt_table, 2)
        self.bg_prompt.addButton(self.rb_prompt_chart, 3)
        self.bg_prompt.addButton(self.rb_prompt_seal, 4)
        self.bg_prompt.addButton(self.rb_prompt_detection, 5)

        prompt_layout.addWidget(self.rb_prompt_text)
        prompt_layout.addWidget(self.rb_prompt_formula)
        prompt_layout.addWidget(self.rb_prompt_table)
        prompt_layout.addWidget(self.rb_prompt_chart)
        prompt_layout.addWidget(self.rb_prompt_seal)
        prompt_layout.addWidget(self.rb_prompt_detection)
        prompt_layout.addStretch()

        content_layout.addLayout(prompt_layout)
        content_layout.addWidget(HorizontalSeparator())

        # ===== 滑块参数 =====
        content_layout.addLayout(self._create_section_title("高级参数"))

        # 重复抑制强度
        self.slider_repetition = self._create_slider_row(
            "重复抑制强度", 0.0, 2.0, 1.00, 0.01,
            tooltip="抑制重复内容的强度，值越大重复越少"
        )
        content_layout.addLayout(self.slider_repetition["layout"])

        # 识别稳定性
        self.slider_stability = self._create_slider_row(
            "识别稳定性", 0.0, 1.0, 0.00, 0.01,
            tooltip="提高稳定性可减少随机性，但可能降低创造力"
        )
        content_layout.addLayout(self.slider_stability["layout"])

        # 结果可信范围
        self.slider_confidence = self._create_slider_row(
            "结果可信范围", 0.0, 1.0, 1.0, 0.01,
            tooltip="过滤低置信度结果的阈值"
        )
        content_layout.addLayout(self.slider_confidence["layout"])

        # 图像最小总像素数
        self.slider_min_pixels = self._create_slider_row(
            "图像最小总像素数", 65536, 1048576, 147384, 1024,
            tooltip="输入图像的最小像素数，低于此值将放大"
        )
        content_layout.addLayout(self.slider_min_pixels["layout"])

        # 图像最大总像素数
        self.slider_max_pixels = self._create_slider_row(
            "图像最大总像素数", 524288, 8388608, 2822400, 1024,
            tooltip="输入图像的最大像素数，高于此值将缩小"
        )
        content_layout.addLayout(self.slider_max_pixels["layout"])

        content_layout.addWidget(HorizontalSeparator())

        # ===== NMS 后处理 =====
        nms_layout = QHBoxLayout()
        nms_label = BodyLabel("NMS后处理")
        nms_label.setToolTip("非极大值抑制后处理，去除重叠检测框")
        self.sw_nms = SwitchButton()
        self.sw_nms.setOnText("开")
        self.sw_nms.setOffText("关")
        nms_layout.addWidget(nms_label)
        nms_layout.addStretch()
        nms_layout.addWidget(self.sw_nms)
        content_layout.addLayout(nms_layout)

        content_layout.addStretch()

        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

        # ===== 底部按钮 =====
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)
        btn_layout.setContentsMargins(24, 12, 24, 24)

        self.btn_default = PushButton("恢复默认")
        self.btn_default.setFixedWidth(100)
        self.btn_default.clicked.connect(self._on_default)
        btn_layout.addWidget(self.btn_default)

        btn_layout.addStretch()

        self.btn_apply = PushButton("应用并重启")
        self.btn_apply.setFixedWidth(120)
        self.btn_apply.setStyleSheet("""
            PushButton {
                background-color: #4a90d9;
                color: white;
                font-weight: bold;
            }
            PushButton:hover {
                background-color: #3a7bc8;
            }
        """)
        self.btn_apply.clicked.connect(self._on_apply)
        btn_layout.addWidget(self.btn_apply)

        self.btn_cancel = PushButton("取消")
        self.btn_cancel.setFixedWidth(80)
        self.btn_cancel.clicked.connect(self.reject)
        btn_layout.addWidget(self.btn_cancel)

        main_layout.addLayout(btn_layout)

    def _create_section_title(self, text: str) -> QHBoxLayout:
        """创建区域标题"""
        layout = QHBoxLayout()
        label = SubtitleLabel(text)
        label.setStyleSheet("font-weight: bold; font-size: 15px; margin-top: 8px;")
        layout.addWidget(label)
        layout.addStretch()
        return layout

    def _create_switch(self, text: str, tooltip: str = "") -> dict:
        """创建开关行组件"""
        layout = QHBoxLayout()
        layout.setSpacing(8)

        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)

        switch = SwitchButton()
        switch.setOnText("开")
        switch.setOffText("关")

        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(switch)

        return {"layout": layout, "switch": switch, "label": label}

    def _create_slider_row(self, text: str, min_val: float, max_val: float,
                           default: float, step: float, tooltip: str = "") -> dict:
        """创建滑块行组件（标签 + 数值输入 + 滑块）"""
        layout = QVBoxLayout()
        layout.setSpacing(4)

        # 标签行
        label_layout = QHBoxLayout()
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
        label_layout.addWidget(label)
        label_layout.addStretch()
        layout.addLayout(label_layout)

        # 输入 + 滑块行
        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        # 数值输入框
        line_edit = QLineEdit()
        line_edit.setFixedWidth(80)
        line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)
        line_edit.setStyleSheet("""
            QLineEdit {
                border: 1px solid #ddd;
                border-radius: 4px;
                padding: 4px 8px;
                background: white;
            }
        """)

        # 滑块
        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(int(min_val / step))
        slider.setMaximum(int(max_val / step))
        slider.setValue(int(default / step))
        slider.setStyleSheet("""
            QSlider::groove:horizontal {
                height: 6px;
                background: #e0e0e0;
                border-radius: 3px;
            }
            QSlider::sub-page:horizontal {
                background: #4a90d9;
                border-radius: 3px;
            }
            QSlider::handle:horizontal {
                width: 16px;
                height: 16px;
                background: white;
                border: 2px solid #4a90d9;
                border-radius: 8px;
                margin: -5px 0;
            }
        """)

        # 同步数值和滑块
        def update_from_slider():
            val = slider.value() * step
            line_edit.setText(f"{val:.2f}" if step < 1 else str(int(val)))

        def update_from_edit():
            try:
                val = float(line_edit.text())
                val = max(min_val, min(max_val, val))
                slider.setValue(int(val / step))
            except ValueError:
                pass

        slider.valueChanged.connect(update_from_slider)
        line_edit.editingFinished.connect(update_from_edit)

        # 初始化显示
        update_from_slider()

        input_layout.addWidget(line_edit)
        input_layout.addWidget(slider, 1)

        layout.addLayout(input_layout)

        return {
            "layout": layout,
            "slider": slider,
            "line_edit": line_edit,
            "min": min_val,
            "max": max_val,
            "step": step
        }

    def _load_settings(self):
        """从配置加载设置"""
        gguf_cfg = self._config.get("ocr", {}).get("gguf", {})

        # 外观设置：appearance.animations_enabled（缺省启用）
        appearance = self._config.get("appearance", {})
        self.sw_animations["switch"].setChecked(
            not appearance.get("animations_enabled", True)
        )

        # 辅助内容解析
        aux = gguf_cfg.get("auxiliary_parsing", {})
        self.sw_header["switch"].setChecked(aux.get("header", False))
        self.sw_footer["switch"].setChecked(aux.get("footer", False))
        self.sw_page_number["switch"].setChecked(aux.get("page_number", True))
        self.sw_footnote["switch"].setChecked(aux.get("footnote", False))
        self.sw_margin_text["switch"].setChecked(aux.get("margin_text", False))
        self.sw_header_image["switch"].setChecked(aux.get("header_image", False))
        self.sw_footer_image["switch"].setChecked(aux.get("footer_image", False))

        # 模型参数
        model = gguf_cfg.get("model_params", {})
        self.sw_orientation["switch"].setChecked(model.get("orientation_correction", False))
        self.sw_distortion["switch"].setChecked(model.get("distortion_correction", False))
        self.sw_layout["switch"].setChecked(model.get("layout_analysis", True))
        self.sw_chart["switch"].setChecked(model.get("chart_recognition", True))
        self.sw_seal["switch"].setChecked(model.get("seal_recognition", True))
        self.sw_image_text["switch"].setChecked(model.get("image_text_recognition", True))
        self.sw_cross_page["switch"].setChecked(model.get("cross_page_table_merge", True))
        self.sw_heading["switch"].setChecked(model.get("heading_level_recognition", True))

        # 几何形状
        geometry = gguf_cfg.get("layout_geometry", "auto")
        geo_map = {"auto": 0, "rectangle": 1, "quadrilateral": 2, "polygon": 3}
        idx = geo_map.get(geometry, 0)
        self.bg_geometry.button(idx).setChecked(True)

        # prompt 类型
        prompt = gguf_cfg.get("prompt_type", "text")
        prompt_map = {
            "text": 0, "formula": 1, "table": 2,
            "chart": 3, "seal": 4, "detection": 5
        }
        idx = prompt_map.get(prompt, 0)
        self.bg_prompt.button(idx).setChecked(True)

        # 滑块参数
        self._set_slider_value(self.slider_repetition, gguf_cfg.get("repetition_penalty", 1.00))
        self._set_slider_value(self.slider_stability, gguf_cfg.get("stability", 0.00))
        self._set_slider_value(self.slider_confidence, gguf_cfg.get("confidence_threshold", 1.0))
        self._set_slider_value(self.slider_min_pixels, gguf_cfg.get("min_pixels", 147384))
        self._set_slider_value(self.slider_max_pixels, gguf_cfg.get("max_pixels", 2822400))

        # NMS
        self.sw_nms.setChecked(gguf_cfg.get("nms_postprocess", True))

    def _set_slider_value(self, slider_data: dict, value: float):
        """设置滑块数值"""
        step = slider_data["step"]
        slider = slider_data["slider"]
        line_edit = slider_data["line_edit"]

        val = max(slider_data["min"], min(slider_data["max"], value))
        slider.setValue(int(val / step))
        line_edit.setText(f"{val:.2f}" if step < 1 else str(int(val)))

    def _get_slider_value(self, slider_data: dict) -> float:
        """获取滑块数值"""
        return slider_data["slider"].value() * slider_data["step"]

    def _get_settings(self) -> dict:
        """获取当前设置"""
        settings = {
            "auxiliary_parsing": {
                "header": self.sw_header["switch"].isChecked(),
                "footer": self.sw_footer["switch"].isChecked(),
                "page_number": self.sw_page_number["switch"].isChecked(),
                "footnote": self.sw_footnote["switch"].isChecked(),
                "margin_text": self.sw_margin_text["switch"].isChecked(),
                "header_image": self.sw_header_image["switch"].isChecked(),
                "footer_image": self.sw_footer_image["switch"].isChecked(),
            },
            "model_params": {
                "orientation_correction": self.sw_orientation["switch"].isChecked(),
                "distortion_correction": self.sw_distortion["switch"].isChecked(),
                "layout_analysis": self.sw_layout["switch"].isChecked(),
                "chart_recognition": self.sw_chart["switch"].isChecked(),
                "seal_recognition": self.sw_seal["switch"].isChecked(),
                "image_text_recognition": self.sw_image_text["switch"].isChecked(),
                "cross_page_table_merge": self.sw_cross_page["switch"].isChecked(),
                "heading_level_recognition": self.sw_heading["switch"].isChecked(),
            },
            "layout_geometry": ["auto", "rectangle", "quadrilateral", "polygon"][self.bg_geometry.checkedId()],
            "prompt_type": ["text", "formula", "table", "chart", "seal", "detection"][self.bg_prompt.checkedId()],
            "repetition_penalty": self._get_slider_value(self.slider_repetition),
            "stability": self._get_slider_value(self.slider_stability),
            "confidence_threshold": self._get_slider_value(self.slider_confidence),
            "min_pixels": int(self._get_slider_value(self.slider_min_pixels)),
            "max_pixels": int(self._get_slider_value(self.slider_max_pixels)),
            "nms_postprocess": self.sw_nms.isChecked(),
        }
        return settings

    def _on_default(self):
        """恢复默认设置"""
        # 辅助内容解析默认
        self.sw_header["switch"].setChecked(False)
        self.sw_footer["switch"].setChecked(False)
        self.sw_page_number["switch"].setChecked(True)
        self.sw_footnote["switch"].setChecked(False)
        self.sw_margin_text["switch"].setChecked(False)
        self.sw_header_image["switch"].setChecked(False)
        self.sw_footer_image["switch"].setChecked(False)

        # 模型参数默认
        self.sw_orientation["switch"].setChecked(False)
        self.sw_distortion["switch"].setChecked(False)
        self.sw_layout["switch"].setChecked(True)
        self.sw_chart["switch"].setChecked(True)
        self.sw_seal["switch"].setChecked(True)
        self.sw_image_text["switch"].setChecked(True)
        self.sw_cross_page["switch"].setChecked(True)
        self.sw_heading["switch"].setChecked(True)

        # 几何形状默认
        self.rb_geo_auto.setChecked(True)

        # prompt 默认
        self.rb_prompt_text.setChecked(True)

        # 滑块默认
        self._set_slider_value(self.slider_repetition, 1.00)
        self._set_slider_value(self.slider_stability, 0.00)
        self._set_slider_value(self.slider_confidence, 1.0)
        self._set_slider_value(self.slider_min_pixels, 147384)
        self._set_slider_value(self.slider_max_pixels, 2822400)

        # NMS 默认
        self.sw_nms.setChecked(True)

        # 外观默认：动画启用
        self.sw_animations["switch"].setChecked(False)

        InfoBar.success(
            title="已恢复默认",
            content="所有设置已恢复为默认值",
            duration=2000,
            parent=self
        )

    def _on_apply(self):
        """应用设置"""
        settings = self._get_settings()
        self.settings_applied.emit(settings)
        # 应用动画开关：appearance.animations_enabled（开关勾选 = 禁用动画）
        AnimationManager.set_enabled(not self.sw_animations["switch"].isChecked())
        self.accept()

    def get_config_patch(self) -> dict:
        """获取配置补丁（用于合并到主配置）"""
        return {
            "ocr": {"gguf": self._get_settings()},
            "appearance": {"animations_enabled": not self.sw_animations["switch"].isChecked()},
        }
