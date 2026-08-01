"""Task 16 集成测试：MainWindow 全链路冒烟（UI 重构计划收尾）

覆盖：
- MainWindow 创建（窗口 / 中央区 / 三个子页面）
- 面板折叠/展开（CollapsiblePanel 集成，Task 4/5）
- 主题切换（ThemeManager 状态，Task 15）
- 快捷键绑定（Task 7：QShortcut.objectName = 快捷键字符串，findChild 可寻）
- 焦点跟踪（Task 16 接线：StatusBar.set_focus_area 随焦点区域切换，Task 13 遗留）

说明：
- 不构造真实 OCR 引擎（避免加载模型 / 启动 llama-server 子进程），
  通过 monkeypatch get_ocr_engine 注入 FakeEngine（与
  test_main_window_new_template.py 同一模式）
- 全部在 offscreen 平台运行：不得真实启动引擎/网络/服务器
- 断言全部基于可观察状态（is_collapsed / shortcut_hint 文本 / 可见性），非恒真
- 焦点测试：offscreen 平台无激活窗口（QWidget.setFocus 静默失效），
  通过发射 QApplication.focusChanged 信号模拟焦点转移——同样走真实接线
  （_connect_focus_tracking → _on_focus_changed → set_focus_area），
  连接缺失/映射错误都会导致断言失败
"""
import pytest
from PyQt6 import sip
from PyQt6.QtGui import QShortcut
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication

from app.ui import main_window as mw_module
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.status_bar import StatusBar


class FakeEngine:
    """最小引擎桩：避免真实 OCR 初始化（加载模型 / 启动 llama-server）"""

    engine_name = "gguf"
    is_ready = True
    init_error = None

    def initialize(self):
        self.is_ready = True


def _make_config() -> dict:
    return {
        "app": {"name": "PDFOCR", "window_size": [1400, 900], "theme": "light"},
        "ocr": {"engine": "gguf", "gguf": {"device": "gpu"}},
        "pdf": {"render_dpi": 200},
        "batch": {"max_workers": 2},
        "export": {"include_confidence": True},
    }


@pytest.fixture
def main_window(qapp, monkeypatch):
    monkeypatch.setattr(mw_module, "get_ocr_engine", lambda config: FakeEngine())
    # 防御：若用户机器 ~/.pdfocr/pending_task.json 存在，MainWindow 构造后
    # 500ms 的 _check_pending_task 定时器会 exec() 模态 MessageBox，offscreen
    # 环境无人交互将永久挂起。测试中禁用恢复流程。
    from app.ui.widgets.cancel_result_dialog import CancelResultDialog
    monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
    w = mw_module.MainWindow(_make_config())
    yield w
    _destroy_test_window(w)


def _destroy_test_window(w):
    """销毁测试窗口（顺序污染修复，Task 16）

    不调用 w.close()：closeEvent 会启动异步清理线程并最终经
    QTimer.singleShot 调 QApplication.quit()，影响 tests/ui 共享的 qapp
    单例（quit 使后续 QTest.qWait 立即返回）。销毁流程：
    1. 显式断开 QApplication 级信号（paletteChanged / focusChanged，
       与 closeEvent Step 0 一致），避免任何外部强引用阻碍析构；
    2. QTest.qWait(600)：等待 MainWindow 构造期的 singleShot(100/500ms)
       定时器触发完毕——它们捕获 self 强引用，而 pytest 测试间隙没有事件
       循环处理定时器，残留窗口会滞留到后续测试的 qWait 才被释放，
       累积的事件循环负载会饿死 10ms 级动画（test_animation_manager
       注册表断言失败的顺序污染根因）。600ms 同时覆盖全部面板动画
       （折叠 300ms / 滑入滑出 250ms）自然结束并清理注册表；
    3. AnimationManager.stop_all() + deleteLater + 轮询自验证：
       兜底停止仍在运行的动画后显式销毁 C++ 窗口。deleteLater 走析构
       不走 closeEvent；DeferredDelete 需真实事件循环交付（processEvents
       不交付，实测）。轮询等待交付完成并断言 sip.isdeleted(w)
       —— 销毁失败在源头响亮报错，而非静默残留到后续测试。
    """
    app_inst = QApplication.instance()
    if app_inst is not None:
        for signal, slot in (
            (app_inst.paletteChanged, w._on_system_palette_changed),
            (app_inst.focusChanged, w._on_focus_changed),
        ):
            try:
                signal.disconnect(slot)
            except (TypeError, RuntimeError):
                pass  # 未连接 / 已失效，跳过
    w.gpu_status.cleanup()
    QTest.qWait(600)
    from app.ui.animation_manager import AnimationManager
    AnimationManager.stop_all()
    w.deleteLater()
    # 自验证（fix round 1）：「无残留窗口」是 teardown 的核心承诺，不能静默假设。
    # 轮询等待 DeferredDelete 交付（固定 qWait 时长在 Qt 交付行为变化时
    # 不可靠；本机 PyQt6 未暴露 QTest.qWaitUntil，用 qWait 轮询等价实现），
    # 超时 → assert 在源头响亮失败，避免窗口泄漏被静默归因到无关的后续
    # 测试（sip.isdeleted：C++ 对象已析构 ⇒ 必然不在
    # QApplication.topLevelWidgets() 中）。
    import time
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline and not sip.isdeleted(w):
        QTest.qWait(20)
    assert sip.isdeleted(w), \
        "fixture 窗口未销毁：deleteLater + 2s 后 C++ 对象仍存活"


