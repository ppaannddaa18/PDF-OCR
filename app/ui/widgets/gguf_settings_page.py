"""
GGUF 模型设置页（Task P5）

- GgufSettingsForm(QWidget)：从旧 OcrSettingsDialog 抽取的嵌入式设置表单
  （引擎服务 / 辅助内容解析 / 模型参数 / 几何形状 / prompt / 滑块 / NMS）。
- GgufSettingsPage(QWidget)：表单 + 操作带（测试连接 | 重启引擎 | 保存并应用 |
  重置），动作通过信号交给主窗口处理；重置仅恢复表单、不自动保存。
- TOOLTIPS：全部可调参数的悬浮提示（含“调大/调小”影响与默认值），
  官方依据：PaddleOCR-VL-1.6-GGUF README（--temp 0、mmproj 像素元数据
  1003520/1605632）与 llama.cpp server 官方文档（引擎默认值）。
- check_llama_health()：测试 llama-server /health 的纯函数（可注入 getter）。
"""
import copy

from PyQt6.QtCore import Qt, pyqtSignal as Signal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QSlider, QButtonGroup, QGridLayout, QScrollArea, QFileDialog,
    QMessageBox,
)
from qfluentwidgets import (
    SwitchButton, RadioButton, PushButton, SubtitleLabel,
    BodyLabel, InfoBar, InfoBarPosition, HorizontalSeparator,
)

from app.ui.animation_manager import AnimationManager
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss
from app.utils.config_loader import get_default_config


