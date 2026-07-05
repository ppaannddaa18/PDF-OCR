"""
GPU状态指示器 — 显示显存使用和引擎状态
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer
from qfluentwidgets import BodyLabel


class GpuStatusWidget(QWidget):
    """GPU/引擎状态指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.status_icon)

        self.status_label = BodyLabel("引擎未初始化")
        layout.addWidget(self.status_label)

        # 定时刷新（每5秒更新显存）
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._engine = None

    def set_engine(self, engine):
        """绑定引擎实例"""
        self._engine = engine
        self._refresh()
        if engine and engine.engine_name == "paddleocr_vl":
            self._timer.start(5000)
        else:
            self._timer.stop()

    def _refresh(self):
        if self._engine is None:
            self.status_icon.setStyleSheet("font-size: 10px; color: #888;")
            self.status_label.setText("引擎未初始化")
            return

        if not self._engine.is_ready:
            self.status_icon.setStyleSheet("font-size: 10px; color: #d83b01;")
            self.status_label.setText("引擎加载中...")
            return

        if self._engine.engine_name == "paddleocr_vl":
            try:
                used, total = self._engine.get_vram_usage()
                if used > 0:
                    self.status_icon.setStyleSheet("font-size: 10px; color: #107c10;")
                    self.status_label.setText(
                        f"GPU: PaddleOCR-VL | VRAM {used:.1f}/{total:.1f} GB"
                    )
                else:
                    self.status_icon.setStyleSheet("font-size: 10px; color: #0078d4;")
                    self.status_label.setText("GPU: PaddleOCR-VL (就绪)")
            except Exception:
                self.status_icon.setStyleSheet("font-size: 10px; color: #0078d4;")
                self.status_label.setText("GPU: PaddleOCR-VL (就绪)")
        else:
            self.status_icon.setStyleSheet("font-size: 10px; color: #666;")
            self.status_label.setText("CPU: RapidOCR (就绪)")

    def cleanup(self):
        """停止定时器"""
        self._timer.stop()
