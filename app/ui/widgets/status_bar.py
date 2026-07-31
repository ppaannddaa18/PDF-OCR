"""StatusBar — 底部状态栏组件（Task 13 重构版：24px 高度 + 动态快捷键提示）

设计要点：
- 24px 固定高度，QHBoxLayout：左侧状态圆点 + 状态文本，右侧引擎状态 + 动态快捷键提示
- set_status(text, status_type) 设置状态文本与彩色圆点
  （info/success/warning/error → text_secondary/success/warning/error）
- set_focus_area(area) 动态切换快捷键提示（file_list / pdf_preview / field_panel / global）
- set_engine_status(engine, status) 消费 GpuStatusWidget.status_changed 信号：
  status 词汇 'ready'|'initializing'|'unavailable'|'cpu_mode' →
  success/warning/error/text_disabled，engine 兼容小写 engine_name（'gguf'）
  与显示名（'GGUF'）两种形式
- 兼容属性：status_label 返回内部状态文本 QLabel；StatusBar.setText 代理到
  状态文本，main_window 既有 25 处 self.status_label.setText(...) 无需逐个修改
- 全部颜色/字体/间距来自 ThemeManager，禁止硬编码颜色
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel

from app.ui.theme_manager import ThemeManager

# 引擎状态 → 圆点颜色角色（与 GpuStatusWidget 词汇一致）
_ENGINE_STATUS_COLORS = {
    'ready': 'success',
    'initializing': 'warning',
    'unavailable': 'error',
    'cpu_mode': 'text_disabled',
}

# 引擎状态 → 中文文案
_ENGINE_STATUS_WORDS = {
    'ready': '就绪',
    'initializing': '加载中',
    'unavailable': '不可用',
    'cpu_mode': 'CPU模式',
}

# 引擎名归一化（status_changed 可能发小写 engine_name）
_ENGINE_NAMES = {
    'gguf': 'GGUF',
    'rapidocr': 'RapidOCR',
}

# 焦点区域 → 快捷键提示
_FOCUS_HINTS = {
    'file_list': 'Ctrl+O 上传 | Delete 移除 | Space 预览',
    'pdf_preview': '左键框选 | 右键平移 | 滚轮缩放',
    'field_panel': 'Ctrl+S 保存 | Delete 删除字段',
    'global': 'Ctrl+Shift+L 文件栏 | Ctrl+Shift+R 字段栏',
}

# 状态类型 → 圆点颜色角色
_STATUS_COLORS = {
    'info': 'text_secondary',
    'success': 'success',
    'warning': 'warning',
    'error': 'error',
}


class StatusBar(QWidget):
    """底部状态栏：状态文本 + 彩色圆点 + 引擎状态 + 动态快捷键提示"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._current_focus = 'global'
        self._setup_ui()
        self.set_focus_area('global')

    def _setup_ui(self):
        self.setFixedHeight(24)
        self.setStyleSheet(f"""
            StatusBar {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-top: 1px solid {ThemeManager.get_color('border')};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'), 0,
            ThemeManager.get_spacing('sm'), 0
        )
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # 左侧状态圆点 + 状态文本
        self.status_icon = QLabel('●')
        self._set_dot_color(self.status_icon, 'text_secondary')
        layout.addWidget(self.status_icon)

        self.status_text = QLabel('就绪 - 请上传 PDF 文件开始')
        self.status_text.setFont(ThemeManager.get_font('caption'))
        self.status_text.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        layout.addWidget(self.status_text)

        layout.addStretch()

        # 右侧引擎状态（圆点 + 名称，消费 GpuStatusWidget.status_changed）
        self.engine_icon = QLabel('●')
        self._set_dot_color(self.engine_icon, 'text_disabled')
        layout.addWidget(self.engine_icon)

        self.engine_label = QLabel('引擎未初始化')
        self.engine_label.setFont(ThemeManager.get_font('caption'))
        self.engine_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        layout.addWidget(self.engine_label)

        # 右侧动态快捷键提示
        self.shortcut_hint = QLabel()
        self.shortcut_hint.setFont(ThemeManager.get_font('caption'))
        self.shortcut_hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        layout.addWidget(self.shortcut_hint)

    # ── 对外接口 ──────────────────────────────────────────────

    def set_status(self, text: str, status_type: str = 'info'):
        """设置状态文本与彩色圆点

        Args:
            text: 状态文本
            status_type: 'info' | 'success' | 'warning' | 'error'
        """
        self.status_text.setText(text)
        role = _STATUS_COLORS.get(status_type, _STATUS_COLORS['info'])
        self._set_dot_color(self.status_icon, role)

    def set_focus_area(self, area: str):
        """根据焦点区域更新快捷键提示

        Args:
            area: 'file_list' | 'pdf_preview' | 'field_panel' | 'global'
        """
        self._current_focus = area
        self.shortcut_hint.setText(_FOCUS_HINTS.get(area, _FOCUS_HINTS['global']))

    def set_engine_status(self, engine: str, status: str):
        """显示引擎状态（桥接 GpuStatusWidget.status_changed）

        Args:
            engine: 引擎名，兼容小写 engine_name（'gguf'）与显示名（'GGUF'）
            status: 'ready' | 'initializing' | 'unavailable' | 'cpu_mode'
        """
        name = _ENGINE_NAMES.get(engine, engine)
        if engine:
            word = _ENGINE_STATUS_WORDS.get(status, '')
            self.engine_label.setText(f"{name} {word}".strip())
        else:
            self.engine_label.setText('引擎未初始化')
        role = _ENGINE_STATUS_COLORS.get(status, 'text_disabled')
        self._set_dot_color(self.engine_icon, role)

    # ── 兼容属性 ──────────────────────────────────────────────

    @property
    def status_label(self) -> QLabel:
        """兼容 main_window 既有 self.status_label 引用（内部状态文本 QLabel）"""
        return self.status_text

    def setText(self, text: str):
        """setText 代理：直接设置状态文本（等价 set_status(text)）"""
        self.status_text.setText(text)

    # ── 内部工具 ──────────────────────────────────────────────

    def _set_dot_color(self, label: QLabel, color_role: str):
        label.setStyleSheet(
            f"font-size: 8px; color: {ThemeManager.get_color(color_role)};"
        )
