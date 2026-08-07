"""
引擎选择对话框 - 启动时在 GGUF / RapidOCR 之间强制选择（Task P1 重设计）

结构：顶部品牌区 + 60/40 非对称卡片区 + 底部动作轨（工位分配台）。
对话框固定浅色（setTheme(LIGHT)），不随系统主题变化；GGUF 卡片使用
深色信号台色板、Rapid 卡片使用暖纸档案绿色板（色值从 ThemeManager
调色板映射，不重复硬编码）。

交互约束（硬性）：
- 无默认选中；「进入」按钮默认禁用，选中卡片后才可用
- 单选卡片高亮描边 + 「本会话」预订标签；双击卡片 = 选择并确认
- 卡片支持键盘：Space=选中，Enter=选中并确认
- Esc / 关闭按钮 / X = 退出程序（choose_engine 侧处理 QApplication.quit()）
- 依赖缺失时仍允许选择，确认时弹一次 InfoBar.warning
"""
from PyQt6.QtCore import Qt
from PyQt6.QtGui import QKeyEvent, QMouseEvent
from PyQt6.QtWidgets import (
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QVBoxLayout,
)
from qfluentwidgets import (
    InfoBar, InfoBarPosition, PrimaryPushButton, Theme, setTheme,
)

from app.ui.theme_manager import ThemeManager


def _palette_colors(design: str, palette_key: str) -> dict:
    """从 ThemeManager 调色板映射卡片所需颜色（避免硬编码重复色板）"""
    p = ThemeManager.COLORS[design][palette_key]
    return {
        "bg": p["bg_primary"],
        "panel": p["bg_surface"],
        "surface_2": p.get("surface_2", p["bg_hover"]),
        "selected_bg": (
            p.get("surface_2", p["bg_hover"])
            if design == "gguf"
            else p.get("bg_selected", p.get("surface_2", p["bg_hover"]))
        ),
        "accent": p.get("accent", p["primary"]),
        "on_accent": p["on_accent"],
        "teal": p.get("accent_alt", p["primary_hover"]),
        "text": p["text_primary"],
        "muted": p["text_secondary"],
        "hover_border": p["border_focus"],
        "ok": p["success"],
        "warn": p.get("warning_text", p["warning"]),
        "err": p["error"],
    }


GGUF_COLORS = _palette_colors("gguf", "dark")
RAPID_COLORS = _palette_colors("rapid", "light")

# 卡片内容规格
_CARD_SPECS = {
    "gguf": {
        "title": "GGUF 本地 VLM",
        "tagline": "本地大模型版面识别，版面理解最强",
        "features": ["VLM 版面分析", "图表 / 印章 / 跨页表格", "关键字语义提取"],
        "perf": "约 2 秒/页，需 6GB 显存",
        "tooltip": "GGUF 是 llama.cpp 模型格式；VLM（视觉语言模型）能理解整页版面，适合复杂文档。",
        "colors": GGUF_COLORS,
    },
    "rapid": {
        "title": "RapidOCR 轻量引擎",
        "tagline": "CPU 轻量快速，零外部依赖",
        "features": ["CPU 轻量", "模板框选", "零外部依赖"],
        "perf": "轻量，CPU 即可",
        "tooltip": "RapidOCR 是传统 OCR 引擎，CPU 轻量运行，适合模板框选式识别。",
        "colors": RAPID_COLORS,
    },
}


