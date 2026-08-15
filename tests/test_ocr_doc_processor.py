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


def _wait_until_events_done(proc, done, expected, timeout_ms=8000):
    """轮询处理事件直到 file_done 达预期次数且线程停止。

    线程最后一批信号（file_done/all_done）在 finished 前 ~10ms 内投递，
    仅等 is_running() 翻转会漏掉这批事件，须同时等待事件计数。
    """
    deadline = time.monotonic() + timeout_ms / 1000
    while (len(done) < expected or proc.is_running()) \
            and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return len(done) >= expected and not proc.is_running()


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


def test_add_during_run_auto_continues(qapp, tmp_path):
    """运行中 add_files 追加的条目在本次运行结束后自动续跑处理"""
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
    proc.add_files([pdf2])  # 运行中追加：不被本次运行结束清掉，自动续跑

    assert _wait_until_events_done(proc, done, expected=2), "续跑未完成"
    assert [p for p, _ in done] == [pdf1, pdf2]  # 续跑自动处理了 pdf2
    assert len(engine.calls) == 4
    loader.shutdown()


def test_corrupted_pdf_fails_file(qapp, tmp_path):
    """损坏 PDF：page_count 吞异常返回 0 → 抛 RuntimeError → file_failed，file_done 不触发"""
    bad_pdf = tmp_path / "broken.pdf"
    bad_pdf.write_bytes(b"this is definitely not a pdf" * 8)  # 垃圾字节 .pdf
    engine = _FakeEngine([PageResult(blocks=[], markdown="p1")])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    failed = []
    done = []
    proc.file_failed.connect(lambda p, e: failed.append((p, e)))
    proc.file_done.connect(lambda p, r: done.append((p, r)))
    proc.add_files([str(bad_pdf)])
    _run_until_done(proc)

    assert len(failed) == 1
    assert failed[0][0] == str(bad_pdf)
    assert "无有效页" in failed[0][1]
    assert not done                # 不再伪装成"完成 0 页"
    assert engine.calls == []      # 损坏文件不触发任何识别
    assert proc.get_cache(str(bad_pdf)) is None
    loader.shutdown()


def test_clear_cache_scoped(qapp, tmp_path):
    """clear_cache(path) 只清指定文件缓存；clear_cache() 清全部"""
    pdf1 = _make_2page_pdf(tmp_path, "a.pdf")
    pdf2 = _make_2page_pdf(tmp_path, "b.pdf")
    engine = _FakeEngine([PageResult(blocks=[], markdown="p1"),
                          PageResult(blocks=[], markdown="p2"),
                          PageResult(blocks=[], markdown="p3"),
                          PageResult(blocks=[], markdown="p4")])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    proc.add_files([pdf1, pdf2])
    _run_until_done(proc)
    assert proc.get_cache(pdf1) is not None
    assert proc.get_cache(pdf2) is not None

    proc.clear_cache(pdf1)
    assert proc.get_cache(pdf1) is None    # 目标缓存被清
    assert proc.get_cache(pdf2) is not None  # 其他文件缓存保留

    proc.clear_cache()
    assert proc.get_cache(pdf2) is None    # 无参清全部
    loader.shutdown()


def test_pending_items_during_run(qapp, tmp_path):
    """运行中 pending_items() 返回取消后仍应处理的全部文件（含未完成项与
    队列全部条目）；按 _on_retry 序列重入队 + 取消后这些文件都被处理完成"""
    pdfs = [_make_2page_pdf(tmp_path, f"doc{i}.pdf") for i in range(3)]
    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    done = []
    proc.file_done.connect(lambda p, r: done.append(p))
    proc.add_files(pdfs)

    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    assert set(proc.pending_items()) == set(pdfs)  # 运行中全部条目均为待处理

    # 与窗口 _on_retry 运行分支相同的序列：pending 全部重入队（目标在内）再取消
    target = pdfs[0]
    proc.clear_cache(target)
    others = [p for p in proc.pending_items() if p != target]
    proc.add_files(others)
    proc.add_files([target])
    proc.cancel()

    # 首轮进行中文件部分页 file_done 1 次 + 续跑 3 次 = 4 次
    assert _wait_until_events_done(proc, done, expected=4), "续跑未完成"
    assert set(done) == set(pdfs)                 # 其余文件未被丢弃
    assert all(proc.get_cache(p) is not None for p in pdfs)
    loader.shutdown()


