"""
图像预处理工具栏 - 可折叠版（Task 10）

设计：
- 折叠态（32px）：仅显示图标按钮行（🔄旋转 / ☀️亮度 / ◐对比度 / 🔲二值化）+ 展开按钮
- 展开态（80px）：显示全部详细控件（旋转下拉框、亮度/对比度滑块、二值化下拉框、
  自动对比度、锐化、重置、应用到全部）
- 200ms 高度动画（minimumHeight / maximumHeight 同步动画，OutCubic，
  动画引用保存在 self._animations 防 GC 回收——Task 4 模式）
- 图标按钮点击直接触发对应操作（不切换展开状态），仅展开按钮切换展开/折叠
- ThemeManager 样式（无硬编码颜色）

保留的既有功能（修复版基线）：
1. _on_auto_contrast: 添加 auto_contrast 参数标记，触发实际处理
2. _on_sharpen: 添加 sharpen 参数标记，触发实际处理
3. apply_auto_contrast / apply_sharpen 信号用于实际处理
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QSlider, QPushButton
from PyQt6.QtCore import Qt, pyqtSignal as Signal, QPropertyAnimation, QEasingCurve
from qfluentwidgets import (
    TransparentToolButton, BodyLabel, PushButton, ComboBox,
)
from app.ui.theme_manager import ThemeManager

# 延迟导入qtawesome，避免字体警告
_qta = None


def _get_qta():
    """获取qtawesome实例（延迟加载）"""
    global _qta
    if _qta is None:
        import qtawesome as qta
        _qta = qta
    return _qta


class ImagePreprocessToolbar(QWidget):
    """图像预处理工具栏（可折叠）"""

    # 折叠态 / 展开态高度
    COLLAPSED_HEIGHT = 32
    EXPANDED_HEIGHT = 80
    # 高度动画时长（ms）
    ANIMATION_DURATION = 200

    # 图标按钮点击时的预设循环
    _ROTATION_PRESETS = (0, 90, 180, 270)
    _BRIGHTNESS_PRESETS = (100, 130, 70)  # %
    _CONTRAST_PRESETS = (100, 130, 70)    # %
    _THRESHOLD_PRESETS = (0, 1, 3, 4)     # ComboBox 索引：关闭/128/180/自动

    image_changed = Signal()  # 图像处理参数改变
    apply_to_all = Signal()   # 应用到所有文件
    reset_requested = Signal()  # 重置请求
    apply_auto_contrast = Signal()  # [修复] 应用自动对比度
    apply_sharpen = Signal()  # [修复] 应用锐化

    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._animations = []  # 保留动画引用，防止被 Python GC 回收导致动画不运行（Task 4 模式）
        self._init_ui()

    def _init_ui(self):
        # 初始为折叠态：最小/最大高度均锁定为折叠高度（不用 setFixedHeight，与高度动画兼容）
        self.setMinimumHeight(self.COLLAPSED_HEIGHT)
        self.setMaximumHeight(self.COLLAPSED_HEIGHT)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            0
        )
        layout.setSpacing(6)
        layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 工具栏底色（类选择器限定自身，避免样式级联影响 qfluentwidgets 子控件）
        self.setStyleSheet(
            f"ImagePreprocessToolbar {{"
            f"background-color: {ThemeManager.get_color('bg_surface')};"
            f"}}"
        )

        # 展开/折叠按钮（始终可见，仅此按钮切换展开状态）
        self.expand_btn = self._build_tool_button(
            '▼', '展开/折叠工具栏', self._toggle_expand, font_size=10
        )
        layout.addWidget(self.expand_btn)

        # 折叠态图标按钮行：点击直接触发对应操作（不切换展开状态）
        self.icon_buttons = [
            self._build_tool_button('🔄', '旋转', self._on_rotate_clicked),
            self._build_tool_button('☀️', '亮度', self._on_brightness_clicked),
            self._build_tool_button('◐', '对比度', self._on_contrast_clicked),
            self._build_tool_button('🔲', '二值化', self._on_threshold_clicked),
        ]
        for btn in self.icon_buttons:
            layout.addWidget(btn)

        # 展开后的详细控件（初始隐藏）
        self.detail_widget = QWidget()
        self._build_detail_controls()
        self.detail_widget.setVisible(False)
        layout.addWidget(self.detail_widget)

        layout.addStretch()

        # 当前参数
        self._current_params = {
            'rotation': 0,
            'brightness': 1.0,
            'contrast': 1.0,
            'threshold': None,
            'auto_contrast_applied': False,  # [修复] 添加自动对比度标记
            'sharpen_applied': False,  # [修复] 添加锐化标记
        }

    def _build_tool_button(self, text, tooltip, handler, font_size=14):
        """构建统一的图标工具按钮（ThemeManager 样式，无硬编码颜色）"""
        btn = QPushButton(text)
        btn.setFixedSize(24, 24)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                border-radius: {ThemeManager.get_radius('sm')}px;
                font-size: {font_size}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)
        btn.clicked.connect(handler)
        return btn

    def _build_detail_controls(self):
        """构建展开态详细控件（保留全部既有功能与信号）"""
        self.detail_layout = QHBoxLayout(self.detail_widget)
        self.detail_layout.setContentsMargins(0, 0, 0, 0)
        self.detail_layout.setSpacing(6)
        self.detail_layout.setAlignment(Qt.AlignmentFlag.AlignVCenter)

        # 旋转控制
        self.rotation_combo = ComboBox()
        self.rotation_combo.addItems(["0°", "90°", "180°", "270°"])
        self.rotation_combo.setCurrentIndex(0)
        self.rotation_combo.setMinimumWidth(70)
        self.rotation_combo.currentIndexChanged.connect(self._on_rotation_changed)
        self.detail_layout.addWidget(BodyLabel("旋转:"))
        self.detail_layout.addWidget(self.rotation_combo)

        self.detail_layout.addSpacing(8)

        # 亮度控制
        self.detail_layout.addWidget(BodyLabel("亮度:"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(10, 200)
        self.brightness_slider.setValue(100)
        self.brightness_slider.setMinimumWidth(80)
        self.brightness_slider.setMaximumWidth(140)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        self.detail_layout.addWidget(self.brightness_slider)
        self.brightness_label = BodyLabel("100%")
        self.brightness_label.setFixedWidth(42)
        self.detail_layout.addWidget(self.brightness_label)

        self.detail_layout.addSpacing(8)

        # 对比度控制
        self.detail_layout.addWidget(BodyLabel("对比度:"))
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(10, 200)
        self.contrast_slider.setValue(100)
        self.contrast_slider.setMinimumWidth(80)
        self.contrast_slider.setMaximumWidth(140)
        self.contrast_slider.valueChanged.connect(self._on_contrast_changed)
        self.detail_layout.addWidget(self.contrast_slider)
        self.contrast_label = BodyLabel("100%")
        self.contrast_label.setFixedWidth(42)
        self.detail_layout.addWidget(self.contrast_label)

        self.detail_layout.addSpacing(8)

        # 二值化阈值
        self.detail_layout.addWidget(BodyLabel("二值化:"))
        self.threshold_combo = ComboBox()
        self.threshold_combo.addItems(["关闭", "128", "150", "180", "自动"])
        self.threshold_combo.setCurrentIndex(0)
        self.threshold_combo.setMinimumWidth(70)
        self.threshold_combo.currentIndexChanged.connect(self._on_threshold_changed)
        self.detail_layout.addWidget(self.threshold_combo)

        self.detail_layout.addSpacing(8)

        # 快捷按钮
        self.btn_auto = PushButton("自动对比度")
        self.btn_auto.setMinimumWidth(85)
        self.btn_auto.clicked.connect(self._on_auto_contrast)
        self.detail_layout.addWidget(self.btn_auto)

        self.btn_sharpen = PushButton("锐化")
        self.btn_sharpen.setMinimumWidth(60)
        self.btn_sharpen.clicked.connect(self._on_sharpen)
        self.detail_layout.addWidget(self.btn_sharpen)

        self.detail_layout.addSpacing(8)

        # 操作按钮
        self.btn_reset = TransparentToolButton(
            _get_qta().icon('fa5s.undo', color=ThemeManager.get_color('text_secondary'))
        )
        self.btn_reset.setToolTip("重置所有调整")
        self.btn_reset.clicked.connect(self._on_reset)
        self.detail_layout.addWidget(self.btn_reset)

        self.btn_apply_all = PushButton("应用到全部")
        self.btn_apply_all.setToolTip("将当前调整应用到所有PDF文件")
        self.btn_apply_all.setMinimumWidth(95)
        self.btn_apply_all.clicked.connect(self._on_apply_to_all)
        self.detail_layout.addWidget(self.btn_apply_all)

    # ---- 折叠 / 展开 ----

    def is_expanded(self) -> bool:
        """是否处于展开状态"""
        return self._expanded

    def _toggle_expand(self):
        """切换展开/折叠（仅展开按钮触发）"""
        self._expanded = not self._expanded

        if self._expanded:
            self.detail_widget.setVisible(True)
            for btn in self.icon_buttons:
                btn.setVisible(False)
            self.expand_btn.setText('▲')
            self._animate_height(self._current_height(), self.EXPANDED_HEIGHT)
        else:
            self.detail_widget.setVisible(False)
            for btn in self.icon_buttons:
                btn.setVisible(True)
            self.expand_btn.setText('▼')
            self._animate_height(self._current_height(), self.COLLAPSED_HEIGHT)

    def _current_height(self) -> int:
        """当前实际高度，钳制在 [折叠, 展开] 区间（未显示时 height() 可能是默认值）"""
        return max(self.COLLAPSED_HEIGHT, min(self.EXPANDED_HEIGHT, self.height()))

    def _animate_height(self, start: int, end: int):
        """200ms 高度动画：minimumHeight 与 maximumHeight 同步动画（Task 4 模式）"""
        # 停止可能仍在运行的旧动画，避免新旧动画相互覆盖属性值
        for anim in self._animations:
            anim.stop()
        self._animations = []

        for prop in (b"minimumHeight", b"maximumHeight"):
            anim = QPropertyAnimation(self, prop)
            anim.setDuration(self.ANIMATION_DURATION)
            anim.setStartValue(start)
            anim.setEndValue(end)
            anim.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._animations.append(anim)
            anim.start()

    # ---- 图标按钮快捷操作（仅触发操作，不切换展开状态） ----

    def _on_rotate_clicked(self):
        """旋转图标：循环切换 0°→90°→180°→270°"""
        current = self._current_params['rotation']
        presets = self._ROTATION_PRESETS
        if current in presets:
            next_angle = presets[(presets.index(current) + 1) % len(presets)]
        else:
            next_angle = presets[0]
        self.rotation_combo.blockSignals(True)
        self.rotation_combo.setCurrentIndex(presets.index(next_angle))
        self.rotation_combo.blockSignals(False)
        self._current_params['rotation'] = next_angle
        self.image_changed.emit()

    def _on_brightness_clicked(self):
        """亮度图标：循环切换预设亮度 100%→130%→70%"""
        current_pct = int(self._current_params['brightness'] * 100)
        presets = self._BRIGHTNESS_PRESETS
        if current_pct in presets:
            next_pct = presets[(presets.index(current_pct) + 1) % len(presets)]
        else:
            next_pct = presets[0]
        self.brightness_slider.blockSignals(True)
        self.brightness_slider.setValue(next_pct)
        self.brightness_slider.blockSignals(False)
        self.brightness_label.setText(f"{next_pct}%")
        self._current_params['brightness'] = next_pct / 100.0
        self.image_changed.emit()

    def _on_contrast_clicked(self):
        """对比度图标：循环切换预设对比度 100%→130%→70%"""
        current_pct = int(self._current_params['contrast'] * 100)
        presets = self._CONTRAST_PRESETS
        if current_pct in presets:
            next_pct = presets[(presets.index(current_pct) + 1) % len(presets)]
        else:
            next_pct = presets[0]
        self.contrast_slider.blockSignals(True)
        self.contrast_slider.setValue(next_pct)
        self.contrast_slider.blockSignals(False)
        self.contrast_label.setText(f"{next_pct}%")
        self._current_params['contrast'] = next_pct / 100.0
        self.image_changed.emit()

    def _on_threshold_clicked(self):
        """二值化图标：循环切换 关闭→128→180→自动"""
        values = [None, 128, 150, 180, -1]  # 与 _on_threshold_changed 保持一致
        current = self._current_params['threshold']
        current_idx = values.index(current) if current in values else 0
        presets = self._THRESHOLD_PRESETS
        if current_idx in presets:
            next_idx = presets[(presets.index(current_idx) + 1) % len(presets)]
        else:
            next_idx = presets[0]
        self.threshold_combo.blockSignals(True)
        self.threshold_combo.setCurrentIndex(next_idx)
        self.threshold_combo.blockSignals(False)
        self._current_params['threshold'] = values[next_idx]
        self.image_changed.emit()

    # ---- 既有控件事件（保留不变） ----

    def _on_rotation_changed(self, index):
        angles = [0, 90, 180, 270]
        self._current_params['rotation'] = angles[index]
        self.image_changed.emit()

    def _on_brightness_changed(self, value):
        self._current_params['brightness'] = value / 100.0
        self.brightness_label.setText(f"{value}%")
        self.image_changed.emit()

    def _on_contrast_changed(self, value):
        self._current_params['contrast'] = value / 100.0
        self.contrast_label.setText(f"{value}%")
        self.image_changed.emit()

    def _on_threshold_changed(self, index):
        values = [None, 128, 150, 180, -1]  # -1 表示自动
        self._current_params['threshold'] = values[index]
        self.image_changed.emit()

    def _on_auto_contrast(self):
        """[修复] 触发自动对比度处理，标记持久化直到显式重置"""
        self._current_params['auto_contrast_applied'] = True
        self.apply_auto_contrast.emit()

    def _on_sharpen(self):
        """[修复] 触发锐化处理，标记持久化直到显式重置"""
        self._current_params['sharpen_applied'] = True
        self.apply_sharpen.emit()

    def _on_reset(self):
        self.rotation_combo.setCurrentIndex(0)
        self.brightness_slider.setValue(100)
        self.contrast_slider.setValue(100)
        self.threshold_combo.setCurrentIndex(0)
        self._current_params = {
            'rotation': 0,
            'brightness': 1.0,
            'contrast': 1.0,
            'threshold': None,
            'auto_contrast_applied': False,  # [修复] 使用一致的键名
            'sharpen_applied': False,        # [修复] 使用一致的键名
        }
        self.reset_requested.emit()

    def _on_apply_to_all(self):
        self.apply_to_all.emit()

    def get_params(self) -> dict:
        """获取当前处理参数"""
        return self._current_params.copy()

    def set_params(self, params: dict):
        """设置处理参数（用于恢复）"""
        # 阻止信号触发，避免重复处理
        self.rotation_combo.blockSignals(True)
        self.brightness_slider.blockSignals(True)
        self.contrast_slider.blockSignals(True)
        self.threshold_combo.blockSignals(True)

        try:
            # 恢复旋转
            rotation = params.get('rotation', 0)
            angles = [0, 90, 180, 270]
            if rotation in angles:
                self.rotation_combo.setCurrentIndex(angles.index(rotation))

            # 恢复亮度
            brightness = params.get('brightness', 1.0)
            brightness_value = int(brightness * 100)
            self.brightness_slider.setValue(brightness_value)
            self.brightness_label.setText(f"{brightness_value}%")

            # 恢复对比度
            contrast = params.get('contrast', 1.0)
            contrast_value = int(contrast * 100)
            self.contrast_slider.setValue(contrast_value)
            self.contrast_label.setText(f"{contrast_value}%")

            # 恢复二值化阈值
            threshold = params.get('threshold', None)
            values = [None, 128, 150, 180, -1]
            if threshold in values:
                self.threshold_combo.setCurrentIndex(values.index(threshold))

            # 更新参数字典
            self._current_params = params.copy()
        finally:
            # 恢复信号
            self.rotation_combo.blockSignals(False)
            self.brightness_slider.blockSignals(False)
            self.contrast_slider.blockSignals(False)
            self.threshold_combo.blockSignals(False)

    def set_enabled(self, enabled: bool):
        """设置控件启用状态"""
        self.rotation_combo.setEnabled(enabled)
        self.brightness_slider.setEnabled(enabled)
        self.contrast_slider.setEnabled(enabled)
        self.threshold_combo.setEnabled(enabled)
        self.btn_auto.setEnabled(enabled)
        self.btn_sharpen.setEnabled(enabled)
        self.btn_reset.setEnabled(enabled)
        self.btn_apply_all.setEnabled(enabled)
        self.expand_btn.setEnabled(enabled)
        for btn in self.icon_buttons:
            btn.setEnabled(enabled)