class _EngineCard(QFrame):
    """引擎选择卡片：品牌色面板、单选高亮、键盘可操作、双击确认"""

    def __init__(self, engine_key: str, dialog: "EngineSelectDialog"):
        super().__init__(dialog)
        self.engine_key = engine_key
        self._dialog = dialog
        self._colors = _CARD_SPECS[engine_key]["colors"]
        self._selected = False

        self.setObjectName(f"{engine_key}Card")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMinimumHeight(360)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(12)

        # 标题行：单选圆圈 + 引擎名（accent 色）+ 「本会话」预订标签
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        self._radio = QLabel()
        self._radio.setFixedSize(18, 18)
        self._radio.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._radio.setStyleSheet(
            f"border: 2px solid {self._colors['muted']};"
            f"border-radius: 9px; background: transparent; color: transparent;"
        )
        title_row.addWidget(self._radio, 0, Qt.AlignmentFlag.AlignTop)

        self._title = QLabel(_CARD_SPECS[engine_key]["title"])
        self._title.setToolTip(_CARD_SPECS[engine_key]["tooltip"])
        self._title.setStyleSheet(
            f"color: {self._colors['accent']}; font-size: 18px; font-weight: 600;"
        )
        title_row.addWidget(self._title)
        title_row.addStretch(1)

        self._session_tag = QLabel("本会话")
        self._session_tag.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._session_tag.setFixedHeight(22)
        self._session_tag.setStyleSheet(
            f"background-color: {self._colors['accent']};"
            f"color: {self._colors['on_accent']};"
            f"border-radius: 11px; font-size: 11px; font-weight: 600;"
            f"padding: 0 10px;"
        )
        self._session_tag.setVisible(False)
        title_row.addWidget(self._session_tag, 0, Qt.AlignmentFlag.AlignTop)
        layout.addLayout(title_row)

        # 状态行：圆点 + 文字（语义色，非按钮外观）
        status_row = QHBoxLayout()
        status_row.setSpacing(4)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet(
            f"color: {self._colors['ok']}; font-size: 11px;"
        )
        status_row.addWidget(self._status_dot)
        self._badge = QLabel()
        self._badge.setStyleSheet(
            f"color: {self._colors['ok']}; font-size: 11px; font-weight: 600;"
        )
        status_row.addWidget(self._badge)
        status_row.addStretch(1)
        layout.addLayout(status_row)

        # 一句话定位（teal 点缀）
        tagline = QLabel(_CARD_SPECS[engine_key]["tagline"])
        tagline.setWordWrap(True)
        tagline.setStyleSheet(
            f"color: {self._colors['teal']}; font-size: 13px;"
        )
        layout.addWidget(tagline)

        # 能力清单
        features = QLabel(
            "\n".join("✓ " + f for f in _CARD_SPECS[engine_key]["features"])
        )
        features.setWordWrap(True)
        features.setStyleSheet(
            f"color: {self._colors['text']}; font-size: 13px; line-height: 22px;"
        )
        layout.addWidget(features)

        # 性能标签（accent 描边小标签，非全宽胶囊）
        perf = QLabel(_CARD_SPECS[engine_key]["perf"])
        perf.setAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        perf.setFixedHeight(22)
        perf.setStyleSheet(
            f"border: 1px solid {self._colors['accent']};"
            f"color: {self._colors['accent']};"
            f"border-radius: 10px; padding: 2px 10px;"
            f"font-size: 11px; font-weight: 600;"
        )
        layout.addWidget(perf)

        layout.addStretch(1)

        # 缺项文本
        self._issues_label = QLabel()
        self._issues_label.setWordWrap(True)
        self._issues_label.setStyleSheet(
            f"color: {self._colors['muted']}; font-size: 11px;"
        )
        layout.addWidget(self._issues_label)

        self._apply_style()

    # ---- 对外 ----

    def set_selected(self, selected: bool):
        """设置选中态（圆圈勾选 + 高亮描边 + 「本会话」标签 + 背景微变）"""
        self._selected = selected
        self._session_tag.setVisible(selected)
        self._apply_style()

    def set_badge(self, available: bool, issues: list):
        """更新状态：绿=就绪，黄=警告，红=不可用（圆点+文字）"""
        if available and not issues:
            color = self._colors["ok"]
            text = "就绪"
        elif available:
            color = self._colors["warn"]
            text = "部分依赖缺失"
        else:
            color = self._colors["err"]
            text = "依赖不完整"
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 11px;")
        self._badge.setStyleSheet(
            f"color: {color}; font-size: 11px; font-weight: 600;")
        self._badge.setText(text)
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

    def keyPressEvent(self, event: QKeyEvent):
        if event.key() in (Qt.Key.Key_Space, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._dialog._select_card(self.engine_key)
            if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
                self._dialog._confirm()
            event.accept()
            return
        super().keyPressEvent(event)

    # ---- 内部 ----

    def _apply_style(self):
        border = self._colors["accent"] if self._selected else "transparent"
        panel = self._colors["selected_bg"] if self._selected else self._colors["panel"]
        if self._selected:
            self._radio.setStyleSheet(
                f"border: 2px solid {self._colors['accent']};"
                f"border-radius: 9px;"
                f"background-color: {self._colors['accent']};"
                f"color: {self._colors['on_accent']};"
                f"font-size: 11px; font-weight: 700;"
            )
            self._radio.setText("✓")
        else:
            self._radio.setStyleSheet(
                f"border: 2px solid {self._colors['muted']};"
                f"border-radius: 9px; background: transparent; color: transparent;"
            )
            self._radio.setText("")
        self.setProperty("selected", "true" if self._selected else "false")
        self.setStyleSheet(
            f"#{self.objectName()} {{"
            f"  background-color: {panel};"
            f"  border: 2px solid {border};"
            f"  border-radius: 12px;"
            f"}}"
            f"#{self.objectName()}:hover {{"
            f"  border: 2px solid {self._colors['hover_border']};"
            f"}}"
            f"#{self.objectName()}:focus {{"
            f"  border: 2px solid {self._colors['hover_border']};"
            f"}}"
            # 选中态优先于聚焦/悬停（同特异性，后写生效）
            f"#{self.objectName()}[selected='true'] {{"
            f"  border: 2px solid {self._colors['accent']};"
            f"}}"
        )


class EngineSelectDialog(QDialog):
    """引擎选择对话框：无默认选中，Esc/关闭退出程序，选中后进入"""

    def __init__(self, config: dict = None, parent=None):
        super().__init__(parent)
        # 固定浅色，不随系统主题变化；GGUF 窗口进入后再由 _apply_design 切深色
        setTheme(Theme.LIGHT)

        self._selected = None
        self._availability = {
            "gguf": {"available": True, "issues": []},
            "rapid": {"available": True, "issues": []},
        }
        self._warning_shown = set()  # 已弹过 warning 的引擎 key（按引擎记录）

        self.setWindowTitle("选择 OCR 引擎")
        self.setModal(True)
        self.setMinimumSize(880, 640)  # 可增长：缺项文本多行/高 DPI 时不裁底部按钮

        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 24)
        root.setSpacing(16)

        # 顶部品牌区
        brand_row = QHBoxLayout()
        brand = QLabel("PDF OCR")
        brand.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
            f"font-size: 16px; font-weight: 600;"
        )
        brand_row.addWidget(brand)
        brand_row.addStretch(1)
        root.addLayout(brand_row)

        separator = QFrame()
        separator.setFixedHeight(1)
        separator.setStyleSheet(
            f"background-color: {ThemeManager.get_color('border')}; border: none;"
        )
        root.addWidget(separator)

        # 标题区
        title = QLabel("选择本次会话的识别引擎")
        title.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
            f"font-size: 22px; font-weight: 600;"
        )
        root.addWidget(title)

        subtitle = QLabel(
            "请根据文档类型选择合适的识别引擎，单次会话仅限一种。"
        )
        subtitle.setWordWrap(True)
        subtitle.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')}; font-size: 13px;"
        )
        root.addWidget(subtitle)

        # 卡片区（60/40 非对称：GGUF 左主、Rapid 右辅）
        cards_row = QHBoxLayout()
        cards_row.setSpacing(20)
        self.gguf_card = _EngineCard("gguf", self)
        self.rapid_card = _EngineCard("rapid", self)
        self.gguf_card.setMinimumWidth(460)
        self.rapid_card.setMinimumWidth(300)
        cards_row.addWidget(self.gguf_card, 3)
        cards_row.addWidget(self.rapid_card, 2)
        root.addLayout(cards_row)

        root.addStretch(1)

        # 底部动作轨
        bottom = QHBoxLayout()
        hint = QLabel("本次会话使用，每次启动重新选择")
        hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')}; font-size: 12px;"
        )
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
        """选中一张卡片：高亮描边 + 「本会话」标签 + 启用进入按钮"""
        self._selected = engine_key
        for card in (self.gguf_card, self.rapid_card):
            card.set_selected(card.engine_key == engine_key)
        self.enter_btn.setEnabled(True)

    def _confirm(self):
        """确认选择：依赖不完整时每个引擎先弹一次 warning，再点才进入"""
        if self._selected is None:
            return
        avail = self._availability.get(self._selected, {"available": True, "issues": []})
        if not avail["available"] and self._selected not in self._warning_shown:
            self._warning_shown.add(self._selected)
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
