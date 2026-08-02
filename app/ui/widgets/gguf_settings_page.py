"""
GGUF 模型设置页（Task P5）

- GgufSettingsForm(QWidget)：从旧 OcrSettingsDialog 抽取的嵌入式设置表单
  （引擎服务 / 辅助内容解析 / 模型参数 / 几何形状 / prompt / 滑块 / NMS）。
  主题三单选仅 show_theme_options=True 时创建（旧对话框兼容；GGUF 页传
  False——GGUF 锁定深色）。
- GgufSettingsPage(QWidget)：表单 + 操作带（恢复默认 | 测试连接 | 重启引擎 |
  保存并应用），三个动作通过信号交给主窗口处理。
- check_llama_health()：测试 llama-server /health 的纯函数（可注入 getter）。
"""
import copy

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSlider, QButtonGroup, QGridLayout, QScrollArea, QFileDialog,
)
from qfluentwidgets import (
    SwitchButton, RadioButton, PushButton, SubtitleLabel,
    BodyLabel, InfoBar, InfoBarPosition, HorizontalSeparator,
)

from app.ui.animation_manager import AnimationManager
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss


def check_llama_health(host: str, port: int, timeout: float = 5.0, getter=None):
    """测试 llama-server /health 连通性，返回 (ok, message)

    getter 可注入（默认 requests.get），便于测试。
    """
    import requests  # requirements-gpu.txt；基础环境缺失时走 ImportError 分支
    getter = getter or requests.get
    try:
        resp = getter(f"http://{host}:{port}/health", timeout=timeout)
        if resp.status_code == 200:
            return True, f"llama-server 正常响应（{host}:{port}）"
        return False, f"服务响应异常: HTTP {resp.status_code}"
    except ImportError:
        return False, "缺少 requests 依赖（见 requirements-gpu.txt）"
    except Exception as e:
        return False, f"无法连接 {host}:{port} - {e}"


