"""Task 13 重构回归测试：独立 StatusBar 组件

覆盖核心行为：
- 24px 固定高度（setFixedHeight(24)）
- set_status 文本与彩色状态圆点（info/success/warning/error → 主题色）
- set_focus_area 四档快捷键提示切换 + 未知档回退 global
- status_label 兼容属性（main_window 25 处 setText 调用无需修改）
- set_engine_status 引擎状态桥接（小写 engine_name / 显示名兼容、
  ready/initializing/unavailable/cpu_mode → 圆点颜色）
- 暗色主题下颜色仍来自 ThemeManager（无硬编码颜色）
"""
import pytest
from PyQt6.QtWidgets import QLabel

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.status_bar import StatusBar


def dot_color(label: QLabel) -> str:
    """从圆点样式表中提取 color 值"""
    for part in label.styleSheet().split(';'):
        if 'color' in part:
            return part.split(':', 1)[1].strip()
    return ''


class TestGeometry:
    def test_fixed_height_24(self, qapp):
        bar = StatusBar()
        assert bar.minimumHeight() == 24
        assert bar.maximumHeight() == 24


class TestThreeSections:
    """Task 5 三区拆分：运行状态 | 操作提示 | 后端状态"""

    def test_three_sections_present(self, qapp):
        bar = StatusBar()
        # 区1：运行状态
        assert isinstance(bar.status_icon, QLabel)
        assert bar.status_text.text() == '就绪 - 请上传 PDF 文件开始'
        # 区2：操作提示（「提示:」caption + shortcut_hint）
        assert bar.hint_caption.text() == '提示:'
        assert bar.shortcut_hint.text() != ''
        # 区3：后端状态
        assert bar.engine_label.text() == '引擎未初始化'

    def test_two_separators_between_sections(self, qapp):
        bar = StatusBar()
        assert len(bar._separators) == 2
        for sep in bar._separators:
            assert ThemeManager.get_color('border') in sep.styleSheet()

    def test_separators_follow_dark_theme(self, qapp):
        ThemeManager.set_theme('dark')
        bar = StatusBar()
        assert ThemeManager.get_color('border') in bar._separators[0].styleSheet()

    def test_hint_caption_follows_theme(self, qapp):
        bar = StatusBar()
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('text_disabled') in bar.hint_caption.styleSheet()


class TestSetOperationHint:
    def test_set_operation_hint_text(self, qapp):
        bar = StatusBar()
        bar.set_operation_hint('按 F2 快速解析')
        assert bar.shortcut_hint.text() == '按 F2 快速解析'

    def test_focus_area_overwrites_operation_hint(self, qapp):
        """set_focus_area 与 set_operation_hint 共用 shortcut_hint，后者最后生效"""
        bar = StatusBar()
        bar.set_operation_hint('临时提示')
        bar.set_focus_area('file_list')
        assert bar.shortcut_hint.text() == 'Ctrl+O 上传 | Delete 移除 | Space 预览'


class TestSetStatus:
    def test_set_status_text(self, qapp):
        bar = StatusBar()
        bar.set_status("已保存模板")
        assert bar.status_text.text() == "已保存模板"

    def test_set_status_info_default_uses_text_secondary(self, qapp):
        bar = StatusBar()
        bar.set_status("就绪", 'info')
        assert dot_color(bar.status_icon) == ThemeManager.get_color('text_secondary')

    @pytest.mark.parametrize('status_type,role', [
        ('success', 'success'),
        ('warning', 'warning'),
        ('error', 'error'),
    ])
    def test_set_status_colors(self, qapp, status_type, role):
        bar = StatusBar()
        bar.set_status("msg", status_type)
        assert dot_color(bar.status_icon) == ThemeManager.get_color(role)

    def test_set_status_unknown_type_falls_back_info(self, qapp):
        bar = StatusBar()
        bar.set_status("msg", 'bogus_type')
        assert dot_color(bar.status_icon) == ThemeManager.get_color('text_secondary')

    def test_status_colors_follow_dark_theme(self, qapp):
        """暗色主题下颜色来自 ThemeManager（非硬编码）"""
        ThemeManager.set_theme('dark')
        bar = StatusBar()
        bar.set_status("msg", 'success')
        assert dot_color(bar.status_icon) == ThemeManager.get_color('success')
        assert ThemeManager.get_color('success') == '#22c55e'  # 暗色主题值，非亮色值