class TestMainWindowCreation:
    def test_main_window_creation(self, main_window):
        w = main_window
        assert w is not None
        assert w.windowTitle() == "PDFOCR"
        w_, h_ = w.config["app"]["window_size"]
        assert (w.size().width(), w.size().height()) == (w_, h_)  # 尺寸来自配置
        # FluentWindow 无 QMainWindow.centralWidget；内容区即 stackedWidget
        assert w.stackedWidget is not None
        assert w.navigationInterface is not None

    def test_four_pages_registered(self, main_window):
        """四个子页面（工作区/结果/历史/关键字汇总）均已加入 stackedWidget"""
        w = main_window
        assert w.stackedWidget.count() == 4
        assert w.stackedWidget.currentWidget() is w.template_page

    def test_core_layout_widgets_present(self, main_window):
        """Task 7 单层水平布局关键组件齐备"""
        w = main_window
        assert w.left_panel is not None
        assert w.right_panel is not None
        assert w.workspace is not None
        assert w.file_panel is not None
        assert w.pdf_canvas is not None
        assert w.field_panel is not None
        assert w.toolbar is not None
        # 状态栏为独立 StatusBar 组件（Task 13），非裸 QLabel
        assert isinstance(w.status_bar, StatusBar)
        assert w.status_label is w.status_bar.status_text  # 兼容属性指向内部文本

class TestPanelToggle:
    def test_left_panel_collapse_expand(self, main_window):
        w = main_window
        w.show()  # offscreen：show 后可见性断言才有意义
        assert not w.left_panel.is_collapsed()
        assert w.left_panel.content_area.isVisible()

        w.left_panel.collapse()
        assert w.left_panel.is_collapsed()
        assert not w.left_panel.content_area.isVisible()
        assert w.left_panel.collapsed_indicator.isVisible()

        w.left_panel.expand()
        assert not w.left_panel.is_collapsed()
        assert w.left_panel.content_area.isVisible()
        assert not w.left_panel.collapsed_indicator.isVisible()

    def test_left_panel_toggle_is_idempotent(self, main_window):
        w = main_window
        w.left_panel.collapse()
        w.left_panel.collapse()  # 重复折叠不报错、状态不变
        assert w.left_panel.is_collapsed()
        w.left_panel.expand()
        w.left_panel.expand()
        assert not w.left_panel.is_collapsed()

    def test_right_panel_slide_in_out(self, main_window):
        w = main_window
        assert w.right_panel.is_visible()
        w.right_panel.slide_out()
        assert not w.right_panel.is_visible()
        w.right_panel.slide_in()
        assert w.right_panel.is_visible()

    def test_panel_toggle_shortcut_bound(self, main_window):
        """Ctrl+Shift+L 已绑定 left_panel.toggle：直接发射信号验证接线"""
        w = main_window
        w.left_panel.expand()
        w.findChild(QShortcut, 'Ctrl+Shift+L').activated.emit()
        assert w.left_panel.is_collapsed()
        w.findChild(QShortcut, 'Ctrl+Shift+L').activated.emit()
        assert not w.left_panel.is_collapsed()


class TestThemeSwitching:
    def test_theme_manager_switch(self, qapp):
        ThemeManager.set_theme('dark')
        assert ThemeManager.current_theme() == 'dark'
        ThemeManager.set_theme('light')
        assert ThemeManager.current_theme() == 'light'

    def test_main_window_apply_theme_mode(self, main_window):
        """MainWindow._apply_theme_mode 双轨同步 ThemeManager 与 qfluentwidgets"""
        w = main_window
        w._apply_theme_mode('dark')
        assert ThemeManager.current_theme() == 'dark'
        w._apply_theme_mode('light')
        assert ThemeManager.current_theme() == 'light'

    def test_status_bar_colors_follow_theme(self, main_window):
        """Task 15：状态栏内嵌颜色来自 ThemeManager，主题切换后刷新"""
        w = main_window
        bar = w.status_bar
        w._apply_theme_mode('dark')
        assert ThemeManager.get_color('bg_surface') in bar.styleSheet()
        w._apply_theme_mode('light')
        assert ThemeManager.get_color('bg_surface') in bar.styleSheet()


