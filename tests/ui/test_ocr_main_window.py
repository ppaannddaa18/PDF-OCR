"""OcrMainWindow 测试（offscreen，fake 引擎）"""
import sys
import time
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ui.windows.ocr_main_window import OcrMainWindow
from app.models.page_result import PageResult


class _FakeEngine:
    def __init__(self):
        self.results = [PageResult(blocks=[], markdown="Page1"),
                        PageResult(blocks=[], markdown="Page2")]

    def recognize_page_auto(self, image):
        return self.results.pop(0)

    def initialize(self):
        pass

    @property
    def is_ready(self):
        return True

    @property
    def engine_name(self):
        return "paddle_vl"

    @property
    def init_error(self):
        return ""


class _SlowFakeEngine(_FakeEngine):
    """每次识别前 sleep，给运行中重试留出窗口；calls 记录识别次数"""

    def __init__(self):
        self.calls = 0

    def recognize_page_auto(self, image):
        self.calls += 1
        time.sleep(0.15)
        return PageResult(blocks=[], markdown=f"p{self.calls}")


# 注意：不在此处定义本地 qapp fixture —— tests/ui/conftest.py 提供 session
# 级 qapp；本地函数级 fixture 会遮蔽它，导致测试结束时 QApplication 被 GC、
# qfluentwidgets 全局 qconfig（QApplication 之前创建的 QObject）随之销毁，
# 下一个窗口构造时崩溃（RuntimeError: QConfig has been deleted）


def test_window_constructs(qapp, tmp_path, monkeypatch):
    # 引擎工厂在 base_window._post_init_base 中解析（该模块命名空间），
    # 与 test_gguf_window.py 相同的 monkeypatch 目标
    import app.ui.windows.base_window as base_mod
    monkeypatch.setattr(base_mod, "get_ocr_engine", lambda cfg: _FakeEngine())
    win = OcrMainWindow({"app": {"name": "OCR 识别", "window_size": [1200, 800]},
                         "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                         "pdf": {"render_dpi": 100}})
    win.show()
    assert win.windowTitle() == "OCR 识别"


def test_add_file_and_parse(qapp, tmp_path, monkeypatch):
    import fitz
    import app.ui.windows.base_window as base_mod
    monkeypatch.setattr(base_mod, "get_ocr_engine", lambda cfg: _FakeEngine())
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "Hello")
    doc.new_page()  # 第二页：与 _FakeEngine 双结果对应
    doc.save(str(pdf))
    doc.close()
    win = OcrMainWindow({"app": {"name": "OCR", "window_size": [1200, 800]},
                         "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                         "pdf": {"render_dpi": 100}})
    win.add_files([str(pdf)])
    # 等待处理完成（QEventLoop + all_done）
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    win.processor.all_done.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert win.processor.get_cache(str(pdf)) is not None
    assert len(win.processor.get_cache(str(pdf))) == 2


def _make_window(monkeypatch, engine):
    """构造窗口并 monkeypatch 引擎工厂"""
    import app.ui.windows.base_window as base_mod
    monkeypatch.setattr(base_mod, "get_ocr_engine", lambda cfg: engine)
    return OcrMainWindow({"app": {"name": "OCR", "window_size": [1200, 800]},
                          "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                          "pdf": {"render_dpi": 100}})


def _wait_signal(processor, signal_name, timeout_ms=5000):
    """运行 QEventLoop 直到信号触发（或超时）"""
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    getattr(processor, signal_name).connect(loop.quit)
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()


def test_retry_during_run_reprocesses(qapp, tmp_path, monkeypatch):
    """I1：运行中点击重试 → cancel + 重新入队 → 自动续跑完整重新处理该文件"""
    import fitz
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()

    win.add_files([str(pdf)])
    _wait_signal(win.processor, "file_started")
    fid = win.file_panel.file_id_by_path(str(pdf))
    win.file_panel.select_file(fid)  # 选中后 _on_retry 才有目标
    win._on_retry()  # 运行中重试：cancel + add_files，续跑自动重跑

    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    pages = win.processor.get_cache(str(pdf))
    assert pages is not None and len(pages) == 2   # 续跑结果为完整 2 页
    assert 2 <= engine.calls <= 4                  # 首次 0-2 页 + 续跑 2 页
    assert "完成" in win.file_panel.status_text(fid)


def test_file_failed_badge(qapp, tmp_path, monkeypatch):
    """M1：引擎/加载失败 → file_failed → 文件徽章更新为失败"""
    engine = _FakeEngine()
    win = _make_window(monkeypatch, engine)
    bad = tmp_path / "bad.png"
    bad.write_bytes(b"not an image at all")  # 图片解码失败 → 文件级失败

    win.add_files([str(bad)])
    _wait_signal(win.processor, "file_failed", timeout_ms=8000)
    fid = win.file_panel.file_id_by_path(str(bad))
    assert fid is not None
    assert "失败" in win.file_panel.status_text(fid)
