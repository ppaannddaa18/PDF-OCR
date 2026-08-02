"""
引擎选择对话框 - 启动时在 GGUF / RapidOCR 之间强制选择（Task P1）

两张引擎卡片按各自设计语言的色板自绘（视觉预演）；对话框整体保留
系统主题跟随（appearance.theme 的 light/dark/auto 仅此处生效，用 default 设计）。

交互约束（硬性）：
- 无默认选中；「进入」按钮默认禁用，选中卡片后才可用
- 单选卡片高亮描边；双击卡片 = 选择并确认
- Esc / 关闭按钮 / X = 退出程序（choose_engine 侧处理 QApplication.quit()）
- 依赖缺失时仍允许选择，确认时弹一次 InfoBar.warning
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)
from qfluentwidgets import InfoBar, InfoBarPosition, PrimaryPushButton

# GGUF 设计语言色板（重设计：暗松绿 × 黄铜金）
GGUF_COLORS = {
    "bg": "#10150F",
    "panel": "#171E16",
    "accent": "#C9A227",
    "teal": "#8FB573",
    "text": "#E9E7D9",
    "muted": "#A5AC97",
}
# RapidOCR 设计语言色板（重设计：暖纸 × 档案绿）
RAPID_COLORS = {
    "bg": "#F6F3ED",
    "panel": "#FFFFFF",
    "accent": "#1E7B5C",
    "teal": "#0E7490",
    "text": "#2A2724",
    "muted": "#6E675E",
}

# 依赖徽章色
_BADGE_OK = "#2FBF71"
_BADGE_WARN = "#F5A623"
_BADGE_ERR = "#E5484D"

# 卡片内容规格
_CARD_SPECS = {
    "gguf": {
        "title": "GGUF 本地 VLM",
        "tagline": "本地大模型版面识别，版面理解最强",
        "features": ["VLM 版面分析", "图表 / 印章 / 跨页表格", "关键字语义提取"],
        "perf": "~2s/页 · 需 6GB 显存",
        "colors": GGUF_COLORS,
    },
    "rapid": {
        "title": "RapidOCR 轻量引擎",
        "tagline": "CPU 轻量快速，零外部依赖",
        "features": ["CPU 轻量", "模板框选", "零外部依赖"],
        "perf": "轻量 · CPU 即可",
        "colors": RAPID_COLORS,
    },
}


class _EngineCard(QFrame):
    """引擎选择卡片：自绘色板、单选高亮描边、双击确认"""

    def __init__(self, engine_key: str, dialog: "EngineSelectDialog"):
        super().__init__(dialog)
        self.engine_key = engine_key
        self._dialog = dialog
        self._colors = _CARD_SPECS[engine_key]["colors"]
        self._selected = False

        self.setObjectName(f"{engine_key}Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedSize(360, 348)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(10)

        # 引擎名（accent 色）
        title = QLabel(_CARD_SPECS[engine_key]["title"])
        title.setStyleSheet(
            f"color: {self._colors['accent']}; font-size: 20px; font-weight: 700;"
        )
        layout.addWidget(title)

        # 一句话定位（teal 点缀）
        tagline = QLabel(_CARD_SPECS[engine_key]["tagline"])
        tagline.setWordWrap(True)
        tagline.setStyleSheet(
            f"color: {self._colors['teal']}; font-size: 13px;"
        )
        layout.addWidget(tagline)

        # 能力清单
        features = QLabel(
            "\n".join(f"· {f}" for f in _CARD_SPECS[engine_key]["features"])
        )
        features.setWordWrap(True)
        features.setStyleSheet(
            f"color: {self._colors['text']}; font-size: 13px; line-height: 20px;"
        )
        layout.addWidget(features)

        # 性能标签（accent 色条）
        perf = QLabel(_CARD_SPECS[engine_key]["perf"])
        perf.setAlignment(Qt.AlignmentFlag.AlignCenter)
        perf.setFixedHeight(26)
        perf.setStyleSheet(
            f"background-color: {self._colors['accent']};"
            f"color: {self._colors['bg']};"
            f"border-radius: 13px; font-size: 12px; font-weight: 600;"
        )
        layout.addWidget(perf)

        layout.addStretch(1)

        # 依赖状态徽章 + 缺项文本
        self._badge = QLabel()
        self._badge.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._badge.setFixedHeight(24)
        self._badge.setStyleSheet("color: transparent;")
        layout.addWidget(self._badge)

        self._issues_label = QLabel()
        self._issues_label.setWordWrap(True)
        self._issues_label.setStyleSheet(
            f"color: {self._colors['muted']}; font-size: 11px;"
        )
        layout.addWidget(self._issues_label)

        self._apply_style()

    # ---- 对外 ----

    def set_selected(self, selected: bool):
        """设置选中态（高亮描边）"""
        self._selected = selected
        self._apply_style()

    def set_badge(self, available: bool, issues: list):
        """更新依赖徽章：红=不可用，黄=警告，绿=就绪"""
        if available and not issues:
            self._badge.setText("就绪")
            self._badge.setStyleSheet(self._badge_style(_BADGE_OK, "#FFFFFF"))
            self._issues_label.setText("")
        elif available:
            self._badge.setText("部分依赖缺失")
            self._badge.setStyleSheet(self._badge_style(_BADGE_WARN, "#3A2400"))
            self._issues_label.setText("\n".join(issues))
        else:
            self._badge.setText("依赖不完整")
            self._badge.setStyleSheet(self._badge_style(_BADGE_ERR, "#FFFFFF"))
            self._issues_label.setText("\n".join(issues))

    # ---- 事件 ----

    def mousePressEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dialog._select_card(self.engine_key)
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dialog._select_card(self.engine_key)
            self._dialog._confirm()
        super().mouseDoubleClickEvent(event)

    # ---- 内部 ----

    def _apply_style(self):
        border = self._colors["accent"] if self._selected else "transparent"
        self.setStyleSheet(
            f"#{self.objectName()} {{"
            f"  background-color: {self._colors['panel']};"
            f"  border: 2px solid {border};"
            f"  border-radius: 12px;"
            f"}}"
        )

    def _badge_style(self, bg: str, fg: str) -> str:
        return (
            f"background-color: {bg}; color: {fg};"
            f"border-radius: 12px; font-size: 12px; font-weight: 600;"
        )


class EngineSelectDialog(QDialog):
    """引擎选择对话框：无默认选中，Esc/关闭退出程序，选中后进入"""

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        self._config = config or {}
        self._selected = None
        self._availability = {
            "gguf": {"available": True, "issues": []},
            "rapid": {"available": True, "issues": []},
        }
        self._warning_shown = False

        self.setWindowTitle("选择 OCR 引擎")
        self.setModal(True)
        self.setFixedSize(820, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(36, 30, 36, 24)
        root.setSpacing(16)

        # 标题（default 设计，跟随系统主题）
        title = QLabel("选择 OCR 引擎")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        root.addWidget(title)

        # 两张卡片并排
        cards_row = QHBoxLayout()
        cards_row.setSpacing(24)
        self.gguf_card = _EngineCard("gguf", self)
        self.rapid_card = _EngineCard("rapid", self)
        cards_row.addWidget(self.gguf_card)
        cards_row.addWidget(self.rapid_card)
        root.addLayout(cards_row)

        root.addStretch(1)

        # 底部：说明文字 + 进入按钮
        bottom = QHBoxLayout()
        hint = QLabel("本次会话使用，每次启动重新选择")
        hint.setStyleSheet("color: #8A8F99; font-size: 12px;")
        bottom.addWidget(hint)
        bottom.addStretch(1)
        self.enter_btn = PrimaryPushButton("进入", self)
        self.enter_btn.setEnabled(False)
        self.enter_btn.setFixedWidth(140)
        self.enter_btn.setFixedHeight(36)
        self.enter_btn.clicked.connect(self._confirm)
        bottom.addWidget(self.enter_btn)
        root.addLayout(bottom)

    # ---- 公开 API ----

    def selected_engine(self):
        """返回 'gguf' | 'rapid' | None（未选中）"""
        return self._selected

    def set_availability(self, availability: dict):
        """设置引擎检查结果（check_engine_availability 返回值），更新卡片徽章

        Args:
            availability: {'gguf': {'available', 'issues'}, 'rapidocr': {...}}
        """
        self._availability = {
            "gguf": availability.get("gguf", {"available": True, "issues": []}),
            "rapid": availability.get("rapidocr", {"available": True, "issues": []}),
        }
        self.gguf_card.set_badge(
            self._availability["gguf"]["available"],
            self._availability["gguf"]["issues"],
        )
        self.rapid_card.set_badge(
            self._availability["rapid"]["available"],
            self._availability["rapid"]["issues"],
        )

    # ---- 内部 ----

    def _select_card(self, engine_key: str):
        """选中一张卡片：高亮描边 + 启用进入按钮"""
        self._selected = engine_key
        for card in (self.gguf_card, self.rapid_card):
            card.set_selected(card.engine_key == engine_key)
        self.enter_btn.setEnabled(True)

    def _confirm(self):
        """确认选择：依赖不完整时先弹一次 warning，再点才进入"""
        if self._selected is None:
            return
        avail = self._availability.get(self._selected, {"available": True, "issues": []})
        if not avail["available"] and not self._warning_shown:
            self._warning_shown = True
            InfoBar.warning(
                title="依赖不完整",
                content="所选引擎依赖不完整，进入后可能初始化失败（可到『模型设置』页修正后重启引擎）",
                orient=Qt.Orientation.Horizontal,
                isClosable=True,
                position=InfoBarPosition.TOP,
                duration=3000,
                parent=self,
            )
            return
        self.accept()
