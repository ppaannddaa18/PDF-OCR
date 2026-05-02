"""
加载遮罩层组件
用于显示OCR引擎初始化进度和错误状态
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton, QCheckBox, QApplication
from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QFont, QDesktopServices
from qfluentwidgets import ProgressRing, BodyLabel, PushButton, InfoBar, InfoBarPosition, CheckBox
from pathlib import Path
import platform
import sys
import json
from datetime import datetime


class LoadingOverlay(QWidget):
    """启动加载遮罩层"""

    retry_requested = Signal()  # 重试请求信号
    use_cpu_mode_requested = Signal()  # 使用CPU模式请求信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._update_animation)
        self._dot_count = 0
        self._current_error_key = None  # 当前错误类型关键字

    def _init_ui(self):
        """初始化UI"""
        # 设置遮罩层样式
        self.setStyleSheet("""
            QWidget {
                background-color: rgba(255, 255, 255, 240);
            }
        """)

        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(16)

        # 进度环
        self.progress_ring = ProgressRing()
        self.progress_ring.setFixedSize(48, 48)
        self.progress_ring.setStrokeWidth(4)
        layout.addWidget(self.progress_ring, alignment=Qt.AlignmentFlag.AlignCenter)

        # 状态文本
        self.status_label = BodyLabel("正在初始化 OCR 引擎...")
        self.status_label.setStyleSheet("font-size: 14px; color: #333;")
        layout.addWidget(self.status_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 描述文本
        self.desc_label = BodyLabel("首次启动需要几秒钟")
        self.desc_label.setStyleSheet("font-size: 12px; color: #666;")
        layout.addWidget(self.desc_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 动画点
        self.dots_label = QLabel("●○○○○")
        self.dots_label.setStyleSheet("font-size: 16px; color: #0078d4;")
        self.dots_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.dots_label, alignment=Qt.AlignmentFlag.AlignCenter)

        # 错误面板（初始隐藏）
        self.error_widget = QWidget()
        self.error_widget.setVisible(False)
        error_layout = QVBoxLayout(self.error_widget)
        error_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        error_layout.setSpacing(12)

        # 错误图标和标题
        self.error_title = BodyLabel("⚠️ OCR引擎初始化失败")
        self.error_title.setStyleSheet("font-size: 16px; color: #d83b01; font-weight: bold;")
        error_layout.addWidget(self.error_title, alignment=Qt.AlignmentFlag.AlignCenter)

        # 错误详情（友好描述）
        self.error_detail = BodyLabel("")
        self.error_detail.setStyleSheet("font-size: 14px; color: #333; font-weight: bold;")
        self.error_detail.setWordWrap(True)
        self.error_detail.setMaximumWidth(450)
        error_layout.addWidget(self.error_detail, alignment=Qt.AlignmentFlag.AlignCenter)

        # 解决步骤区域
        self.solution_widget = QWidget()
        solution_layout = QVBoxLayout(self.solution_widget)
        solution_layout.setContentsMargins(16, 8, 16, 8)
        solution_layout.setSpacing(8)

        self.solution_title = BodyLabel("解决步骤:")
        self.solution_title.setStyleSheet("font-size: 13px; color: #666; font-weight: bold;")
        solution_layout.addWidget(self.solution_title)

        self.solution_steps = BodyLabel("")
        self.solution_steps.setStyleSheet("font-size: 12px; color: #444; line-height: 1.6;")
        self.solution_steps.setWordWrap(True)
        self.solution_steps.setMaximumWidth(420)
        solution_layout.addWidget(self.solution_steps)

        # 一键下载按钮区域
        self.download_btn_widget = QWidget()
        download_layout = QHBoxLayout(self.download_btn_widget)
        download_layout.setContentsMargins(0, 4, 0, 4)
        self.download_btn = PushButton("一键下载运行库")
        self.download_btn.setFixedWidth(140)
        self.download_btn.clicked.connect(self._on_download_runtime)
        download_layout.addStretch()
        download_layout.addWidget(self.download_btn)
        download_layout.addStretch()
        solution_layout.addWidget(self.download_btn_widget)
        self.download_btn_widget.setVisible(False)

        error_layout.addWidget(self.solution_widget)

        # 高级选项区域
        self.advanced_widget = QWidget()
        advanced_layout = QVBoxLayout(self.advanced_widget)
        advanced_layout.setContentsMargins(16, 8, 16, 8)

        # CPU模式选项
        self.cpu_mode_checkbox = CheckBox("使用CPU模式运行 (较慢但更稳定)")
        self.cpu_mode_checkbox.setChecked(False)
        advanced_layout.addWidget(self.cpu_mode_checkbox)

        error_layout.addWidget(self.advanced_widget)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.export_diag_btn = PushButton("导出诊断信息")
        self.export_diag_btn.setFixedWidth(120)
        self.export_diag_btn.clicked.connect(self._on_export_diagnostics)
        btn_layout.addWidget(self.export_diag_btn)

        self.retry_btn = PushButton("重试")
        self.retry_btn.setFixedWidth(80)
        self.retry_btn.clicked.connect(self._on_retry)
        btn_layout.addWidget(self.retry_btn)

        self.help_btn = PushButton("帮助")
        self.help_btn.setFixedWidth(80)
        self.help_btn.clicked.connect(self._on_help)
        btn_layout.addWidget(self.help_btn)

        error_layout.addLayout(btn_layout)
        layout.addWidget(self.error_widget, alignment=Qt.AlignmentFlag.AlignCenter)

    def show_loading(self):
        """显示加载状态"""
        self.error_widget.setVisible(False)
        self.progress_ring.setVisible(True)
        self.status_label.setVisible(True)
        self.desc_label.setVisible(True)
        self.dots_label.setVisible(True)
        self._animation_timer.start(300)

    def show_error(self, error_msg: str):
        """显示错误状态 - 增强版，提供具体解决步骤"""
        self._animation_timer.stop()
        self.progress_ring.setVisible(False)
        self.status_label.setVisible(False)
        self.desc_label.setVisible(False)
        self.dots_label.setVisible(False)

        # 解析错误并获取友好提示和解决步骤
        friendly_msg, solution_steps, download_url, error_key = self._translate_error_enhanced(error_msg)
        self._current_error_key = error_key

        # 设置错误详情
        self.error_detail.setText(friendly_msg)

        # 设置解决步骤
        self.solution_steps.setText(solution_steps)

        # 显示/隐藏下载按钮
        if download_url:
            self.download_btn_widget.setVisible(True)
            self._download_url = download_url
        else:
            self.download_btn_widget.setVisible(False)
            self._download_url = None

        self.error_widget.setVisible(True)

    def hide_overlay(self):
        """隐藏遮罩层"""
        self._animation_timer.stop()
        self.setVisible(False)

    def closeEvent(self, event):
        """[修复] 组件关闭时停止定时器"""
        self._animation_timer.stop()
        super().closeEvent(event)

    def __del__(self):
        """[修复] 析构时确保定时器停止"""
        try:
            if hasattr(self, '_animation_timer'):
                self._animation_timer.stop()
        except:
            pass

    def _update_animation(self):
        """更新动画点"""
        self._dot_count = (self._dot_count + 1) % 5
        dots = "●" * (self._dot_count + 1) + "○" * (4 - self._dot_count)
        self.dots_label.setText(dots)

    def _translate_error(self, error_msg: str) -> str:
        """将技术错误转换为用户友好提示 - 保留兼容性"""
        error_map = {
            "Model file not found": "未找到OCR模型文件",
            "model not found": "未找到OCR模型文件",
            "Out of memory": "内存不足",
            "memory": "内存不足",
            "ONNX runtime error": "OCR运行环境异常",
            "onnx": "OCR运行环境异常",
            "CUDA": "GPU加速初始化失败",
            "GPU": "GPU加速初始化失败",
        }

        for key, friendly in error_map.items():
            if key.lower() in error_msg.lower():
                return f"错误原因: {friendly}"

        return f"错误原因: {error_msg}"

    def _translate_error_enhanced(self, error_msg: str) -> tuple:
        """
        增强版错误翻译，返回 (友好描述, 解决步骤, 下载链接, 错误关键字)
        """
        # 错误类型映射表：关键字 -> (友好描述, 解决步骤, 下载链接)
        # 注意：更具体的错误应该放在前面，避免被通用错误匹配
        error_solutions = {
            # GPU/CUDA 相关错误（优先匹配）
            "cuda out of memory": (
                "GPU显存不足",
                "1. 勾选下方「使用CPU模式运行」\n2. 关闭其他占用GPU的程序\n3. 降低批量处理文件数量",
                None
            ),
            "cuda": (
                "GPU加速初始化失败",
                "1. 勾选下方「使用CPU模式运行」\n2. 更新显卡驱动\n3. 检查CUDA是否正确安装",
                None
            ),
            "gpu": (
                "GPU加速初始化失败",
                "1. 勾选下方「使用CPU模式运行」\n2. 更新显卡驱动\n3. 检查CUDA是否正确安装",
                None
            ),
            # 模型文件错误
            "model file not found": (
                "未找到OCR模型文件",
                "1. 重新安装应用程序\n2. 检查安装目录是否完整\n3. 联系技术支持获取模型文件",
                None
            ),
            "model not found": (
                "未找到OCR模型文件",
                "1. 重新安装应用程序\n2. 检查安装目录是否完整\n3. 联系技术支持获取模型文件",
                None
            ),
            # 运行时错误
            "onnx runtime error": (
                "OCR运行环境异常",
                "1. 下载并安装 Visual C++ 运行库\n2. 重启应用程序",
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            ),
            "onnx": (
                "OCR运行环境异常",
                "1. 下载并安装 Visual C++ 运行库\n2. 重启应用程序",
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            ),
            "dll load failed": (
                "动态库加载失败",
                "1. 下载并安装 Visual C++ 运行库\n2. 重启计算机后重试",
                "https://aka.ms/vs/17/release/vc_redist.x64.exe"
            ),
            # 内存错误（放在 GPU 错误之后）
            "out of memory": (
                "系统内存不足",
                "1. 关闭其他应用程序后重试\n2. 降低批量处理文件数量\n3. 在配置文件中设置 use_gpu: false",
                None
            ),
            "memory": (
                "系统内存不足",
                "1. 关闭其他应用程序后重试\n2. 降低批量处理文件数量\n3. 在配置文件中设置 use_gpu: false",
                None
            ),
            # 权限错误
            "permission denied": (
                "权限不足",
                "1. 以管理员身份运行应用程序\n2. 检查安装目录权限\n3. 关闭杀毒软件后重试",
                None
            ),
        }

        error_lower = error_msg.lower()

        for key, (friendly, steps, url) in error_solutions.items():
            if key in error_lower:
                return friendly, steps, url, key

        # 默认处理
        return (
            f"初始化遇到问题",
            f"1. 重启应用程序\n2. 重新安装应用程序\n3. 联系技术支持\n\n详细信息: {error_msg}",
            None,
            "unknown"
        )

    def _on_retry(self):
        """重试按钮点击 - 支持CPU模式切换"""
        # 检查是否选择了CPU模式
        if self.cpu_mode_checkbox.isChecked():
            self.show_loading()
            self.use_cpu_mode_requested.emit()
        else:
            self.show_loading()
            self.retry_requested.emit()

    def _on_download_runtime(self):
        """一键下载运行库"""
        if hasattr(self, '_download_url') and self._download_url:
            from PyQt6.QtCore import QUrl
            QDesktopServices.openUrl(QUrl(self._download_url))
            InfoBar.success(
                title="下载已开始",
                content="请在浏览器中完成下载并安装，然后重启应用程序",
                duration=5000,
                parent=self.parent()
            )

    def _on_export_diagnostics(self):
        """导出诊断信息"""
        try:
            # 收集诊断信息
            diagnostics = {
                "timestamp": datetime.now().isoformat(),
                "platform": platform.platform(),
                "python_version": sys.version,
                "architecture": platform.architecture()[0],
                "error_type": self._current_error_key or "unknown",
                "app_version": "1.0.0",
            }

            # 保存到桌面
            desktop_path = Path.home() / "Desktop"
            if not desktop_path.exists():
                desktop_path = Path.home()

            diag_file = desktop_path / f"pdfocr_diagnostics_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"

            with open(diag_file, 'w', encoding='utf-8') as f:
                json.dump(diagnostics, f, indent=2, ensure_ascii=False)

            InfoBar.success(
                title="诊断信息已导出",
                content=f"文件保存至: {diag_file.name}",
                duration=5000,
                parent=self.parent()
            )
        except Exception as e:
            InfoBar.error(
                title="导出失败",
                content=str(e),
                duration=3000,
                parent=self.parent()
            )

    def _on_help(self):
        """帮助按钮点击"""
        # 显示帮助信息
        InfoBar.info(
            title="帮助",
            content="请查看应用程序文档或联系技术支持获取帮助",
            duration=5000,
            parent=self.parent()
        )

    def should_use_cpu_mode(self) -> bool:
        """返回用户是否选择了CPU模式"""
        return self.cpu_mode_checkbox.isChecked()