class TestSetFocusArea:
    EXPECTED_HINTS = {
        'file_list': 'Ctrl+O 上传 | Delete 移除 | Space 预览',
        'pdf_preview': '左键框选 | 右键平移 | 滚轮缩放',
        'field_panel': 'Ctrl+S 保存 | Delete 删除字段',
        'global': 'Ctrl+Shift+L 文件栏 | Ctrl+Shift+R 字段栏',
    }

    def test_default_focus_is_global(self, qapp):
        bar = StatusBar()
        assert bar.shortcut_hint.text() == self.EXPECTED_HINTS['global']

    @pytest.mark.parametrize('area', ['file_list', 'pdf_preview', 'field_panel', 'global'])
    def test_four_areas_switch_hints(self, qapp, area):
        bar = StatusBar()
        bar.set_focus_area(area)
        assert bar.shortcut_hint.text() == self.EXPECTED_HINTS[area]

    def test_unknown_area_falls_back_global(self, qapp):
        bar = StatusBar()
        bar.set_focus_area('nonsense_area')
        assert bar.shortcut_hint.text() == self.EXPECTED_HINTS['global']

    def test_focus_area_switch_is_dynamic(self, qapp):
        bar = StatusBar()
        bar.set_focus_area('file_list')
        first = bar.shortcut_hint.text()
        bar.set_focus_area('pdf_preview')
        assert first != bar.shortcut_hint.text()
        assert bar.shortcut_hint.text() == self.EXPECTED_HINTS['pdf_preview']


class TestStatusLabelCompat:
    def test_status_label_property_returns_internal_label(self, qapp):
        bar = StatusBar()
        assert bar.status_label is bar.status_text
        assert isinstance(bar.status_label, QLabel)

    def test_set_text_via_status_label(self, qapp):
        """模拟 main_window 既有 self.status_label.setText(...) 用法"""
        bar = StatusBar()
        bar.status_label.setText("已加载 5 个文件")
        assert bar.status_text.text() == "已加载 5 个文件"

    def test_set_text_proxy_on_bar(self, qapp):
        bar = StatusBar()
        bar.setText("兼容代理")
        assert bar.status_text.text() == "兼容代理"

    def test_default_status_text(self, qapp):
        bar = StatusBar()
        assert bar.status_text.text() == '就绪 - 请上传 PDF 文件开始'


class TestEngineStatus:
    @pytest.mark.parametrize('engine,status,expected_text,role', [
        ('gguf', 'ready', 'GGUF 就绪', 'success'),
        ('GGUF', 'initializing', 'GGUF 加载中', 'warning'),
        ('rapidocr', 'cpu_mode', 'RapidOCR CPU模式', 'text_disabled'),
        ('RapidOCR', 'unavailable', 'RapidOCR 不可用', 'error'),
    ])
    def test_engine_display_and_dot(self, qapp, engine, status, expected_text, role):
        """小写 engine_name 与显示名两种形式均兼容"""
        bar = StatusBar()
        bar.set_engine_status(engine, status)
        assert bar.engine_label.text() == expected_text
        assert dot_color(bar.engine_icon) == ThemeManager.get_color(role)

    def test_empty_engine_shows_uninitialized(self, qapp):
        """[Task 13 minor 修复] 空引擎态（'', 'unavailable'）回放：灰色圆点，
        与 GpuStatusWidget 的 text_disabled 保持一致（原为红色 error）"""
        bar = StatusBar()
        bar.set_engine_status('', 'unavailable')
        assert bar.engine_label.text() == '引擎未初始化'
        assert dot_color(bar.engine_icon) == ThemeManager.get_color('text_disabled')

    def test_default_engine_state(self, qapp):
        bar = StatusBar()
        assert bar.engine_label.text() == '引擎未初始化'
        assert dot_color(bar.engine_icon) == ThemeManager.get_color('text_disabled')

    def test_engine_status_does_not_clobber_status_text(self, qapp):
        bar = StatusBar()
        bar.set_status("批量识别完成 - 成功 12/15")
        bar.set_engine_status('gguf', 'ready')
        assert bar.status_text.text() == "批量识别完成 - 成功 12/15"
