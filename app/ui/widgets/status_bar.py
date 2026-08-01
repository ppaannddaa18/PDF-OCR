"""StatusBar — 底部状态栏组件（Task 13 重构 + Task 5 三区版：24px 高度）

设计要点：
- 24px 固定高度，QHBoxLayout 三区 + 1px 分隔线：
  区1 运行状态（圆点 + 状态文本，可伸展）|
  区2 操作提示（「提示:」caption + shortcut_hint）|
  区3 后端状态（引擎圆点 + engine_label）
- set_status(text, status_type) 设置状态文本与彩色圆点
  （info/success/warning/error → text_secondary/success/warning/error）
- set_focus_area(area) 动态切换快捷键提示（file_list / pdf_preview / field_panel / global）；
  set_operation_hint(text) 直接设置操作提示文本（新 API）
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
        self._status_icon_role = 'text_secondary'
        self._engine_icon_role = 'text_disabled'
        self._separators = []  # 三区之间的 1px 分隔线（apply_theme 时重刷颜色）
        self._setup_ui()
        self.set_focus_area('global')
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _setup_ui(self):
        self.setFixedHeight(24)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'), 0,
            ThemeManager.get_spacing('sm'), 0
        )
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # ── 区1：运行状态（圆点 + 状态文本，可伸展） ──
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

        # ── 区1 | 区2 分隔线 ──
        layout.addWidget(self._make_separator())

        # ── 区2：操作提示（「提示:」caption + shortcut_hint） ──
        self.hint_caption = QLabel('提示:')
        self.hint_caption.setFont(ThemeManager.get_font('caption'))
        layout.addWidget(self.hint_caption)

        self.shortcut_hint = QLabel()
        self.shortcut_hint.setFont(ThemeManager.get_font('caption'))
        self.shortcut_hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        layout.addWidget(self.shortcut_hint)

        # ── 区2 | 区3 分隔线 ──
        layout.addWidget(self._make_separator())

        # ── 区3：后端状态（引擎圆点 + engine_label） ──
        self.engine_icon = QLabel('●')
        self._set_dot_color(self.engine_icon, 'text_disabled')
        layout.addWidget(self.engine_icon)

        self.engine_label = QLabel('引擎未初始化')
        self.engine_label.setFont(ThemeManager.get_font('caption'))
        self.engine_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        layout.addWidget(self.engine_label)

        # 构造时烘焙样式（在全部子控件创建后调用，可安全重复执行）
        self.apply_theme()

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

    def set_operation_hint(self, text: str):
        """设置操作提示文本（区2；与 set_focus_area 共用 shortcut_hint）"""
        self.shortcut_hint.setText(text)

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
            role = _ENGINE_STATUS_COLORS.get(status, 'text_disabled')
        else:
            # [Task 13 minor] 空引擎态（'', 'unavailable'）回放：灰色圆点，
            # 与 GpuStatusWidget 的 text_disabled 保持一致（原来显示红色 error）
            self.engine_label.setText('引擎未初始化')
            role = 'text_disabled'
        self._set_dot_color(self.engine_icon, role)

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用，
        构造时烘焙的颜色字符串需重新生成）"""
        self.setStyleSheet(f"""
            StatusBar {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-top: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        self.status_text.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        self.engine_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        self.shortcut_hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        self.hint_caption.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        for separator in self._separators:
            separator.setStyleSheet(
                f"background-color: {ThemeManager.get_color('border')};"
            )
        # 圆点颜色按当前状态角色重绘
        self._set_dot_color(self.status_icon, self._status_icon_role)
        self._set_dot_color(self.engine_icon, self._engine_icon_role)

    # ── 兼容属性 ──────────────────────────────────────────────

    @property
    def status_label(self) -> QLabel:
        """兼容 main_window 既有 self.status_label 引用（内部状态文本 QLabel）"""
        return self.status_text

    def setText(self, text: str):
        """setText 代理：直接设置状态文本（等价 set_status(text)）"""
        self.status_text.setText(text)

    # ── 内部工具 ──────────────────────────────────────────────

    def _make_separator(self) -> QWidget:
        """创建 1px 垂直分隔线（主题色 border；apply_theme 重刷）"""
        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setFixedHeight(16)
        self._separators.append(separator)
        return separator

    def _set_dot_color(self, label: QLabel, color_role: str):
        # 记录当前角色，主题刷新时可重绘
        if label is self.status_icon:
            self._status_icon_role = color_role
        else:
            self._engine_icon_role = color_role
        label.setStyleSheet(
            f"font-size: 8px; color: {ThemeManager.get_color(color_role)};"
        )
