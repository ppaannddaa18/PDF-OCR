"""P1 双向高亮：字段行 -> 画布高亮居中；画布点击行盒 -> 右侧选中字段行

说明：不构造完整真实 OCR 引擎（避免加载模型/启动 llama-server），
通过 monkeypatch get_ocr_engine 注入 FakeEngine（与 test_main_window_new_template 一致）。
"""
import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

from app.ui import main_window as mw_module
from app.models.page_result import PageResult, StructuredResult, StructuredField


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
        "structured": {"detection": False},
    }


@pytest.fixture
def main_window(qapp, monkeypatch):
    monkeypatch.setattr(mw_module, "get_ocr_engine", lambda config: FakeEngine())
    w = mw_module.MainWindow(_make_config())
    yield w
    # 不调用 w.close()：closeEvent 最终会 QApplication.quit()，
    # 影响 tests/ui 共享的 qapp 单例；仅停掉 GPU 状态定时器
    w.gpu_status.cleanup()
    # deleteLater 立即销毁实例（不触发 closeEvent），避免 7 个 MainWindow
    # 残留至进程结束，降低全量套件下事件循环负载（collapsible 动画 flaky 相关）
    w.deleteLater()
    QApplication.processEvents()


def _make_result():
    """两个带 bbox 的字段 + 一个无 bbox 字段（检测关闭时 bbox 为 None 的形态）"""
    fields = [
        StructuredField(label="报关单号", value="090820241000039736",
                        status="pending", bbox=[10, 10, 110, 30]),
        StructuredField(label="境内收货人", value="91330333",
                        status="pending", bbox=[10, 40, 120, 60]),
        StructuredField(label="备注", value="", status="not_found", bbox=None),
    ]
    return PageResult(blocks=[], markdown="", structured=StructuredResult(fields=fields))


def _load_canvas_image(w):
    """给画布加载一张图（场景坐标需要图像上下文）"""
    w.pdf_canvas.load_image(Image.new("RGB", (300, 200), "white"))


class TestResultFieldToCanvas:
    """结果→画布：字段行点击 -> 高亮对应原文区域并居中"""

    def test_field_selected_highlights_bbox_and_centers(self, main_window):
        w = main_window
        w._current_page_result = _make_result()
        _load_canvas_image(w)
        w._on_result_field_selected(0)
        assert len(w.pdf_canvas._highlight_items) == 1
        _, bbox = w.pdf_canvas._highlight_items[0]
        assert bbox == [10, 10, 110, 30]

    def test_field_without_bbox_clears_highlights(self, main_window):
        w = main_window
        w._current_page_result = _make_result()
        _load_canvas_image(w)
        w.pdf_canvas.highlight_bbox([0, 0, 50, 50])
        w._on_result_field_selected(2)  # 备注 bbox=None → 降级为清高亮
        assert w.pdf_canvas._highlight_items == []

    def test_out_of_range_row_is_noop(self, main_window):
        w = main_window
        w._current_page_result = _make_result()
        w._on_result_field_selected(99)  # 不崩溃、无高亮
        assert w.pdf_canvas._highlight_items == []

    def test_no_result_noop(self, main_window):
        w = main_window
        w._current_page_result = None
        w._on_result_field_selected(0)  # 不崩溃
        assert w.pdf_canvas._highlight_items == []


class TestCanvasClickToResult:
    """画布→结果：点击行盒 -> 右侧选中对应字段行（中心包含判定）"""

    def test_bbox_clicked_selects_matching_row(self, main_window):
        w = main_window
        w._current_page_result = _make_result()
        w._result_panel.load_result(w._current_page_result)
        # 点击落入字段1（bbox [10,40,120,60]）内部
        w._on_canvas_bbox_clicked([60, 45, 70, 55])
        assert w._result_panel._field_table.currentRow() == 1

    def test_click_outside_all_bboxes_noop(self, main_window):
        w = main_window
        w._current_page_result = _make_result()
        w._result_panel.load_result(w._current_page_result)
        w._on_canvas_bbox_clicked([500, 500, 510, 510])
        assert w._result_panel._field_table.currentRow() == -1

    def test_no_result_noop(self, main_window):
        w = main_window
        w._current_page_result = None
        w._on_canvas_bbox_clicked([60, 45, 70, 55])  # 不崩溃
        assert w._result_panel._field_table.currentRow() == -1


class TestReviewFixes:
    """最终评审修复回归：高亮不累积 / 检测初始化不冻结主线程 / 预处理清旧结果"""

    def test_consecutive_field_clicks_do_not_stack_highlights(self, main_window):
        """连续点击两个字段行：只保留当前选中，不叠加累积（评审 Important #3）"""
        w = main_window
        w._current_page_result = _make_result()
        _load_canvas_image(w)
        w._on_result_field_selected(0)
        w._on_result_field_selected(1)
        assert len(w.pdf_canvas._highlight_items) == 1
        _, bbox = w.pdf_canvas._highlight_items[0]
        assert bbox == [10, 40, 120, 60]  # 字段1（境内收货人）

    def test_detection_fn_never_initializes_on_main_thread(self, main_window, monkeypatch):
        """检测函数只返回引擎方法，模型初始化必须留在 worker 线程（评审 Important #1）"""
        w = main_window
        w.config["structured"]["detection"] = True
        calls = []

        class FakeRapid:
            def __init__(self, *a, **k):
                self.detect_lines = "detect_lines_fn"

            def initialize(self):
                calls.append("initialize")

        monkeypatch.setattr("app.core.ocr_engine_rapid.RapidOCREngine", FakeRapid)
        fn = w._get_detection_fn()
        assert fn == "detect_lines_fn"
        assert calls == []  # 主线程绝不同步加载 ONNX 模型

    def test_detection_fn_disabled_returns_none(self, main_window):
        """默认 structured.detection: false → 不启用检测层"""
        w = main_window
        assert w._get_detection_fn() is None

    def test_preprocess_change_clears_stale_result(self, main_window):
        """预处理变更后旧解析结果与旧 bbox 必须清除（评审 Important #2）"""
        w = main_window
        w._current_page_result = _make_result()
        _load_canvas_image(w)
        w.pdf_canvas.highlight_bbox([10, 10, 110, 30])

        class FakeToolbar:
            def get_params(self):
                return {}

        class FakePreprocessor:
            def set_params(self, params):
                pass

            def get_current_image(self):
                return Image.new("RGB", (200, 150), "white")

        w.preprocess_toolbar = FakeToolbar()
        w._current_preprocessor = FakePreprocessor()
        w._on_preprocess_changed()
        assert w._current_page_result is None
        assert w.pdf_canvas._highlight_items == []