class TestShortcuts:
    # Task 7：全部 QShortcut 以快捷键字符串为 objectName
    SHORTCUT_NAMES = [
        'Ctrl+O', 'Ctrl+S', 'Ctrl+Return', 'Ctrl+T', 'Delete',
        'Ctrl+Z', 'Ctrl+Y', 'Ctrl+Shift+L', 'Ctrl+Shift+R',
        'Ctrl+Shift+N', 'Space',
    ]

    @pytest.mark.parametrize('shortcut_name', SHORTCUT_NAMES)
    def test_shortcut_binding_exists(self, main_window, shortcut_name):
        assert main_window.findChild(QShortcut, shortcut_name) is not None

    def test_shortcut_objects_unique(self, main_window):
        """每个快捷键字符串只绑定一个 QShortcut（无重复绑定）"""
        for name in self.SHORTCUT_NAMES:
            matches = main_window.findChildren(QShortcut, name)
            assert len(matches) == 1, f"{name} 绑定数量 = {len(matches)}"


class TestFocusTracking:
    """Task 16 接线：StatusBar.set_focus_area 随焦点区域切换（Task 13 遗留）"""

    HINTS = {
        'file_list': 'Ctrl+O 上传 | Delete 移除 | Space 预览',
        'pdf_preview': '左键框选 | 右键平移 | 滚轮缩放',
        'field_panel': 'Ctrl+S 保存 | Delete 删除字段',
        'global': 'Ctrl+Shift+L 文件栏 | Ctrl+Shift+R 字段栏',
    }

    @staticmethod
    def _emit_focus(widget):
        """发射应用级 focusChanged 信号模拟焦点转移

        offscreen 平台无激活窗口，QWidget.setFocus() 静默失效；
        直接发射信号仍走真实接线（_connect_focus_tracking →
        _on_focus_changed → set_focus_area），连接缺失即断言失败。
        """
        QApplication.instance().focusChanged.emit(None, widget)

    def test_focus_in_panels_updates_status_bar_hint(self, main_window):
        w = main_window
        bar = w.status_bar

        # 文件列表（QListWidget 持焦）→ 文件栏提示
        self._emit_focus(w.file_panel.list_widget)
        assert bar.shortcut_hint.text() == self.HINTS['file_list']

        # 画布（QGraphicsView 持焦）→ 画布提示
        self._emit_focus(w.pdf_canvas)
        assert bar.shortcut_hint.text() == self.HINTS['pdf_preview']

        # 字段面板（QTableWidget 持焦）→ 字段提示
        self._emit_focus(w.field_panel.table)
        assert bar.shortcut_hint.text() == self.HINTS['field_panel']

    def test_focus_outside_panels_returns_global(self, main_window):
        w = main_window
        bar = w.status_bar

        self._emit_focus(w.file_panel.list_widget)
        assert bar.shortcut_hint.text() == self.HINTS['file_list']

        # 焦点移到工具栏引擎下拉框（三个面板之外）→ 回到全局提示
        self._emit_focus(w.engine_combo)
        assert bar.shortcut_hint.text() == self.HINTS['global']

        # 焦点丢失（窗口失焦 / 无焦点控件）→ 回到全局提示
        self._emit_focus(None)
        assert bar.shortcut_hint.text() == self.HINTS['global']

    def test_focus_area_hint_differs_by_area(self, main_window):
        """三档面板提示互不相同（断言非恒真）"""
        w = main_window
        bar = w.status_bar
        seen = set()
        for widget, expected in [
            (w.file_panel.list_widget, self.HINTS['file_list']),
            (w.pdf_canvas, self.HINTS['pdf_preview']),
            (w.field_panel.table, self.HINTS['field_panel']),
        ]:
            self._emit_focus(widget)
            text = bar.shortcut_hint.text()
            assert text == expected
            seen.add(text)
        assert len(seen) == 3


