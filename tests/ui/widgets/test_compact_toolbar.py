# tests/ui/widgets/test_compact_toolbar.py
import pytest
from PyQt6.QtWidgets import QApplication

from app.ui.widgets.compact_toolbar import CompactToolbar
from app.ui.widgets.gpu_status import GpuStatusWidget


class FakeEngine:
    """最小引擎桩：供 GpuStatusWidget 绑定测试"""

    engine_name = "gguf"
    is_ready = True


class TestCompactToolbar:
    def test_create_toolbar(self, qapp):
        toolbar = CompactToolbar()
        assert toolbar.height() == 36

    def test_engine_options(self, qapp):
        toolbar = CompactToolbar()
        assert toolbar.engine_combo.count() == 3
        assert toolbar.engine_combo.itemText(0) == 'GGUF (GPU)'

    def test_signals(self, qapp):
        toolbar = CompactToolbar()
        signals = {}

        def capture(name):
            def handler():
                signals[name] = True
            return handler

        toolbar.upload_clicked.connect(capture('upload'))
        toolbar.test_ocr_clicked.connect(capture('test'))
        toolbar.batch_ocr_clicked.connect(capture('batch'))
        toolbar.save_template_clicked.connect(capture('save'))
        toolbar.load_template_clicked.connect(capture('load'))
        toolbar.settings_clicked.connect(capture('settings'))

        # 模拟点击（通过信号）
        toolbar.upload_clicked.emit()
        assert signals['upload']

    def test_engine_changed(self, qapp):
        toolbar = CompactToolbar()
        changed = []
        toolbar.engine_changed.connect(changed.append)
        toolbar.engine_combo.setCurrentIndex(1)
        assert changed == ['GGUF (CPU)']

    def test_nav_toggle_signal(self, qapp):
        """导航图开关按钮存在且点击发射 nav_toggle_clicked"""
        toolbar = CompactToolbar()
        emitted = []
        toolbar.nav_toggle_clicked.connect(lambda: emitted.append(True))
        assert hasattr(toolbar, 'nav_toggle_btn')
        assert toolbar.nav_toggle_btn.toolTip() == '切换版面导航图'
        toolbar.nav_toggle_btn.click()
        assert emitted == [True]

    def test_set_engine_status(self, qapp):
        toolbar = CompactToolbar()
        toolbar.set_engine_status('GGUF', 'ready')
        assert '就绪' in toolbar.engine_status.toolTip() or 'ready' in toolbar.engine_status.toolTip()

    def test_set_engine_status_emits_signal(self, qapp):
        """外部设置引擎状态时也必须发射 status_changed，保证状态来源一致"""
        toolbar = CompactToolbar()
        emitted = []
        toolbar.engine_status.status_changed.connect(
            lambda engine, status: emitted.append((engine, status))
        )
        toolbar.set_engine_status('GGUF', 'ready')
        assert emitted == [('GGUF', 'ready')]
        emitted.clear()
        toolbar.set_engine_status('RapidOCR', 'cpu_mode')
        assert emitted == [('RapidOCR', 'cpu_mode')]

    def test_engine_status_embeds_gpu_status_widget(self, qapp):
        """引擎状态指示器已集成 GpuStatusWidget（彩色圆点 + 缩写）"""
        toolbar = CompactToolbar()
        assert isinstance(toolbar.engine_status, GpuStatusWidget)

    def test_bind_engine_updates_status(self, qapp):
        """绑定引擎后，状态指示器显示就绪缩写"""
        toolbar = CompactToolbar()
        toolbar.engine_status.set_engine(FakeEngine())
        assert 'GGUF' in toolbar.engine_status.status_label.text()
        assert toolbar.engine_status.status_icon.styleSheet()  # 非空即已设置圆点颜色
        toolbar.engine_status.cleanup()
