"""OcrDocProcessor 批量处理（fake 引擎，PyQt6 QThread 信号测试）"""
import shutil
import sys
import time
from pathlib import Path
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.ocr_doc_processor import OcrDocProcessor, is_image_file
from app.core.pdf_loader import PdfLoader
from app.models.page_result import PageResult


def _make_2page_pdf(tmp_path, name="doc.pdf"):
    """构造一个 2 页 PDF，返回路径字符串"""
    pdf = tmp_path / name
    import fitz
    doc = fitz.open()
    for _ in range(2):
        pg = doc.new_page()
        pg.insert_text((72, 72), "Hello")
    doc.save(str(pdf))
    doc.close()
    return str(pdf)


class _FakeEngine:
    """按预设结果队列逐页返回；calls 记录每次识别调用的图像尺寸"""

    def __init__(self, results):
        self.results = results
        self.calls = []

    def recognize_page_auto(self, image):
        self.calls.append(image.size)
        return self.results.pop(0)


class _FailingEngine:
    """第 1 页抛异常、第 2 页正常——验证单页失败不中断文件"""

    def __init__(self):
        self.calls = []

    def recognize_page_auto(self, image):
        self.calls.append(image.size)
        if len(self.calls) == 1:
            raise RuntimeError("engine boom")
        return PageResult(blocks=[], markdown="p2")


class _SlowEngine:
    """每次识别前 sleep，给 cancel / 运行中 add_files 留出窗口"""

    def __init__(self):
        self.calls = []

    def recognize_page_auto(self, image):
        self.calls.append(image.size)
        time.sleep(0.15)
        return PageResult(blocks=[], markdown=f"p{len(self.calls)}")


def _wait_until(proc, signal_name, timeout_ms=3000):
    """运行 QEventLoop 直到信号触发（或超时），返回是否触发"""
    loop = QEventLoop()
    fired = []
    getattr(proc, signal_name).connect(lambda: (fired.append(1), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    loop.exec()
    return bool(fired)


def _wait_not_running(proc, timeout_ms=2000):
    """轮询直到线程彻底停止（finished → deleteLater 落定），返回是否停止"""
    deadline = time.monotonic() + timeout_ms / 1000
    while proc.is_running() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return not proc.is_running()


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
    pdf_path = _make_2page_pdf(tmp_path)
    engine = _FakeEngine([PageResult(blocks=[], markdown="p1"),
                          PageResult(blocks=[], markdown="p2")])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    results = {}
    proc.file_done.connect(lambda p, r: results.update({p: r}))
    proc.add_files([pdf_path])
    _run_until_done(proc)
    assert len(results[pdf_path]) == 2
    assert results[pdf_path][0].markdown == "p1"
    loader.shutdown()


def test_single_page_failure_continues(qapp, tmp_path):
    """第 1 页识别失败 → 占位页计入结果，第 2 页正常，file_done 页数 == 总页数"""
    pdf_path = _make_2page_pdf(tmp_path)
    engine = _FailingEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    results = {}
    proc.file_done.connect(lambda p, r: results.update({p: r}))
    proc.add_files([pdf_path])
    _run_until_done(proc)
    pages = results[pdf_path]
    assert len(pages) == 2            # 失败页占位不中断文件
    assert pages[0].markdown == ""    # 失败页占位 markdown 为空
    assert pages[0].image_size == engine.calls[0]  # 占位保留渲染图像尺寸
    assert pages[1].markdown == "p2"  # 后续页正常识别
    loader.shutdown()


def test_cancel_stops_queue(qapp, tmp_path):
    """运行中取消：cancelled 触发、已解析页经 file_done 保留、剩余页不再识别"""
    pdf_path = _make_2page_pdf(tmp_path)
    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    cancelled = []
    done_pages = {}
    proc.file_done.connect(lambda p, r: done_pages.update({p: r}))
    proc.cancelled.connect(lambda: cancelled.append(1))
    proc.add_files([pdf_path])

    # 等 worker 真正开始处理文件（file_started 落定）后再取消，保证命中进行中状态
    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    proc.cancel()

    assert _wait_until(proc, "cancelled", timeout_ms=5000), "cancelled 未触发"
    assert _wait_not_running(proc), "线程未在超时内停止"

    assert cancelled                      # cancelled 已触发
    assert len(engine.calls) < 2          # 取消生效：未识别完全部页
    assert len(done_pages) == 1           # 进行中文件经 file_done 保留（先写缓存再发信号）
    assert len(done_pages[pdf_path]) == len(engine.calls)  # 部分页 == 已识别页
    assert proc.is_running() is False     # 线程最终停止
    loader.shutdown()


def test_add_during_run_kept_for_next_start(qapp, tmp_path):
    """运行中 add_files 追加的条目在本次运行结束后保留，可再次 start 处理"""
    pdf1 = _make_2page_pdf(tmp_path)
    pdf2 = tmp_path / "doc2.pdf"
    shutil.copy(pdf1, pdf2)
    pdf2 = str(pdf2)

    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    done = []
    proc.file_done.connect(lambda p, r: done.append((p, r)))
    proc.add_files([pdf1])

    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    proc.add_files([pdf2])  # 运行中追加：不应被本次运行结束清掉

    assert _wait_until(proc, "all_done"), "第一次运行未结束"
    assert _wait_not_running(proc), "线程未在超时内停止"
    assert [p for p, _ in done] == [pdf1]        # 本次运行只处理了 pdf1
    assert len(engine.calls) == 2

    _run_until_done(proc)                        # 第二次 start 处理追加的 pdf2
    assert [p for p, _ in done] == [pdf1, pdf2]
    assert len(engine.calls) == 4
    loader.shutdown()
