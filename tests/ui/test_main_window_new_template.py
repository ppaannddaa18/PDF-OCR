"""Task 7 修复 I-1 回归测试：新建模板需持久化空配置 + 清空默认模板

背景：_on_new_template (Ctrl+Shift+N) 最初只清 UI 状态，导致切换文件再切回时
旧区域/默认模板静默复活。修复后应与 on_clear_current_pdf_fields 一致：
- 清空 _default_template
- 为当前 PDF 写入空覆盖配置占位 Template(name="empty", regions=[])

说明：不构造完整真实 OCR 引擎（避免加载模型/启动 llama-server 子进程），
通过 monkeypatch get_ocr_engine 注入 FakeEngine。
"""
import pytest

from app.ui import main_window as mw_module
from app.models.template import Template


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
    w = mw_module.MainWindow(_make_config())
    yield w
    # 不调用 w.close()：closeEvent 最终会 QApplication.quit()，
    # 影响 tests/ui 共享的 qapp 单例；仅停掉 GPU 状态定时器
    w.gpu_status.cleanup()


class TestNewTemplatePersistence:
    def test_new_template_persists_empty_override_and_clears_default(self, main_window):
        """新建模板必须清空默认模板，并为当前 PDF 写入空覆盖配置占位"""
        w = main_window
        w._default_template = Template(name="default", regions=[])
        w._current_pdf = "dummy.pdf"
        w._pdf_overrides.clear()

        w._on_new_template()

        # 默认模板被清空，旧默认配置不会静默复活
        assert w._default_template is None
        # 当前 PDF 写入空覆盖配置占位（切换文件再切回时不会恢复旧区域）
        assert w._current_pdf in w._pdf_overrides
        override = w._pdf_overrides[w._current_pdf]
        assert override.name == "empty"
        assert override.regions == []

    def test_new_template_without_current_pdf(self, main_window):
        """无当前 PDF 时不应写入覆盖配置（不崩溃）"""
        w = main_window
        w._current_pdf = None
        w._pdf_overrides.clear()
        w._default_template = Template(name="default", regions=[])

        w._on_new_template()

        assert w._default_template is None
        assert w._pdf_overrides == {}

    def test_new_template_effective_template_stays_empty_after_switch_back(self, main_window):
        """切换文件再切回后，有效模板仍为空（修复的核心行为）"""
        w = main_window
        # 场景：先有默认模板，当前 PDF 为其配置了区域
        w._default_template = Template(name="default", regions=[])
        w._current_pdf = "a.pdf"
        w._pdf_overrides.clear()

        w._on_new_template()
        # 切到另一个文件（无覆盖配置 → 走默认模板路径）
        w._current_pdf = "b.pdf"
        assert w._get_effective_template("b.pdf") is None  # 默认模板已清空
        # 切回 a.pdf → 命中的是空覆盖配置，而不是被遗忘的旧配置
        w._current_pdf = "a.pdf"
        effective = w._get_effective_template("a.pdf")
        assert effective is not None
        assert effective.regions == []
