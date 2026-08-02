"""引擎状态发光横线 — 窗口顶部 2px 渐变带（P2 骨架 + P6 呼吸动画 + 重设计）

set_status('initializing' | 'ready' | 'error') → 黄铜 / 鼠尾草绿 / 信号红。
paintEvent 绘制两端淡出的横向线性渐变模拟发光；
P6：initializing 态叠加黄铜呼吸（alpha 100↔220，QTimer 驱动相位），
尊重 AnimationManager 全局动画开关（禁用时静态常亮）。
"""
import math

from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget

from app.ui.animation_manager import AnimationManager


class EngineStatusBand(QWidget):
    """引擎初始化状态带：窗口顶部 2px 发光横线"""

    # 三态颜色（与 GGUF 签名一致：黄铜=初始化 / 鼠尾草绿=就绪 / 信号红=错误）
    STATUS_COLORS = {
        'initializing': '#E0B23C',  # 黄铜（呼吸）
        'ready': '#8FB573',         # 鼠尾草绿
        'error': '#E2574C',         # 信号红
    }

    BREATH_INTERVAL_MS = 80

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = 'initializing'
        self._phase = 0.0  # 呼吸相位 0..1
        self.setMinimumHeight(2)
        self.setMaximumHeight(2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 纯装饰条，不拦截鼠标事件
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)
        self._breath_timer = QTimer(self)
        self._breath_timer.setInterval(self.BREATH_INTERVAL_MS)
        self._breath_timer.timeout.connect(self._on_breath_tick)
        self._update_breath_timer()

    def set_status(self, status: str) -> None:
        """设置状态；未知状态抛 ValueError，重复设置 no-op"""
        if status not in self.STATUS_COLORS:
            raise ValueError(f"Unknown engine status: {status}")
        if status == self._status:
            return
        self._status = status
        self._update_breath_timer()
        self.update()

    def status(self) -> str:
        """当前状态"""
        return self._status

    def _update_breath_timer(self):
        """initializing + 动画启用 → 呼吸；否则停止"""
        breathing = (
            self._status == 'initializing' and AnimationManager.is_enabled())
        if breathing and not self._breath_timer.isActive():
            self._phase = 0.0
            self._breath_timer.start()
        elif not breathing and self._breath_timer.isActive():
            self._breath_timer.stop()

    def _on_breath_tick(self):
        """推进呼吸相位（每 tick 重绘）"""
        if not AnimationManager.is_enabled():
            self._breath_timer.stop()
            self._phase = 0.0
            self.update()
            return
        self._phase = (self._phase + 0.08) % 1.0
        self.update()

    def paintEvent(self, event):
        """绘制两端淡出的横向渐变（发光感）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.STATUS_COLORS[self._status])
        if self._status == 'initializing' and AnimationManager.is_enabled():
            # 琥珀呼吸：alpha 100 ↔ 220
            wave = 0.5 + 0.5 * math.sin(self._phase * 2.0 * math.pi)
            color.setAlpha(int(100 + 120 * wave))
        fade = 0.15  # 两端淡出比例，模拟发光渐隐
        gradient = QLinearGradient(0, 0, self.width(), 0)
        edge = QColor(color)
        edge.setAlpha(0)
        gradient.setColorAt(0.0, edge)
        gradient.setColorAt(fade, color)
        gradient.setColorAt(1.0 - fade, color)
        gradient.setColorAt(1.0, edge)
        painter.fillRect(self.rect(), gradient)

    def hideEvent(self, event):
        """隐藏时停止呼吸定时器"""
        self._breath_timer.stop()
        super().hideEvent(event)

    def closeEvent(self, event):
        """关闭时停止呼吸定时器"""
        self._breath_timer.stop()
        super().closeEvent(event)