# ── 全部可调参数悬浮提示 ──────────────────────────────────────
# 数值项格式：{描述}。调大：…；调小：…（默认：X）
# 开关项格式：{描述}。开启：…；关闭：…（默认：X）
TOOLTIPS = {
    "server_path": (
        "llama-server.exe 的路径（llama.cpp 官方 HTTP server）。"
        "指向 llama-b9969/llama-server.exe；填错或缺失会启动失败。"
        "（默认：llama-b9969/llama-server.exe）"),
    "model_path": (
        "主模型 GGUF 文件（PaddleOCR-VL-1.6-GGUF.gguf），必须与 mmproj 配套；"
        "官方从 HuggingFace / ModelScope 获取。"
        "（默认：models/PaddleOCR-VL-1.6-GGUF.gguf）"),
    "mmproj_path": (
        "视觉投影文件（mmproj GGUF），内含 clip 图像像素上限元数据；"
        "官方默认 image_max_pixels=1003520，Spotting 需 1605632。"
        "（默认：models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf）"),
    "host": (
        "服务监听地址。改为 0.0.0.0 可让局域网其他机器访问，"
        "但服务无鉴权，建议保持本机。"
        "（默认：127.0.0.1，与 llama.cpp 官方一致）"),
    "port": (
        "llama-server 服务端口，重启引擎后生效；需避开已被占用的端口。"
        "（默认：8080，与 llama.cpp 官方一致）"),
    "device": (
        "推理设备。GPU：速度快（约 2s/页，需约 6GB 显存）；"
        "CPU：零显存但慢（约 10s/页）。切换需重启程序。"
        "（默认：gpu）"),
    "n_gpu_layers": (
        "加载到 GPU 的层数。调大（999/-1 全部卸载）：更快但显存占用高；"
        "调小（0 全 CPU）：省显存但更慢。llama.cpp 官方默认 auto。"
        "CPU 模式下无效（引擎强制 0）。"
        "（默认：999）"),
    "mmproj_offload": (
        "是否把视觉投影也加载到 GPU。开启：更快、显存占用更高；"
        "关闭：省显存、更慢。llama.cpp 官方默认开启。"
        "CPU 模式下无效（引擎强制关闭）。"
        "（默认：开启）"),
    "max_tokens": (
        "单次生成的最大 token 数，超出会截断。调大：长表格/长页输出更完整，"
        "但耗时增加，实测 ≥2560 会出现重复幻觉；调小：更快、防幻觉，"
        "但可能截断字段。官方无推荐值（llama.cpp 默认 -1 不限）；"
        "实测报关单 2048 可覆盖备注合同号。"
        "（默认：2048）"),
    "temperature": (
        "采样温度，越高越随机。调大：输出更多样，但同一页多次识别可能不一致、"
        "易幻觉；调小：更稳定可复现。官方 llama.cpp 示例用 --temp 0；"
        "引擎默认 0.80。"
        "（默认：0.0）"),
    "timeout_seconds": (
        "单次 OCR 请求的超时秒数。调大：长页/慢机器不易报超时，"
        "但卡住时等待更久；调小：快速失败并触发重试。"
        "llama.cpp server 自身默认 3600。"
        "（默认：120）"),
    "aux.header": (
        "是否识别并保留页眉。开启：保留页眉内容；关闭：过滤页眉、输出更干净。"
        "官方完整流水线默认忽略页眉/页脚/脚注/旁注等标签。"
        "（默认：关闭）"),
    "aux.footer": (
        "是否识别并保留页脚。开启：保留页脚内容；关闭：过滤页脚。"
        "官方完整流水线默认忽略页脚。"
        "（默认：关闭）"),
    "aux.page_number": (
        "是否识别并保留页码。开启：输出含页码；关闭：过滤页码。"
        "（默认：开启）"),
    "aux.footnote": (
        "是否识别并保留脚注。开启：保留脚注内容；关闭：过滤脚注。"
        "（默认：关闭）"),
    "aux.margin_text": (
        "是否识别并保留旁注/侧边文本。开启：保留旁注；关闭：过滤旁注。"
        "（默认：关闭）"),
    "aux.header_image": (
        "是否识别并保留页眉图片。开启：保留页眉图片；关闭：过滤。"
        "（默认：关闭）"),
    "aux.footer_image": (
        "是否识别并保留页脚图片。开启：保留页脚图片；关闭：过滤。"
        "（默认：关闭）"),
    "model.orientation_correction": (
        "自动检测并矫正图片旋转方向。开启：歪图也能读正，但更慢；"
        "关闭：更快，歪图可能漏字。"
        "（默认：关闭）"),
    "model.distortion_correction": (
        "矫正透视扭曲和变形。开启：拍照/扫描变形图更准，但更慢；"
        "关闭：更快，变形图可能误识别。"
        "（默认：关闭）"),
    "model.layout_analysis": (
        "进行版面分析。开启：识别文档版面结构、阅读顺序更合理；"
        "关闭：跳过版面分析，更快。"
        "（默认：开启）"),
    "model.chart_recognition": (
        "识别图表和数据可视化。开启：图表内容可解析；关闭：跳过图表。"
        "（默认：开启）"),
    "model.seal_recognition": (
        "识别印章和签章。开启：印章文字可提取；关闭：跳过印章。"
        "（默认：开启）"),
    "model.image_text_recognition": (
        "识别嵌入图片中的文字。开启：图片内文字可提取；关闭：跳过。"
        "（默认：开启）"),
    "model.cross_page_table_merge": (
        "合并跨页表格。开启：跨页表格合并为一张；关闭：按页独立。"
        "（默认：开启）"),
    "model.heading_level_recognition": (
        "识别段落标题级别。开启：输出带标题层级；关闭：平铺输出。"
        "（默认：开启）"),
    "layout_geometry": (
        "版面检测框形状。auto：自动选择（官方推荐）；rectangle：矩形，"
        "最快、适合横平竖直；quadrilateral：四边形，适合倾斜/透视；"
        "polygon：多边形，最精确、适合弯曲/不规则区域。"
        "（默认：auto）"),
    "prompt_type": (
        "发送给模型的识别指令。text：OCR 全页文本；formula/table/chart/seal："
        "对应元素级识别（官方提示词 Formula Recognition: 等）；"
        "detection：Spotting 文本检测与识别，官方要求把 mmproj 的 "
        "image_max_pixels 改为 1605632。"
        "（默认：text）"),
    "repetition_penalty": (
        "重复抑制强度（映射为频率惩罚=(值-1)×2）。调大：更少重复，"
        "但可能漏字/截断；调小：更自然但易重复。llama.cpp 官方默认 1.00 即关闭。"
        "（默认：1.00）"),
    "stability": (
        "识别稳定性，映射 top_p=1-stability。调大：输出更保守确定、"
        "重复更少；调小：输出更随机多样。llama.cpp 引擎默认 top_p=0.95，"
        "默认 0 对应 top_p=1.0（关闭）。"
        "（默认：0.00）"),
    "confidence_threshold": (
        "结果可信范围阈值，低于阈值的低置信结果被过滤。调大：只保留高置信结果、"
        "可能漏字段；调小：保留更多结果。"
        "（默认：1.00）"),
    "min_pixels": (
        "送入模型的图像最小总像素数，低于则放大。调大：小字/模糊图更清晰，"
        "但显存与耗时上升；调小：更快更省显存，小字可能糊。"
        "官方 mmproj 默认 112896（14×14×28×28）。"
        "（默认：112896）"),
    "max_pixels": (
        "送入模型的图像最大总像素数，高于则缩小。调大：细节更多但更慢更占显存，"
        "且超过 mmproj 上限（1003520）会被服务端再压回；调小：更快更省显存，"
        "小字/表格易丢细节。Spotting 模式官方要求 1605632。"
        "（默认：1003520）"),
    "nms_postprocess": (
        "非极大值抑制，去除重叠检测框。开启：检测框更干净，"
        "但可能误删重叠的合法内容；关闭：保留全部框。"
        "（默认：开启）"),
    "pdf.render_dpi": (
        "PDF 页面渲染分辨率。调大：OCR 更清晰、识别更准，但更慢、更占内存，"
        "且超过 max_pixels 会被压缩，收益有限；调小：更快更省内存，小字可能糊。"
        "（默认：200）"),
    "batch.max_workers": (
        "并行处理的页数/文件数。调大：多页更快，但显存与 CPU 压力更大"
        "（llama-server 单实例仍可能排队）；调小：更稳定。"
        "（默认：4）"),
    "batch.retry_times": (
        "单页失败后的重试次数。调大：对偶发超时更稳，但整体耗时更长；"
        "调小：快速失败。"
        "（默认：2）"),
    "export.include_confidence": (
        "导出 Excel/CSV 时是否包含置信度列。开启：便于核对结果可信度；"
        "关闭：表格更简洁。"
        "（默认：开启）"),
    "animations_enabled": (
        "关闭界面折叠、滑入滑出等动画。开启（勾选=禁用）：界面变化即时生效；"
        "关闭：保留动画效果。"
        "（默认：关闭）"),
}