class GgufSettingsForm(QWidget):
    """GGUF 引擎参数设置表单（可嵌入页面或对话框）"""

    settings_applied = Signal(dict)

    # 主题模式（仅 show_theme_options=True 时启用）
    THEME_OPTIONS = ['light', 'dark', 'auto']
    THEME_LABELS = ['浅色', '深色', '跟随系统']

    def __init__(self, config: dict, parent=None, show_theme_options: bool = True):
        super().__init__(parent)
        self._show_theme_options = show_theme_options
        self._original_config = copy.deepcopy(config)
        self._config = copy.deepcopy(config)
        self._init_ui()
        self._load_settings()
        # 主题切换后由 ThemeManager 触发重建本表单内嵌 QSS
        ThemeManager.register_refresh_callback(self._apply_theme_styles)

    # ── UI 构建 ────────────────────────────────────────────────

    def _init_ui(self):
        """初始化 UI"""
        self.setMinimumSize(560, 600)

        # 主题化输入/滑块（Task 15：主题切换时重建 QSS）
        self._theme_inputs = []   # QLineEdit（数值/路径输入框）
        self._theme_sliders = []  # QSlider（滑块）

        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 滚动区域（容纳大量设置项）
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setStyleSheet("QScrollArea { border: none; background: transparent; }")

        content_widget = QWidget()
        content_layout = QVBoxLayout(content_widget)
        content_layout.setSpacing(16)
        content_layout.setContentsMargins(24, 24, 24, 24)

        # 标题
        title_layout = QHBoxLayout()
        title = SubtitleLabel("GGUF 模型设置")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        content_layout.addLayout(title_layout)

        hint = BodyLabel("参数保存后需重启引擎生效；设备（GPU/CPU）切换需重启程序")
        hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')}; font-size: 12px;")
        content_layout.addWidget(hint)
        self._hint_label = hint

        content_layout.addWidget(HorizontalSeparator())

        # ===== 引擎服务 =====
        content_layout.addLayout(self._create_section_title("引擎服务"))
        service_grid = QGridLayout()
        service_grid.setSpacing(10)
        service_grid.setColumnStretch(1, 1)

        self.ed_server_path, btn_server = self._make_path_edit()
        self._add_path_row(service_grid, 0, "llama-server 路径", self.ed_server_path,
                           btn_server, "可执行文件 (*.exe);;所有文件 (*)")
        self.ed_model_path, btn_model = self._make_path_edit()
        self._add_path_row(service_grid, 1, "模型文件 (GGUF)", self.ed_model_path,
                           btn_model, "GGUF 模型 (*.gguf);;所有文件 (*)")
        self.ed_mmproj_path, btn_mmproj = self._make_path_edit()
        self._add_path_row(service_grid, 2, "视觉投影 (mmproj)", self.ed_mmproj_path,
                           btn_mmproj, "GGUF 模型 (*.gguf);;所有文件 (*)")

        self.ed_host = self._make_value_edit("127.0.0.1")
        self._add_value_row(service_grid, 3, "服务地址 (host)", self.ed_host)
        self.ed_port = self._make_value_edit("8080")
        self._add_value_row(service_grid, 4, "服务端口 (port)", self.ed_port)

        # 设备单选（GPU/CPU；切换需重启程序）
        device_row = QHBoxLayout()
        device_label = BodyLabel("推理设备")
        device_label.setToolTip("GPU 速度快（约2s/页，需约6GB显存）；CPU 0显存但慢（约10s/页）")
        device_row.addWidget(device_label)
        device_row.addSpacing(12)
        self.bg_device = QButtonGroup(self)
        self.rb_device_gpu = RadioButton("GPU")
        self.rb_device_cpu = RadioButton("CPU")
        self.bg_device.addButton(self.rb_device_gpu, 0)
        self.bg_device.addButton(self.rb_device_cpu, 1)
        device_row.addWidget(self.rb_device_gpu)
        device_row.addWidget(self.rb_device_cpu)
        device_row.addStretch()
        service_grid.addLayout(device_row, 5, 0, 1, 3)

        self.ed_n_gpu_layers = self._make_value_edit("99")
        self._add_value_row(service_grid, 6, "GPU 层数 (n_gpu_layers)", self.ed_n_gpu_layers,
                            "加载到 GPU 的层数；-1 全部、0 全部 CPU")
        self.ed_max_tokens = self._make_value_edit("512")
        self._add_value_row(service_grid, 7, "最大生成 token (max_tokens)", self.ed_max_tokens)
        self.ed_temperature = self._make_value_edit("0.0")
        self._add_value_row(service_grid, 8, "温度 (temperature)", self.ed_temperature)
        self.ed_idle_unload = self._make_value_edit("300")
        self._add_value_row(service_grid, 9, "空闲卸载秒数 (idle_unload_seconds)",
                            self.ed_idle_unload, "引擎空闲超过该秒数后自动卸载（当前预留）")

        offload_row = self._create_switch(
            "mmproj 显存卸载 (mmproj_offload)", "将视觉投影也加载到 GPU，减少显存占用")
        self.sw_mmproj_offload = offload_row["switch"]
        service_grid.addLayout(offload_row["layout"], 10, 0, 1, 3)

        content_layout.addLayout(service_grid)
        content_layout.addWidget(HorizontalSeparator())

        # ===== 外观设置 =====
        content_layout.addLayout(self._create_section_title("外观设置"))

        if self._show_theme_options:
            theme_layout = QHBoxLayout()
            theme_layout.setSpacing(16)
            self.bg_theme = QButtonGroup(self)
            self.rb_theme_light = RadioButton(self.THEME_LABELS[0])
            self.rb_theme_dark = RadioButton(self.THEME_LABELS[1])
            self.rb_theme_auto = RadioButton(self.THEME_LABELS[2])
            self.bg_theme.addButton(self.rb_theme_light, 0)
            self.bg_theme.addButton(self.rb_theme_dark, 1)
            self.bg_theme.addButton(self.rb_theme_auto, 2)
            theme_layout.addWidget(self.rb_theme_light)
            theme_layout.addWidget(self.rb_theme_dark)
            theme_layout.addWidget(self.rb_theme_auto)
            theme_layout.addStretch()
            content_layout.addLayout(theme_layout)

            self.rb_theme_light.toggled.connect(
                lambda checked: checked and self._on_theme_changed('light'))
            self.rb_theme_dark.toggled.connect(
                lambda checked: checked and self._on_theme_changed('dark'))
            self.rb_theme_auto.toggled.connect(
                lambda checked: checked and self._on_theme_changed('auto'))

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

        self.slider_repetition = self._create_slider_row(
            "重复抑制强度", 0.0, 2.0, 1.00, 0.01,
            tooltip="抑制重复内容的强度，值越大重复越少"
        )
        content_layout.addLayout(self.slider_repetition["layout"])

        self.slider_stability = self._create_slider_row(
            "识别稳定性", 0.0, 1.0, 0.00, 0.01,
            tooltip="提高稳定性可减少随机性，但可能降低创造力"
        )
        content_layout.addLayout(self.slider_stability["layout"])

        self.slider_confidence = self._create_slider_row(
            "结果可信范围", 0.0, 1.0, 1.0, 0.01,
            tooltip="过滤低置信度结果的阈值"
        )
        content_layout.addLayout(self.slider_confidence["layout"])

        self.slider_min_pixels = self._create_slider_row(
            "图像最小总像素数", 65536, 1048576, 147384, 1024,
            tooltip="输入图像的最小像素数，低于此值将放大"
        )
        content_layout.addLayout(self.slider_min_pixels["layout"])

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

        # 构造时烘焙全部内嵌样式
        self._apply_theme_styles()

    # ── 小部件工厂 ─────────────────────────────────────────────

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
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(switch)
        return {"layout": layout, "switch": switch, "label": label}

    def _make_value_edit(self, default: str) -> QLineEdit:
        edit = QLineEdit(default)
        edit.setFixedWidth(180)
        self._theme_inputs.append(edit)
        return edit

    def _make_path_edit(self):
        edit = QLineEdit()
        edit.setPlaceholderText("路径")
        self._theme_inputs.append(edit)
        btn = PushButton("浏览…")
        btn.setFixedWidth(72)
        return edit, btn

    def _add_path_row(self, grid, row, text, line_edit, browse_btn, file_filter):
        label = BodyLabel(text)
        grid.addWidget(label, row, 0)
        grid.addWidget(line_edit, row, 1)
        grid.addWidget(browse_btn, row, 2)
        browse_btn.clicked.connect(
            lambda: self._browse_file(line_edit, file_filter))

    def _add_value_row(self, grid, row, text, line_edit, tooltip: str = ""):
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
        grid.addWidget(label, row, 0)
        grid.addWidget(line_edit, row, 1, 1, 2)

    def _browse_file(self, line_edit: QLineEdit, file_filter: str):
        path, _ = QFileDialog.getOpenFileName(self, "选择文件", "", file_filter)
        if path:
            line_edit.setText(path)

    def _create_slider_row(self, text: str, min_val: float, max_val: float,
                           default: float, step: float, tooltip: str = "") -> dict:
        layout = QVBoxLayout()
        layout.setSpacing(4)

        label_layout = QHBoxLayout()
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
        label_layout.addWidget(label)
        label_layout.addStretch()
        layout.addLayout(label_layout)

        input_layout = QHBoxLayout()
        input_layout.setSpacing(8)

        line_edit = QLineEdit()
        line_edit.setFixedWidth(80)
        line_edit.setAlignment(Qt.AlignmentFlag.AlignCenter)

        slider = QSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(int(min_val / step))
        slider.setMaximum(int(max_val / step))
        slider.setValue(int(default / step))

        self._theme_inputs.append(line_edit)
        self._theme_sliders.append(slider)
        self._apply_theme_styles()

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
            "step": step,
        }

    # ── 主题 ───────────────────────────────────────────────────

    def _on_theme_changed(self, theme: str):
        from qfluentwidgets import Theme as FluentTheme
        from qfluentwidgets import setTheme as setFluentTheme
        setFluentTheme({
            'light': FluentTheme.LIGHT,
            'dark': FluentTheme.DARK,
            'auto': FluentTheme.AUTO,
        }[theme])
        effective = ThemeManager.resolve_theme(theme)
        ThemeManager.set_theme(effective)

    def _apply_theme_styles(self):
        hint = getattr(self, '_hint_label', None)
        if hint is not None:
            hint.setStyleSheet(
                f"color: {ThemeManager.get_color('text_disabled')}; font-size: 12px;")
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
                }}
            """)
        for slider in self._theme_sliders:
            slider.setStyleSheet(f"""
                QSlider::groove:horizontal {{
                    height: 6px;
                    background: {border};
                    border-radius: 3px;
                }}
                QSlider::sub-page:horizontal {{
                    background: {primary};
                    border-radius: 3px;
                }}
                QSlider::handle:horizontal {{
                    width: 16px;
                    height: 16px;
                    background: {bg};
                    border: 2px solid {primary};
                    border-radius: 8px;
                    margin: -5px 0;
                }}
            """)

    # ── 配置加载/读取 ──────────────────────────────────────────

    def _load_settings(self):
        gguf_cfg = self._config.get("ocr", {}).get("gguf", {})

        # 引擎服务
        self.ed_server_path.setText(str(gguf_cfg.get("server_path", "")))
        self.ed_model_path.setText(str(gguf_cfg.get("model_path", "")))
        self.ed_mmproj_path.setText(str(gguf_cfg.get("mmproj_path", "")))
        self.ed_host.setText(str(gguf_cfg.get("host", "127.0.0.1")))
        self.ed_port.setText(str(gguf_cfg.get("port", 8080)))
        device = gguf_cfg.get("device", "gpu")
        self.rb_device_gpu.setChecked(device == "gpu")
        self.rb_device_cpu.setChecked(device != "gpu")
        self.ed_n_gpu_layers.setText(str(gguf_cfg.get("n_gpu_layers", 99)))
        self.ed_max_tokens.setText(str(gguf_cfg.get("max_tokens", 512)))
        self.ed_temperature.setText(str(gguf_cfg.get("temperature", 0.0)))
        self.ed_idle_unload.setText(str(gguf_cfg.get("idle_unload_seconds", 300)))
        self.sw_mmproj_offload.setChecked(gguf_cfg.get("mmproj_offload", False))

        # 外观：animations_enabled（开关勾选 = 禁用动画）
        appearance = self._config.get("appearance", {})
        if self._show_theme_options:
            theme = appearance.get("theme", "auto")
            for rb in (self.rb_theme_light, self.rb_theme_dark, self.rb_theme_auto):
                rb.blockSignals(True)
            try:
                self.bg_theme.button(self.THEME_OPTIONS.index(theme)).setChecked(True)
            except ValueError:
                self.bg_theme.button(2).setChecked(True)
            finally:
                for rb in (self.rb_theme_light, self.rb_theme_dark, self.rb_theme_auto):
                    rb.blockSignals(False)
        self.sw_animations["switch"].setChecked(
            not appearance.get("animations_enabled", True))

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

        geometry = gguf_cfg.get("layout_geometry", "auto")
        geo_map = {"auto": 0, "rectangle": 1, "quadrilateral": 2, "polygon": 3}
        self.bg_geometry.button(geo_map.get(geometry, 0)).setChecked(True)

        prompt = gguf_cfg.get("prompt_type", "text")
        prompt_map = {
            "text": 0, "formula": 1, "table": 2,
            "chart": 3, "seal": 4, "detection": 5,
        }
        self.bg_prompt.button(prompt_map.get(prompt, 0)).setChecked(True)

        self._set_slider_value(self.slider_repetition, gguf_cfg.get("repetition_penalty", 1.00))
        self._set_slider_value(self.slider_stability, gguf_cfg.get("stability", 0.00))
        self._set_slider_value(self.slider_confidence, gguf_cfg.get("confidence_threshold", 1.0))
        self._set_slider_value(self.slider_min_pixels, gguf_cfg.get("min_pixels", 147384))
        self._set_slider_value(self.slider_max_pixels, gguf_cfg.get("max_pixels", 2822400))

        self.sw_nms.setChecked(gguf_cfg.get("nms_postprocess", True))

    def _set_slider_value(self, slider_data: dict, value: float):
        step = slider_data["step"]
        slider = slider_data["slider"]
        line_edit = slider_data["line_edit"]
        val = max(slider_data["min"], min(slider_data["max"], value))
        slider.setValue(int(val / step))
        line_edit.setText(f"{val:.2f}" if step < 1 else str(int(val)))

    def _get_slider_value(self, slider_data: dict) -> float:
        return slider_data["slider"].value() * slider_data["step"]

    @staticmethod
    def _parse_int(text: str, default: int) -> int:
        try:
            return int(text)
        except ValueError:
            return default

    @staticmethod
    def _parse_float(text: str, default: float) -> float:
        try:
            return float(text)
        except ValueError:
            return default

    def _get_settings(self) -> dict:
        settings = {
            # 引擎服务
            "server_path": self.ed_server_path.text().strip(),
            "model_path": self.ed_model_path.text().strip(),
            "mmproj_path": self.ed_mmproj_path.text().strip(),
            "host": self.ed_host.text().strip() or "127.0.0.1",
            "port": self._parse_int(self.ed_port.text(), 8080),
            "device": "gpu" if self.rb_device_gpu.isChecked() else "cpu",
            "n_gpu_layers": self._parse_int(self.ed_n_gpu_layers.text(), 99),
            "mmproj_offload": self.sw_mmproj_offload.isChecked(),
            "max_tokens": self._parse_int(self.ed_max_tokens.text(), 512),
            "temperature": self._parse_float(self.ed_temperature.text(), 0.0),
            "idle_unload_seconds": self._parse_int(self.ed_idle_unload.text(), 300),
            # 辅助内容解析
            "auxiliary_parsing": {
                "header": self.sw_header["switch"].isChecked(),
                "footer": self.sw_footer["switch"].isChecked(),
                "page_number": self.sw_page_number["switch"].isChecked(),
                "footnote": self.sw_footnote["switch"].isChecked(),
                "margin_text": self.sw_margin_text["switch"].isChecked(),
                "header_image": self.sw_header_image["switch"].isChecked(),
                "footer_image": self.sw_footer_image["switch"].isChecked(),
            },
            # 模型参数
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

    def get_config_patch(self) -> dict:
        """获取配置补丁（用于合并到主配置）"""
        patch = {
            "ocr": {"gguf": self._get_settings()},
            "appearance": {
                "animations_enabled": not self.sw_animations["switch"].isChecked(),
            },
        }
        if self._show_theme_options:
            patch["appearance"]["theme"] = self.THEME_OPTIONS[self.bg_theme.checkedId()]
        return patch

    def _on_default(self):
        """恢复默认设置"""
        # 引擎服务默认
        self.ed_server_path.clear()
        self.ed_model_path.clear()
        self.ed_mmproj_path.clear()
        self.ed_host.setText("127.0.0.1")
        self.ed_port.setText("8080")
        self.rb_device_gpu.setChecked(True)
        self.ed_n_gpu_layers.setText("99")
        self.ed_max_tokens.setText("512")
        self.ed_temperature.setText("0.0")
        self.ed_idle_unload.setText("300")
        self.sw_mmproj_offload.setChecked(False)

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

        self.rb_geo_auto.setChecked(True)
        self.rb_prompt_text.setChecked(True)

        self._set_slider_value(self.slider_repetition, 1.00)
        self._set_slider_value(self.slider_stability, 0.00)
        self._set_slider_value(self.slider_confidence, 1.0)
        self._set_slider_value(self.slider_min_pixels, 147384)
        self._set_slider_value(self.slider_max_pixels, 2822400)

        self.sw_nms.setChecked(True)

        if self._show_theme_options:
            self.bg_theme.button(2).setChecked(True)
        self.sw_animations["switch"].setChecked(False)

        InfoBar.success(
            title="已恢复默认",
            content="所有设置已恢复为默认值",
            duration=2000,
            parent=self
        )

    def apply_animations(self):
        """应用动画开关（开关勾选 = 禁用动画）"""
        AnimationManager.set_enabled(not self.sw_animations["switch"].isChecked())


class GgufSettingsPage(QWidget):
    """GGUF 模型设置页：GgufSettingsForm + 操作带（测试连接/重启引擎/保存并应用）"""

    save_requested = Signal(dict)          # patch
    restart_requested = Signal(dict)       # patch
    test_connection_requested = Signal()

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.form = GgufSettingsForm(config, self, show_theme_options=False)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(self.form, 1)

        # 操作带
        bar = QWidget()
        bar_layout = QHBoxLayout(bar)
        bar_layout.setContentsMargins(24, 8, 24, 12)
        bar_layout.setSpacing(12)

        self.btn_default = PushButton("恢复默认")
        self.btn_default.setFixedWidth(100)
        self.btn_default.clicked.connect(self.form._on_default)
        bar_layout.addWidget(self.btn_default)

        bar_layout.addStretch()

        self.btn_test = PushButton("测试连接")
        self.btn_test.setFixedWidth(110)
        self.btn_test.clicked.connect(self.test_connection_requested.emit)
        bar_layout.addWidget(self.btn_test)

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

        layout.addWidget(bar)

    def get_config_patch(self) -> dict:
        return self.form.get_config_patch()
