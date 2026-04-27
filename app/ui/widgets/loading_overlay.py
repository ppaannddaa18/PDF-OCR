"""
加载遮罩层组件
用于显示OCR引擎初始化进度和错误状态
"""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout, QPushButton
from PyQt6.QtCore import Qt, QTimer, pyqtSignal as Signal
from PyQt6.QtGui import QColor, QFont
from qfluentwidgets import ProgressRing, BodyLabel, PushButton, InfoBar, InfoBarPosition


class LoadingOverlay(QWidget):
    """启动加载遮罩层"""

    retry_requested = Signal()  # 重试请求信号

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()
        self._animation_timer = QTimer()
        self._animation_timer.timeout.connect(self._update_animation)
        self._dot_count = 0

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

        # 错误详情
        self.error_detail = BodyLabel("")
        self.error_detail.setStyleSheet("font-size: 13px; color: #333;")
        self.error_detail.setWordWrap(True)
        self.error_detail.setMaximumWidth(400)
        error_layout.addWidget(self.error_detail, alignment=Qt.AlignmentFlag.AlignCenter)

        # 解决方案提示
        self.solution_label = BodyLabel("可能的解决方案:")
        self.solution_label.setStyleSheet("font-size: 12px; color: #666;")
        error_layout.addWidget(self.solution_label, alignment=Qt.AlignmentFlag.AlignCenter)

        self.solution_list = BodyLabel("• 重新安装应用程序\n• 检查磁盘空间\n• 联系技术支持")
        self.solution_list.setStyleSheet("font-size: 12px; color: #666;")
        error_layout.addWidget(self.solution_list, alignment=Qt.AlignmentFlag.AlignCenter)

        # 按钮区域
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(12)

        self.retry_btn = PushButton("重试")
        self.retry_btn.setFixedWidth(100)
        self.retry_btn.clicked.connect(self._on_retry)
        btn_layout.addWidget(self.retry_btn)

        self.help_btn = PushButton("查看帮助")
        self.help_btn.setFixedWidth(100)
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
        """显示错误状态"""
        self._animation_timer.stop()
        self.progress_ring.setVisible(False)
        self.status_label.setVisible(False)
        self.desc_label.setVisible(False)
        self.dots_label.setVisible(False)

        # 设置错误详情
        friendly_msg = self._translate_error(error_msg)
        self.error_detail.setText(friendly_msg)

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
        """将技术错误转换为用户友好提示"""
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

    def _on_retry(self):
        """重试按钮点击"""
        self.show_loading()
        self.retry_requested.emit()

    def _on_help(self):
        """帮助按钮点击"""
        # 显示帮助信息
        InfoBar.info(
            title="帮助",
            content="请查看应用程序文档或联系技术支持获取帮助",
            duration=5000,
            parent=self.parent()
        )