class ScrollSafeSlider(QSlider):
    """悬停横条时滚轮不调节滑块，避免误触；滚轮事件向上传播给滚动区"""

    def wheelEvent(self, event):
        event.ignore()


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

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
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
        title = SubtitleLabel("GGUF 模型设置")
        title.setStyleSheet("font-weight: bold; font-size: 18px;")
        title_layout.addWidget(title)
        title_layout.addStretch()
        content_layout.addLayout(title_layout)

        hint = BodyLabel(
            "GGUF 参数保存后需重启引擎生效；PDF 渲染分辨率等部分参数需重启程序；"
            "设备（GPU/CPU）切换需重启程序")
        hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')}; font-size: 12px;")
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
                           btn_server, "可执行文件 (*.exe);;所有文件 (*)",
                           TOOLTIPS["server_path"])
        self.ed_model_path, btn_model = self._make_path_edit()
        self._add_path_row(service_grid, 1, "模型文件 (GGUF)", self.ed_model_path,
                           btn_model, "GGUF 模型 (*.gguf);;所有文件 (*)",
                           TOOLTIPS["model_path"])
        self.ed_mmproj_path, btn_mmproj = self._make_path_edit()
        self._add_path_row(service_grid, 2, "视觉投影 (mmproj)", self.ed_mmproj_path,
                           btn_mmproj, "GGUF 模型 (*.gguf);;所有文件 (*)",
                           TOOLTIPS["mmproj_path"])

        self.ed_host = self._make_value_edit("127.0.0.1")
        self._add_value_row(service_grid, 3, "服务地址 (host)", self.ed_host,
                            TOOLTIPS["host"])
        self.ed_port = self._make_value_edit("8080")
        self._add_value_row(service_grid, 4, "服务端口 (port)", self.ed_port,
                            TOOLTIPS["port"])

        # 设备单选（GPU/CPU；切换需重启程序）
        device_row = QHBoxLayout()
        device_label = BodyLabel("推理设备")
        device_label.setToolTip(TOOLTIPS["device"])
        device_row.addWidget(device_label)
        device_row.addSpacing(12)
        self.bg_device = QButtonGroup(self)
        self.rb_device_gpu = RadioButton("GPU")
        self.rb_device_cpu = RadioButton("CPU")
        self.rb_device_gpu.setToolTip(TOOLTIPS["device"])
        self.rb_device_cpu.setToolTip(TOOLTIPS["device"])
        self.bg_device.addButton(self.rb_device_gpu, 0)
        self.bg_device.addButton(self.rb_device_cpu, 1)
        # CPU 模式联动：引擎强制 n_gpu_layers=0 / mmproj_offload=False，禁用对应输入
        self.rb_device_cpu.toggled.connect(self._on_device_changed)
        device_row.addWidget(self.rb_device_gpu)
        device_row.addWidget(self.rb_device_cpu)
        device_row.addStretch()
        service_grid.addLayout(device_row, 5, 0, 1, 3)

        self.ed_n_gpu_layers = self._make_value_edit("999")
        self._add_value_row(service_grid, 6, "GPU 层数 (n_gpu_layers)", self.ed_n_gpu_layers,
                            TOOLTIPS["n_gpu_layers"])
        self.ed_max_tokens = self._make_value_edit("2048")
        self._add_value_row(service_grid, 7, "最大生成 token (max_tokens)",
                            self.ed_max_tokens, TOOLTIPS["max_tokens"])
        self.ed_temperature = self._make_value_edit("0.0")
        self._add_value_row(service_grid, 8, "温度 (temperature)",
                            self.ed_temperature, TOOLTIPS["temperature"])
        self.ed_timeout = self._make_value_edit("120")
        self._add_value_row(service_grid, 9, "请求超时秒数 (timeout_seconds)",
                            self.ed_timeout, TOOLTIPS["timeout_seconds"])

        offload_row = self._create_switch(
            "mmproj 显存卸载 (mmproj_offload)", TOOLTIPS["mmproj_offload"])
        self.sw_mmproj_offload = offload_row["switch"]
        service_grid.addLayout(offload_row["layout"], 10, 0, 1, 3)

        content_layout.addLayout(service_grid)
        content_layout.addWidget(HorizontalSeparator())

        # ===== 外观设置 =====
        content_layout.addLayout(self._create_section_title("外观设置"))

        self.sw_animations = self._create_switch(
            "禁用动画", TOOLTIPS["animations_enabled"])
        # 即时生效（与 Rapid 设置对话框一致），无需等待保存
        self.sw_animations["switch"].checkedChanged.connect(
            lambda checked: AnimationManager.set_enabled(not checked))
        content_layout.addLayout(self.sw_animations["layout"])
        content_layout.addWidget(HorizontalSeparator())

        # ===== 辅助内容解析 =====
        content_layout.addLayout(self._create_section_title("辅助内容解析"))
        content_layout.addWidget(BodyLabel("模型自动识别并过滤辅助内容，开启后将恢复解析"))

        aux_grid = QGridLayout()
        aux_grid.setSpacing(12)
        aux_grid.setColumnStretch(0, 1)
        aux_grid.setColumnStretch(1, 1)

        self.sw_header = self._create_switch("页眉", TOOLTIPS["aux.header"])
        self.sw_footer = self._create_switch("页脚", TOOLTIPS["aux.footer"])
        self.sw_page_number = self._create_switch("页码", TOOLTIPS["aux.page_number"])
        self.sw_footnote = self._create_switch("脚注", TOOLTIPS["aux.footnote"])
        self.sw_margin_text = self._create_switch("旁注文本", TOOLTIPS["aux.margin_text"])
        self.sw_header_image = self._create_switch("页眉图片", TOOLTIPS["aux.header_image"])
        self.sw_footer_image = self._create_switch("页脚图片", TOOLTIPS["aux.footer_image"])

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

        self.sw_orientation = self._create_switch(
            "图片方向矫正", TOOLTIPS["model.orientation_correction"])
        self.sw_distortion = self._create_switch(
            "图片扭曲矫正", TOOLTIPS["model.distortion_correction"])
        self.sw_layout = self._create_switch(
            "版面分析", TOOLTIPS["model.layout_analysis"])
        self.sw_chart = self._create_switch(
            "图表识别", TOOLTIPS["model.chart_recognition"])
        self.sw_seal = self._create_switch(
            "印章识别", TOOLTIPS["model.seal_recognition"])
        self.sw_image_text = self._create_switch(
            "图片文字识别", TOOLTIPS["model.image_text_recognition"])
        self.sw_cross_page = self._create_switch(
            "跨页表格合并", TOOLTIPS["model.cross_page_table_merge"])
        self.sw_heading = self._create_switch(
            "段落标题级别识别", TOOLTIPS["model.heading_level_recognition"])

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
        for rb in (self.rb_geo_auto, self.rb_geo_rect,
                   self.rb_geo_quad, self.rb_geo_poly):
            rb.setToolTip(TOOLTIPS["layout_geometry"])

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
        for rb in (self.rb_prompt_text, self.rb_prompt_formula,
                   self.rb_prompt_table, self.rb_prompt_chart,
                   self.rb_prompt_seal, self.rb_prompt_detection):
            rb.setToolTip(TOOLTIPS["prompt_type"])

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
            tooltip=TOOLTIPS["repetition_penalty"]
        )
        content_layout.addLayout(self.slider_repetition["layout"])

        self.slider_stability = self._create_slider_row(
            "识别稳定性", 0.0, 1.0, 0.00, 0.01,
            tooltip=TOOLTIPS["stability"]
        )
        content_layout.addLayout(self.slider_stability["layout"])

        self.slider_confidence = self._create_slider_row(
            "结果可信范围", 0.0, 1.0, 1.0, 0.01,
            tooltip=TOOLTIPS["confidence_threshold"]
        )
        content_layout.addLayout(self.slider_confidence["layout"])

        self.slider_min_pixels = self._create_slider_row(
            "图像最小总像素数", 65536, 1048576, 112896, 256,
            tooltip=TOOLTIPS["min_pixels"]
        )
        content_layout.addLayout(self.slider_min_pixels["layout"])

        self.slider_max_pixels = self._create_slider_row(
            "图像最大总像素数", 524288, 8388608, 1003520, 256,
            tooltip=TOOLTIPS["max_pixels"]
        )
        content_layout.addLayout(self.slider_max_pixels["layout"])

        content_layout.addWidget(HorizontalSeparator())

        # ===== NMS 后处理 =====
        nms_layout = QHBoxLayout()
        nms_label = BodyLabel("NMS后处理")
        nms_label.setToolTip(TOOLTIPS["nms_postprocess"])
        self.sw_nms = SwitchButton()
        self.sw_nms.setOnText("开")
        self.sw_nms.setOffText("关")
        self.sw_nms.setToolTip(TOOLTIPS["nms_postprocess"])
        nms_layout.addWidget(nms_label)
        nms_layout.addStretch()
        nms_layout.addWidget(self.sw_nms)
        content_layout.addLayout(nms_layout)

        content_layout.addWidget(HorizontalSeparator())

        # ===== 文档与批处理 =====
        content_layout.addLayout(self._create_section_title("文档与批处理"))

        doc_grid = QGridLayout()
        doc_grid.setSpacing(10)
        doc_grid.setColumnStretch(1, 1)

        self.ed_render_dpi = self._make_value_edit("200")
        self._add_value_row(doc_grid, 0, "PDF 渲染分辨率 (render_dpi)",
                            self.ed_render_dpi, TOOLTIPS["pdf.render_dpi"])
        self.ed_max_workers = self._make_value_edit("4")
        self._add_value_row(doc_grid, 1, "并行页数 (max_workers)",
                            self.ed_max_workers, TOOLTIPS["batch.max_workers"])
        self.ed_retry_times = self._make_value_edit("2")
        self._add_value_row(doc_grid, 2, "失败重试次数 (retry_times)",
                            self.ed_retry_times, TOOLTIPS["batch.retry_times"])

        self.sw_include_confidence = self._create_switch(
            "导出含置信度 (include_confidence)", TOOLTIPS["export.include_confidence"])
        doc_grid.addLayout(self.sw_include_confidence["layout"], 3, 0, 1, 3)
        content_layout.addLayout(doc_grid)

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
        if tooltip:
            switch.setToolTip(tooltip)
        layout.addWidget(label)
        layout.addStretch()
        layout.addWidget(switch)
        return {"layout": layout, "switch": switch, "label": label}

    def _make_value_edit(self, default: str) -> QLineEdit:
        edit = QLineEdit(default)
        edit.setFixedWidth(180)
        self._apply_edit_palette(edit)
        self._theme_inputs.append(edit)
        return edit

    def _make_path_edit(self):
        edit = QLineEdit()
        edit.setPlaceholderText("路径")
        self._apply_edit_palette(edit)
        self._theme_inputs.append(edit)
        btn = PushButton("浏览…")
        btn.setFixedWidth(72)
        return edit, btn

    def _add_path_row(self, grid, row, text, line_edit, browse_btn, file_filter,
                      tooltip: str = ""):
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
            line_edit.setToolTip(tooltip)
            browse_btn.setToolTip(tooltip)
        grid.addWidget(label, row, 0)
        grid.addWidget(line_edit, row, 1)
        grid.addWidget(browse_btn, row, 2)
        browse_btn.clicked.connect(
            lambda: self._browse_file(line_edit, file_filter))

    def _add_value_row(self, grid, row, text, line_edit, tooltip: str = ""):
        label = BodyLabel(text)
        if tooltip:
            label.setToolTip(tooltip)
            line_edit.setToolTip(tooltip)
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
        self._apply_edit_palette(line_edit)

        slider = ScrollSafeSlider(Qt.Orientation.Horizontal)
        slider.setMinimum(int(min_val / step))
        slider.setMaximum(int(max_val / step))
        slider.setValue(int(default / step))
        if tooltip:
            line_edit.setToolTip(tooltip)
            slider.setToolTip(tooltip)

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
            self._apply_edit_palette(line_edit)
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

    def _apply_edit_palette(self, edit: QLineEdit):
        """QLineEdit 显式文本/占位符调色板

        纯 Qt 控件不随 qfluentwidgets 主题换色；深色设计下若不指定，
        文字保持默认深色，在深色背景上不可读（GGUF 设置页问题根因）。
        """
        from PyQt6.QtGui import QColor, QPalette
        pal = edit.palette()
        pal.setColor(QPalette.ColorRole.Text,
                     QColor(ThemeManager.get_color('text_primary')))
        pal.setColor(QPalette.ColorRole.PlaceholderText,
                     QColor(ThemeManager.get_color('text_secondary')))
        edit.setPalette(pal)

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
        self.ed_n_gpu_layers.setText(str(gguf_cfg.get("n_gpu_layers", 999)))
        self.ed_max_tokens.setText(str(gguf_cfg.get("max_tokens", 2048)))
        self.ed_temperature.setText(str(gguf_cfg.get("temperature", 0.0)))
        self.ed_timeout.setText(str(gguf_cfg.get("timeout_seconds", 120)))
        self.sw_mmproj_offload.setChecked(gguf_cfg.get("mmproj_offload", True))

        # 外观：animations_enabled（开关勾选 = 禁用动画）
        appearance = self._config.get("appearance", {})
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
        self._set_slider_value(self.slider_min_pixels, gguf_cfg.get("min_pixels", 112896))
        self._set_slider_value(self.slider_max_pixels, gguf_cfg.get("max_pixels", 1003520))

        self.sw_nms.setChecked(gguf_cfg.get("nms_postprocess", True))

        # 文档与批处理
        pdf_cfg = self._config.get("pdf", {})
        self.ed_render_dpi.setText(str(pdf_cfg.get("render_dpi", 200)))
        batch_cfg = self._config.get("batch", {})
        self.ed_max_workers.setText(str(batch_cfg.get("max_workers", 4)))
        self.ed_retry_times.setText(str(batch_cfg.get("retry_times", 2)))
        export_cfg = self._config.get("export", {})
        self.sw_include_confidence["switch"].setChecked(
            export_cfg.get("include_confidence", True))

        # CPU 联动初始状态（setChecked 同值不触发 toggled，需手动同步一次）
        self._on_device_changed(self.rb_device_cpu.isChecked())

    def _set_slider_value(self, slider_data: dict, value: float):
        step = slider_data["step"]
        slider = slider_data["slider"]
        line_edit = slider_data["line_edit"]
        val = max(slider_data["min"], min(slider_data["max"], value))
        slider.setValue(int(val / step))
        line_edit.setText(f"{val:.2f}" if step < 1 else str(int(val)))

    def _on_device_changed(self, is_cpu: bool):
        """CPU 模式联动：引擎强制 n_gpu_layers=0、mmproj_offload=False，
        禁用相关输入（灰显），避免界面值与引擎实际行为不一致"""
        self.ed_n_gpu_layers.setEnabled(not is_cpu)
        self.sw_mmproj_offload.setEnabled(not is_cpu)

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
            "n_gpu_layers": self._parse_int(self.ed_n_gpu_layers.text(), 999),
            "mmproj_offload": self.sw_mmproj_offload.isChecked(),
            "max_tokens": self._parse_int(self.ed_max_tokens.text(), 2048),
            "temperature": self._parse_float(self.ed_temperature.text(), 0.0),
            "timeout_seconds": self._parse_int(self.ed_timeout.text(), 120),
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
            "layout_geometry": ["auto", "rectangle", "quadrilateral", "polygon"][
                max(0, self.bg_geometry.checkedId())],
            "prompt_type": ["text", "formula", "table", "chart", "seal", "detection"][
                max(0, self.bg_prompt.checkedId())],
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
            "pdf": {
                "render_dpi": self._parse_int(self.ed_render_dpi.text(), 200),
            },
            "batch": {
                "max_workers": self._parse_int(self.ed_max_workers.text(), 4),
                "retry_times": self._parse_int(self.ed_retry_times.text(), 2),
            },
            "export": {
                "include_confidence": self.sw_include_confidence["switch"].isChecked(),
            },
            "appearance": {
                "animations_enabled": not self.sw_animations["switch"].isChecked(),
            },
        }
        return patch

    def _on_default(self):
        """恢复默认设置：统一从 get_default_config() 读取，不硬编码"""
        defaults = get_default_config()
        gguf = defaults["ocr"]["gguf"]

        # 引擎服务
        self.ed_server_path.setText(str(gguf.get("server_path", "")))
        self.ed_model_path.setText(str(gguf.get("model_path", "")))
        self.ed_mmproj_path.setText(str(gguf.get("mmproj_path", "")))
        self.ed_host.setText(str(gguf.get("host", "127.0.0.1")))
        self.ed_port.setText(str(gguf.get("port", 8080)))
        self.rb_device_gpu.setChecked(gguf.get("device", "gpu") == "gpu")
        self.rb_device_cpu.setChecked(gguf.get("device", "gpu") != "gpu")
        self.ed_n_gpu_layers.setText(str(gguf.get("n_gpu_layers", 999)))
        self.ed_max_tokens.setText(str(gguf.get("max_tokens", 2048)))
        self.ed_temperature.setText(str(gguf.get("temperature", 0.0)))
        self.ed_timeout.setText(str(gguf.get("timeout_seconds", 120)))
        self.sw_mmproj_offload.setChecked(gguf.get("mmproj_offload", True))

        # 辅助内容解析
        aux = gguf.get("auxiliary_parsing", {})
        self.sw_header["switch"].setChecked(aux.get("header", False))
        self.sw_footer["switch"].setChecked(aux.get("footer", False))
        self.sw_page_number["switch"].setChecked(aux.get("page_number", True))
        self.sw_footnote["switch"].setChecked(aux.get("footnote", False))
        self.sw_margin_text["switch"].setChecked(aux.get("margin_text", False))
        self.sw_header_image["switch"].setChecked(aux.get("header_image", False))
        self.sw_footer_image["switch"].setChecked(aux.get("footer_image", False))

        # 模型参数
        model = gguf.get("model_params", {})
        self.sw_orientation["switch"].setChecked(
            model.get("orientation_correction", False))
        self.sw_distortion["switch"].setChecked(
            model.get("distortion_correction", False))
        self.sw_layout["switch"].setChecked(model.get("layout_analysis", True))
        self.sw_chart["switch"].setChecked(model.get("chart_recognition", True))
        self.sw_seal["switch"].setChecked(model.get("seal_recognition", True))
        self.sw_image_text["switch"].setChecked(
            model.get("image_text_recognition", True))
        self.sw_cross_page["switch"].setChecked(
            model.get("cross_page_table_merge", True))
        self.sw_heading["switch"].setChecked(
            model.get("heading_level_recognition", True))

        # 几何 / prompt
        geo_map = {"auto": 0, "rectangle": 1, "quadrilateral": 2, "polygon": 3}
        self.bg_geometry.button(
            geo_map.get(gguf.get("layout_geometry", "auto"), 0)).setChecked(True)
        prompt_map = {
            "text": 0, "formula": 1, "table": 2,
            "chart": 3, "seal": 4, "detection": 5,
        }
        self.bg_prompt.button(
            prompt_map.get(gguf.get("prompt_type", "text"), 0)).setChecked(True)

        # 高级参数
        self._set_slider_value(self.slider_repetition,
                               gguf.get("repetition_penalty", 1.00))
        self._set_slider_value(self.slider_stability,
                               gguf.get("stability", 0.00))
        self._set_slider_value(self.slider_confidence,
                               gguf.get("confidence_threshold", 1.0))
        self._set_slider_value(self.slider_min_pixels,
                               gguf.get("min_pixels", 112896))
        self._set_slider_value(self.slider_max_pixels,
                               gguf.get("max_pixels", 1003520))
        self.sw_nms.setChecked(gguf.get("nms_postprocess", True))

        # 文档与批处理
        self.ed_render_dpi.setText(str(defaults["pdf"].get("render_dpi", 200)))
        self.ed_max_workers.setText(str(defaults["batch"].get("max_workers", 4)))
        self.ed_retry_times.setText(str(defaults["batch"].get("retry_times", 2)))
        self.sw_include_confidence["switch"].setChecked(
            defaults["export"].get("include_confidence", True))

        # 外观
        animations_enabled = defaults.get("appearance", {}).get(
            "animations_enabled", True)
        self.sw_animations["switch"].setChecked(not animations_enabled)

        InfoBar.success(
            title="已恢复默认",
            content="表单已恢复为默认值（未自动保存，请点“保存并应用”）",
            duration=2000,
            parent=self
        )


