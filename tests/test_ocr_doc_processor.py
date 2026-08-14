"""OcrDocProcessor 批量处理（fake 引擎，PyQt6 QThread 信号测试）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.ocr_doc_processor import OcrDocProcessor, is_image_file
from app.core.pdf_loader import PdfLoader
from app.models.page_result import PageResult


class _FakeEngine:
    def __init__(self, results):
        self.results = results  # path -> List[PageResult]
        self.calls = []

    def recognize_page_auto(self, image):
        self.calls.append(image.size)
        return self.results.pop(0)


@pytest.fixture
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


def _run_until_done(proc, timeout_ms=3000):
    loop = QEventLoop()
    done = []
    proc.all_done.connect(lambda: (done.append(1), loop.quit()))
    proc.file_failed.connect(lambda p, e: (done.append(("err", p, e)), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    proc.start()
    loop.exec()
    return done


def test_is_image_file():
    assert is_image_file("a.png") and is_image_file("b.JPG")
    assert not is_image_file("a.pdf")


def test_process_pdf_in_order(qapp, tmp_path):
    from PyQt6.QtGui import QImage, QPixmap  # noqa
    pdf = tmp_path / "doc.pdf"
    import fitz
    doc = fitz.open()
    for _ in range(2):
        pg = doc.new_page()
        pg.insert_text((72, 72), "Hello")
    doc.save(str(pdf))
    doc.close()

    engine = _FakeEngine([PageResult(blocks=[], markdown="p1"),
                          PageResult(blocks=[], markdown="p2")])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    results = {}
    proc.file_done.connect(lambda p, r: results.update({p: r}))
    proc.add_files([str(pdf)])
    _run_until_done(proc)
    assert len(results[str(pdf)]) == 2
    assert results[str(pdf)][0].markdown == "p1"
    loader.shutdown()


def test_cancel_stops_queue(qapp):
    engine = _FakeEngine([])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    cancelled = []
    proc.cancelled.connect(lambda: cancelled.append(1))
    proc.add_files(["x.pdf"])
    proc.cancel()  # 未开始即取消
    assert proc.is_running() is False
    loader.shutdown()
