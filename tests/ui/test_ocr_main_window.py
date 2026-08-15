"""OcrMainWindow 测试（offscreen，fake 引擎）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication

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
