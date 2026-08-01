"""引擎状态发光横线 — 窗口顶部 2px 渐变带（P2 骨架）

set_status('initializing' | 'ready' | 'error') → 琥珀 / 冰青 / 红。
paintEvent 绘制两端淡出的横向线性渐变模拟发光；
P6 在此叠加呼吸动画（本任务只做静态色 + set_status 接口 + 最小高 2px）。
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QColor, QLinearGradient, QPainter
from PyQt6.QtWidgets import QSizePolicy, QWidget


class EngineStatusBand(QWidget):
    """引擎初始化状态带：窗口顶部 2px 发光横线"""

    # 三态颜色（与 GGUF 签名一致：琥珀=初始化 / 冰青=就绪 / 红=错误）
    STATUS_COLORS = {
        'initializing': '#F59E0B',
        'ready': '#5EEAD4',
        'error': '#F87171',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._status = 'initializing'
        self.setMinimumHeight(2)
        self.setMaximumHeight(2)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        # 纯装饰条，不拦截鼠标事件
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents, True)

    def set_status(self, status: str) -> None:
        """设置状态；未知状态抛 ValueError，重复设置 no-op"""
        if status not in self.STATUS_COLORS:
            raise ValueError(f"Unknown engine status: {status}")
        if status == self._status:
            return
        self._status = status
        self.update()

    def status(self) -> str:
        """当前状态"""
        return self._status

    def paintEvent(self, event):
        """绘制两端淡出的横向渐变（发光感）"""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        color = QColor(self.STATUS_COLORS[self._status])
        fade = 0.15  # 两端淡出比例，模拟发光渐隐
        gradient = QLinearGradient(0, 0, self.width(), 0)
        edge = QColor(color)
        edge.setAlpha(0)
        gradient.setColorAt(0.0, edge)
        gradient.setColorAt(fade, color)
        gradient.setColorAt(1.0 - fade, color)
        gradient.setColorAt(1.0, edge)
        painter.fillRect(self.rect(), gradient)
