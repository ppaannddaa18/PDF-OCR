"""
GPU状态指示器 — 紧凑形态：彩色圆点 + 引擎缩写

Task 6 集成到 CompactToolbar：
- 保留原有核心逻辑：set_engine 绑定引擎、_refresh 状态轮询、
  GGUF 引擎的就绪显示与空闲卸载检查、5 秒定时刷新
- 视觉压缩为「彩色圆点 + 缩写」并嵌入 CompactToolbar.engine_status
- 新增 status_changed 信号，作为状态来源供外部（如状态栏）桥接
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer, pyqtSignal
from qfluentwidgets import BodyLabel

from app.ui.theme_manager import ThemeManager


class GpuStatusWidget(QWidget):
    """GPU/引擎状态指示器（紧凑版：彩色圆点 + 缩写）"""

    # 状态变化信号：(engine_name, status)
    # status 取值与 CompactToolbar.set_engine_status 词汇一致：
    #   'ready' | 'initializing' | 'unavailable' | 'cpu_mode'
    status_changed = pyqtSignal(str, str)

    # 引擎名缩写映射（彩色圆点 + 缩写）
    ENGINE_ABBR = {
        "gguf": "GGUF",
        "rapidocr": "RapidOCR",
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(4)

        self.status_icon = QLabel("●")
        self._set_dot_color(ThemeManager.get_color('text_disabled'))
        layout.addWidget(self.status_icon)

        self.status_label = BodyLabel("未初始化")
        self.status_label.setMaximumWidth(90)
        layout.addWidget(self.status_label)

        # 定时刷新（每5秒更新显存）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._refresh)
        self._engine = None

    def set_engine(self, engine):
        """绑定引擎实例"""
        self._engine = engine
        self._refresh()
        if engine and engine.engine_name == "gguf":
            self._timer.start(5000)
        else:
            self._timer.stop()

    def set_engine_status(self, engine: str, status: str):
        """外部直接设置状态（CompactToolbar.set_engine_status 委托到此）

        Args:
            engine: 引擎显示名，如 'GGUF'、'RapidOCR'
            status: 'ready', 'initializing', 'unavailable', 'cpu_mode'
        """
        status_colors = {
            'ready': ThemeManager.get_color('success'),
            'initializing': ThemeManager.get_color('warning'),
            'unavailable': ThemeManager.get_color('error'),
            'cpu_mode': ThemeManager.get_color('text_disabled'),
        }
        color = status_colors.get(status, ThemeManager.get_color('text_disabled'))
        self._set_dot_color(color)
        self.status_label.setText(engine)
        self.setToolTip(f'{engine}: {status}')
        # 与 _refresh 各分支一致，外部设置路径同样发射状态信号
        self.status_changed.emit(engine, status)

    def _set_dot_color(self, color: str):
        self.status_icon.setStyleSheet(f"font-size: 10px; color: {color};")

    def _refresh(self):
        if self._engine is None:
            self._set_dot_color(ThemeManager.get_color('text_disabled'))
            self.status_label.setText("未初始化")
            self.setToolTip("引擎未初始化")
            self.status_changed.emit("", "unavailable")
            return

        if not self._engine.is_ready:
            self._set_dot_color(ThemeManager.get_color('warning'))
            # 显示具体引擎缩写，避免用户误以为卡死
            engine_label = self.ENGINE_ABBR.get(self._engine.engine_name, "引擎")
            self.status_label.setText(f"{engine_label} 加载中...")
            self.setToolTip(f"{engine_label} 加载中...")
            self.status_changed.emit(self._engine.engine_name, "initializing")
            return

        engine_name = self._engine.engine_name
        if engine_name == "gguf":
            # GGUF 引擎不直接提供显存信息，显示就绪状态
            self._set_dot_color(ThemeManager.get_color('success'))
            self.status_label.setText("GGUF")
            self.setToolTip("GPU: GGUF (就绪)")
            self.status_changed.emit(engine_name, "ready")
            # Wire up idle unload check
            try:
                if hasattr(self._engine, '_check_idle_unload'):
                    self._engine._check_idle_unload()
            except Exception:
                pass
        else:
            self._set_dot_color(ThemeManager.get_color('success'))
            self.status_label.setText("RapidOCR")
            self.setToolTip("CPU: RapidOCR (就绪)")
            self.status_changed.emit(engine_name, "cpu_mode")

    def cleanup(self):
        """停止定时器"""
        self._timer.stop()

    def hideEvent(self, event):
        """隐藏时停止定时器"""
        self._timer.stop()
        super().hideEvent(event)

    def showEvent(self, event):
        """显示时重启定时器"""
        super().showEvent(event)
        if self._engine and self._engine.engine_name == "gguf":
            self._timer.start(5000)