class GgufSettingsPage(QWidget):
    """GGUF 模型设置页：GgufSettingsForm + 操作带（测试连接/重启引擎/保存并应用）"""

    save_requested = Signal(dict)          # patch
    restart_requested = Signal(dict)       # patch
    test_connection_requested = Signal(str, int)  # (host, port) 表单当前值

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.form = GgufSettingsForm(config, self)

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

        self.btn_test = PushButton("测试连接")
        self.btn_test.setFixedWidth(110)
        self.btn_test.clicked.connect(self._on_test_clicked)
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

        self.btn_reset = PushButton("重置")
        self.btn_reset.setFixedWidth(80)
        self.btn_reset.clicked.connect(self._on_reset_clicked)
        bar_layout.addWidget(self.btn_reset)

        layout.addWidget(bar)

    def get_config_patch(self) -> dict:
        return self.form.get_config_patch()

    def _on_test_clicked(self):
        """测试连接：携带表单当前 host/port（未保存时也应测试编辑中的值）"""
        self.test_connection_requested.emit(
            self.form.ed_host.text().strip() or "127.0.0.1",
            GgufSettingsForm._parse_int(self.form.ed_port.text(), 8080))

    def _confirm_reset(self) -> bool:
        """重置确认框：重置仅恢复表单，不自动保存"""
        ret = QMessageBox.question(
            self,
            "重置确认",
            "将恢复为默认值且不会自动保存，是否继续？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        return ret == QMessageBox.StandardButton.Yes

    def _on_reset_clicked(self):
        if self._confirm_reset():
            self.form._on_default()