class TestUploadRequestedWiring:
    """F-1: FileListPanel 空状态「上传 PDF」操作按钮 → on_upload（Task 8 遗留）"""

    def test_file_panel_upload_requested_triggers_upload_dialog(self, main_window, monkeypatch):
        """发射 upload_requested 后走真实 on_upload 槽：打开文件对话框并加载所选文件

        on_upload 在 connect 时即被绑定，实例级替换无效；用桩替换
        QFileDialog.getOpenFileNames，端到端验证真实槽被调用（不弹真实对话框）。
        """
        w = main_window
        monkeypatch.setattr(
            mw_module.QFileDialog, "getOpenFileNames",
            lambda *args, **kwargs: (["dummy1.pdf", "dummy2.pdf"], ""),
        )
        assert w.file_panel.files == []
        w.file_panel.upload_requested.emit()
        assert w.file_panel.files == ["dummy1.pdf", "dummy2.pdf"]
        assert "已加载 2 个文件" in w.status_label.text()


class TestTemplateNameLabelTheme:
    """F-2: template_name_label 创建点不再硬编码 #0078d4（Task 15 全局约束）

    断言启动路径：构造后（_set_template_name 首次调用在文件加载之后）标签的
    内嵌 QSS 即来自 ThemeManager。不在此处做 _apply_theme_mode 切换断言——
    切换后 qfluentwidgets setTheme 会重排其控件 QSS（FluentWindow 既有行为，
    与 F-2 无关），启动态才是本修复的覆盖范围。
    """

    def test_template_name_label_created_with_theme_manager_primary(self, main_window):
        """启动全程（构造后、文件加载前）标签颜色为 ThemeManager primary，无 #0078d4"""
        w = main_window
        ss = w.template_name_label.styleSheet()
        assert ThemeManager.get_color('primary') in ss
        assert '#0078d4' not in ss


class TestAnimationPrefWiring:
    """F-3: 启动接线仅在 config 显式声明 animations_enabled 时覆盖系统 reduced-motion 检测"""

    @staticmethod
    def _spy_set_enabled(monkeypatch):
        """包裹 AnimationManager.set_enabled：记录调用并委托原实现（classmethod 在
        类属性访问时已绑定，普通函数替换后仍可经 AnimationManager.set_enabled(v) 调用）"""
        import app.ui.animation_manager as anim_module
        original = anim_module.AnimationManager.set_enabled
        calls = []

        def _spy(value):
            calls.append(value)
            return original(value)

        monkeypatch.setattr(anim_module.AnimationManager, "set_enabled", _spy)
        return calls

    def test_no_animations_key_preserves_system_detection(self, qapp, monkeypatch):
        """appearance 节缺失或无 animations_enabled 键 → 不调用 set_enabled，
        保留模块级系统检测结果（模拟系统禁用动画）"""
        import app.ui.animation_manager as anim_module
        from app.ui.animation_manager import AnimationManager
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(mw_module, "get_ocr_engine", lambda config: FakeEngine())
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        # 模拟系统 reduced-motion 检测结果：动画被系统禁用
        monkeypatch.setattr(anim_module.AnimationManager, "_enabled", False)
        calls = self._spy_set_enabled(monkeypatch)

        # appearance 节完全缺失（_make_config 默认形态）
        w1 = mw_module.MainWindow(_make_config())
        assert calls == []
        assert AnimationManager.is_enabled() is False  # 系统检测值原样保留
        _destroy_test_window(w1)

        # appearance 节存在但无 animations_enabled 键
        config = _make_config()
        config["appearance"] = {"theme": "light"}
        w2 = mw_module.MainWindow(config)
        assert calls == []
        assert AnimationManager.is_enabled() is False
        _destroy_test_window(w2)

    def test_animations_key_applied_from_config(self, qapp, monkeypatch):
        """config 显式声明 animations_enabled → 按声明值覆盖（False/True 两分支）"""
        import app.ui.animation_manager as anim_module
        from app.ui.animation_manager import AnimationManager
        from app.ui.widgets.cancel_result_dialog import CancelResultDialog
        monkeypatch.setattr(mw_module, "get_ocr_engine", lambda config: FakeEngine())
        monkeypatch.setattr(CancelResultDialog, "has_pending_task", lambda: False)
        monkeypatch.setattr(anim_module.AnimationManager, "_enabled", True)  # 基线
        calls = self._spy_set_enabled(monkeypatch)

        config_false = _make_config()
        config_false["appearance"] = {"theme": "light", "animations_enabled": False}
        w1 = mw_module.MainWindow(config_false)
        assert calls == [False]
        assert AnimationManager.is_enabled() is False
        _destroy_test_window(w1)

        calls.clear()
        config_true = _make_config()
        config_true["appearance"] = {"theme": "light", "animations_enabled": True}
        w2 = mw_module.MainWindow(config_true)
        assert calls == [True]
        assert AnimationManager.is_enabled() is True
        _destroy_test_window(w2)