def test_retry_during_run_restarts_target(qapp, tmp_path):
    """运行中重试（cancel + add_files 同一文件）：取消后自动续跑重新完整处理"""
    pdf_path = _make_2page_pdf(tmp_path)
    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    done = []
    proc.file_done.connect(lambda p, r: done.append((p, r)))
    proc.add_files([pdf_path])

    # 等 worker 真正开始处理文件后再模拟重试（cancel + 重新入队同一文件）
    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    proc.cancel()
    proc.add_files([pdf_path])  # 与窗口 _on_retry 运行分支相同的调用序列

    # 首次运行以 cancelled 收尾（file_done 部分页），续跑以 all_done 收尾
    assert _wait_until_events_done(proc, done, expected=2), "续跑未完成"

    assert len(done) == 2                        # 首次（0-2 页）+ 续跑（完整）
    assert len(done[-1][1]) == 2                 # 续跑结果完整 2 页
    assert 2 <= len(engine.calls) <= 4           # 首次 0-2 页 + 续跑 2 页
    assert len(proc.get_cache(pdf_path)) == 2    # 缓存为续跑完整结果
    loader.shutdown()


def test_shutdown_stops_and_never_restarts(qapp, tmp_path):
    """C3：运行中 shutdown（运行中已追加文件 → 队列非空）→ 线程停止后
    不再续跑：cancelled 触发、引擎调用计数在停止后不再增长"""
    pdf1 = _make_2page_pdf(tmp_path)
    pdf2 = tmp_path / "doc2.pdf"
    shutil.copy(pdf1, pdf2)
    pdf2 = str(pdf2)

    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    cancelled = []
    done = []
    proc.file_done.connect(lambda p, r: done.append((p, r)))
    proc.cancelled.connect(lambda: cancelled.append(1))
    proc.add_files([pdf1])

    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    proc.add_files([pdf2])   # 运行中追加：关闭瞬间队列非空（C3 竞态前提）
    proc.shutdown()          # cancel + clear_queue + 置位

    assert _wait_until(proc, "cancelled", timeout_ms=5000), "cancelled 未触发"
    assert _wait_not_running(proc), "线程未在超时内停止"
    assert cancelled
    calls_after_stop = len(engine.calls)

    # 越过原续跑窗口（_SlowEngine 每页 0.15s）：若续跑发生，调用计数会继续增长
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    assert len(engine.calls) == calls_after_stop  # 不再续跑：引擎调用冻结
    assert not proc.is_running()
    assert proc.pending_items() == []             # 队列与运行快照均已清空
    loader.shutdown()


def test_start_after_shutdown_is_noop(qapp, tmp_path):
    """C3：shutdown 后即使重新入队，start() 也为 no-op（防御）"""
    pdf_path = _make_2page_pdf(tmp_path)
    engine = _SlowEngine()
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    proc.add_files([pdf_path])
    proc.start()
    assert _wait_until(proc, "file_started"), "file_started 未触发"
    proc.shutdown()
    assert _wait_not_running(proc), "线程未在超时内停止"
    calls_after_shutdown = len(engine.calls)

    proc.add_files([pdf_path])   # 模拟关闭后仍有调用方尝试入队启动
    proc.start()                 # 防御：_shutting_down 置位后直接返回
    deadline = time.monotonic() + 0.6
    while time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.05)
    assert not proc.is_running()
    assert len(engine.calls) == calls_after_shutdown  # 未启动新线程
    loader.shutdown()
