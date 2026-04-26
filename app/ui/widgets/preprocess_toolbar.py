"""
图像预处理工具栏 - 修复版
修复内容:
1. _on_auto_contrast: 添加 auto_contrast 参数标记，触发实际处理
2. _on_sharpen: 添加 sharpen 参数标记，触发实际处理
3. 添加 apply_auto_contrast 和 apply_sharpen 信号用于实际处理
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QVBoxLayout, QSlider, QLabel, QSpinBox
from PyQt6.QtCore import Qt, pyqtSignal as Signal
from qfluentwidgets import (
    TransparentToolButton, BodyLabel, PushButton, ComboBox,
    InfoBar, InfoBarPosition
)

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
    """图像预处理工具栏"""
    image_changed = Signal()  # 图像处理参数改变
    apply_to_all = Signal()   # 应用到所有文件
    reset_requested = Signal()  # 重置请求
    apply_auto_contrast = Signal()  # [修复] 应用自动对比度
    apply_sharpen = Signal()  # [修复] 应用锐化

    def __init__(self, parent=None):
        super().__init__(parent)
        self._init_ui()

    def _init_ui(self):
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 2, 6, 2)
        layout.setSpacing(6)

        # 旋转控制
        self.rotation_combo = ComboBox()
        self.rotation_combo.addItems(["0°", "90°", "180°", "270°"])
        self.rotation_combo.setCurrentIndex(0)
        self.rotation_combo.setMinimumWidth(60)
        self.rotation_combo.currentIndexChanged.connect(self._on_rotation_changed)
        layout.addWidget(BodyLabel("旋转:"))
        layout.addWidget(self.rotation_combo)

        layout.addSpacing(8)

        # 亮度控制
        layout.addWidget(BodyLabel("亮度:"))
        self.brightness_slider = QSlider(Qt.Orientation.Horizontal)
        self.brightness_slider.setRange(10, 200)
        self.brightness_slider.setValue(100)
        self.brightness_slider.setMinimumWidth(60)
        self.brightness_slider.setMaximumWidth(120)
        self.brightness_slider.valueChanged.connect(self._on_brightness_changed)
        layout.addWidget(self.brightness_slider)
        self.brightness_label = BodyLabel("100%")
        self.brightness_label.setFixedWidth(36)
        layout.addWidget(self.brightness_label)

        layout.addSpacing(8)

        # 对比度控制
        layout.addWidget(BodyLabel("对比度:"))
        self.contrast_slider = QSlider(Qt.Orientation.Horizontal)
        self.contrast_slider.setRange(10, 200)
        self.contrast_slider.setValue(100)
        self.contrast_slider.setMinimumWidth(60)
        self.contrast_slider.setMaximumWidth(120)
        self.contrast_slider.valueChanged.connect(self._on_contrast_changed)
        layout.addWidget(self.contrast_slider)
        self.contrast_label = BodyLabel("100%")
        self.contrast_label.setFixedWidth(36)
        layout.addWidget(self.contrast_label)

        layout.addSpacing(8)

        # 二值化阈值
        layout.addWidget(BodyLabel("二值化:"))
        self.threshold_combo = ComboBox()
        self.threshold_combo.addItems(["关闭", "128", "150", "180", "自动"])
        self.threshold_combo.setCurrentIndex(0)
        self.threshold_combo.setMinimumWidth(60)
        self.threshold_combo.currentIndexChanged.connect(self._on_threshold_changed)
        layout.addWidget(self.threshold_combo)

        layout.addSpacing(8)

        # 快捷按钮
        self.btn_auto = PushButton("自动对比度")
        self.btn_auto.setMinimumWidth(70)
        self.btn_auto.clicked.connect(self._on_auto_contrast)
        layout.addWidget(self.btn_auto)

        self.btn_sharpen = PushButton("锐化")
        self.btn_sharpen.setMinimumWidth(50)
        self.btn_sharpen.clicked.connect(self._on_sharpen)
        layout.addWidget(self.btn_sharpen)

        layout.addSpacing(8)

        # 操作按钮
        self.btn_reset = TransparentToolButton(_get_qta().icon('fa5s.undo', color='#666'))
        self.btn_reset.setToolTip("重置所有调整")
        self.btn_reset.clicked.connect(self._on_reset)
        layout.addWidget(self.btn_reset)

        self.btn_apply_all = PushButton("应用到全部")
        self.btn_apply_all.setToolTip("将当前调整应用到所有PDF文件")
        self.btn_apply_all.setMinimumWidth(80)
        self.btn_apply_all.clicked.connect(self._on_apply_to_all)
        layout.addWidget(self.btn_apply_all)

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
        """[修复] 触发自动对比度处理"""
        self._current_params['auto_contrast_applied'] = True
        self.apply_auto_contrast.emit()  # [修复] 发送专门信号触发处理
        self._current_params['auto_contrast_applied'] = False  # 重置标记

    def _on_sharpen(self):
        """[修复] 触发锐化处理"""
        self._current_params['sharpen_applied'] = True
        self.apply_sharpen.emit()  # [修复] 发送专门信号触发处理
        self._current_params['sharpen_applied'] = False  # 重置标记

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
            'auto_contrast': False,
            'sharpen': False,
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
