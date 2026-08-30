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


class _RestartFakeEngine(_FakeEngine):
    """apply_config 返回 True（矫正键变化需重启）+ 记录 unload/initialize"""

    def __init__(self):
        super().__init__()
        self.unload_calls = 0
        self.reinit_calls = 0

    def apply_config(self, patch):
        return True

    def unload(self):
        self.unload_calls += 1

    def initialize(self):
        # 窗口构造时 base _start_ocr_init 也会调一次 initialize；仅统计
        # unload 之后的调用（重启触发），unload_calls 由重启路径独占
        if self.unload_calls:
            self.reinit_calls += 1


class _RestartSlowEngine(_SlowFakeEngine):
    """慢引擎 + apply_config 返回 True（运行中需重启场景）"""

    def apply_config(self, patch):
        return True

    def unload(self):
        self.unload_calls = getattr(self, "unload_calls", 0) + 1


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


def _patch_quit_and_dialog(monkeypatch):
    """C1 测试配套：确认弹窗应答 + 屏蔽 base 异步清理的 QApplication.quit()

    base closeEvent 最后的清理线程会调 QApplication.quit()；真实调用会置
    quitNow，导致本测试之后所有 QEventLoop.exec()（_wait_signal 等）立即
    返回 —— 测试会话内必须屏蔽。
    """
    import PyQt6.QtWidgets as qt_widgets
    monkeypatch.setattr(qt_widgets.QApplication, "quit",
                        lambda *a, **k: None)
    return qt_widgets


def _make_2page_pdf(tmp_path, name="doc.pdf"):
    import fitz
    pdf = tmp_path / name
    doc = fitz.open()
    doc.new_page()
    doc.new_page()
    doc.save(str(pdf))
    doc.close()
    return str(pdf)


def test_retry_during_run_keeps_others_queued(qapp, tmp_path, monkeypatch):
    """C2：运行中重试只清目标缓存并重跑目标；其余未处理文件保留在队列，
    续跑完成后全部 3 个文件均完成（不再永久"等待"）"""
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    pdfs = [_make_2page_pdf(tmp_path, f"doc{i}.pdf") for i in range(3)]
    done = []
    win.processor.file_done.connect(lambda p, r: done.append(p))
    win.add_files(pdfs)
    _wait_signal(win.processor, "file_started")  # 首文件开始处理
    target = pdfs[0]
    win.file_panel.select_file(win.file_panel.file_id_by_path(target))
    win._on_retry()  # 运行中重试：pending 全部重入队 + cancel → 续跑重跑整个队列

    _wait_signal(win.processor, "all_done", timeout_ms=15000)
    assert set(done) == set(pdfs)      # 其余文件未被 _clear_run_queue 丢弃
    assert done.count(target) >= 2     # 目标重新处理：首轮部分页 + 续跑完整
    assert 6 <= engine.calls <= 7      # 首轮 0-1 页 + 续跑 6 页（目标重跑在内）
    assert len(win.processor.get_cache(target)) == 2  # 目标缓存为续跑完整结果
    for p in pdfs:
        fid = win.file_panel.file_id_by_path(p)
        assert fid is not None and "完成" in win.file_panel.status_text(fid)


def test_close_event_cancels_processor(qapp, tmp_path, monkeypatch):
    """C1：任务进行中关闭窗口 → 确认弹窗（Yes）→ 处理器被 cancel"""
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    win.add_files([_make_2page_pdf(tmp_path)])
    _wait_signal(win.processor, "file_started")  # 任务运行中（慢引擎 2 页）
    assert win.processor.is_running()

    qt_widgets = _patch_quit_and_dialog(monkeypatch)
    monkeypatch.setattr(
        qt_widgets.QMessageBox, "question",
        lambda *a, **k: qt_widgets.QMessageBox.StandardButton.Yes)

    win.show()
    win.close()

    # cancel 已生效：当前页推理完成后线程停止（轮询等待）
    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


def test_close_event_no_keeps_window(qapp, tmp_path, monkeypatch):
    """C1：任务进行中关闭 → 确认弹窗（No）→ 关闭被 ignore，任务继续"""
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    win.add_files([_make_2page_pdf(tmp_path)])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    qt_widgets = _patch_quit_and_dialog(monkeypatch)
    monkeypatch.setattr(
        qt_widgets.QMessageBox, "question",
        lambda *a, **k: qt_widgets.QMessageBox.StandardButton.No)

    win.show()
    closed = win.close()
    assert not closed                  # 关闭事件被 ignore
    assert win.isVisible()             # 窗口保留
    assert win.processor.is_running()  # 任务未被取消

    # 等任务自然完成，线程停止后窗口可安全回收
    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


def test_select_uncached_file_waits_for_parse(qapp, tmp_path, monkeypatch):
    """手动解析模式：运行中点选未缓存文件 → 不自动入队，仅提示等待解析"""
    engine = _SlowFakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    pdf2 = _make_2page_pdf(tmp_path, "doc2.pdf")
    done = []
    win.processor.file_done.connect(lambda p, r: done.append(p))
    win.add_files([pdf])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    win._on_file_selected(pdf2)  # 点选未缓存文件
    assert pdf2 not in win.processor.pending_items()  # 不自动入队
    assert "等待解析" in win.status_label.text()
    assert "doc2.pdf" in win.file_label.text()

    # 本批结束后 pdf2 从未入队，不会被处理
    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    assert done == [pdf]
    assert win.processor.get_cache(pdf2) is None


def test_select_processing_file_no_rerun(qapp, tmp_path, monkeypatch):
    """手动解析模式：点击正在处理中的文件 → 提示"正在处理中"，不触发重跑"""
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    win._on_file_selected(pdf)  # 正在处理中的文件被点击
    assert "正在处理中" in win.status_label.text()

    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    assert engine.calls == 2  # 恰好处理一遍，未被重跑
    assert win.processor.get_cache(pdf) is not None


def test_parse_button_processes_queued(qapp, tmp_path, monkeypatch):
    """手动解析：queue_files 只添加不启动；点「解析」处理会话等待文件，
    历史分组文件不参与批量解析"""
    engine = _SlowFakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    pdf2 = _make_2page_pdf(tmp_path, "doc2.pdf")
    hist = _make_2page_pdf(tmp_path, "hist.pdf")
    win.file_panel.add_file(hist, history=True)   # 历史分组文件
    win.queue_files([pdf, pdf2])
    assert not win.processor.is_running()           # 只添加，不启动
    assert win.processor.get_cache(pdf) is None
    assert win.processor.get_cache(pdf2) is None

    win._on_parse()
    assert win.processor.is_running()               # 解析按钮启动处理
    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    assert win.processor.get_cache(pdf) is not None
    assert win.processor.get_cache(pdf2) is not None
    assert win.processor.get_cache(hist) is None    # 历史文件未被批量解析

    # 全部完成后再次点解析：无等待文件，不重启处理（先等 worker 线程收尾）
    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    win._on_parse()
    assert not win.processor.is_running()


def test_cancel_during_run_marks_badge_cancelled(qapp, tmp_path, monkeypatch):
    """T8-I1-F：运行中取消 → cancelled 信号 → 进行中文件徽章/状态栏"已取消"
    （worker 先 file_done 写部分页"完成"再 emit cancelled，徽章被覆盖）"""
    engine = _SlowFakeEngine()
    win = _make_window(monkeypatch, engine)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_signal(win.processor, "file_started")
    fid = win.file_panel.file_id_by_path(pdf)
    assert fid is not None

    win.processor.cancel()
    _wait_signal(win.processor, "cancelled", timeout_ms=5000)
    assert "已取消" in win.file_panel.status_text(fid)
    assert "完成" not in win.file_panel.status_text(fid)  # 假完成已被覆盖
    assert "已取消" in win.status_label.text()

    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


def _make_pdf(tmp_path, name="doc.pdf"):
    import fitz
    pdf = tmp_path / name
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Hello")
    doc.save(str(pdf))
    doc.close()
    return str(pdf)


def _count_render_calls(win, monkeypatch):
    """包装 pdf_loader.render_page 计数（spy），返回 calls dict + 原方法"""
    orig = win.pdf_loader.render_page
    calls = {"n": 0}

    def counting_render(pdf_path, page_num=0):
        calls["n"] += 1
        return orig(pdf_path, page_num)

    monkeypatch.setattr(win.pdf_loader, "render_page", counting_render)
    return calls


def test_render_page_cache_hit(qapp, tmp_path, monkeypatch):
    """T9：渲染缓存命中——同一文件同页两次 _render_page → render_page 只调用
    一次；不同页不命中缓存"""
    engine = _FakeEngine()
    win = _make_window(monkeypatch, engine)
    path = _make_pdf(tmp_path)
    calls = _count_render_calls(win, monkeypatch)
    page = PageResult(blocks=[], markdown="Page1")

    win._render_page(path, page, 1)
    win._render_page(path, page, 1)
    assert calls["n"] == 1                      # 缓存命中：同页不再渲染
    assert win._render_cache[path][1] is not None

    win._render_page(path, page, 2)             # 不同页 → 未命中，重新渲染
    assert calls["n"] == 2


def test_render_cache_invalidated_on_reparse(qapp, tmp_path, monkeypatch):
    """T9：重解析后渲染缓存失效——file_done 弹出旧渲染图并重渲染；
    _on_retry 立即失效目标文件缓存"""
    engine = _FakeEngine()
    win = _make_window(monkeypatch, engine)
    path = _make_pdf(tmp_path)
    calls = _count_render_calls(win, monkeypatch)
    page = PageResult(blocks=[], markdown="Page1")
    monkeypatch.setattr(win.processor, "start", lambda: None)  # 不启动后台线程
    win.file_panel.add_file(path)
    win.file_panel.select_file(win.file_panel.file_id_by_path(path))

    win._render_page(path, page, 1)
    win._render_page(path, page, 1)
    assert calls["n"] == 1                      # 命中缓存

    win._on_processor_file_done(path, [page])   # 重解析完成 → 失效 + 重渲染
    assert calls["n"] == 2                      # file_done 弹出缓存后 _show_file 重新渲染
    win._render_page(path, page, 1)
    assert calls["n"] == 2                      # 新缓存命中

    win._on_retry()                             # 重试 → 立即失效（start 已屏蔽，无线程）
    assert path not in win._render_cache


def _wait_cached(win, path, timeout_ms=8000):
    """轮询等待指定文件解析完成（processEvents 驱动信号，避免 QEventLoop
    晚连导致的 5s 空等）"""
    from PyQt6.QtCore import QCoreApplication
    deadline = time.monotonic() + timeout_ms / 1000
    while win.processor.get_cache(path) is None and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    assert win.processor.get_cache(path) is not None


def _make_isolated_window(monkeypatch, engine, tmp_path):
    """构造窗口并把历史文件指向临时路径——_restore_history 默认读用户真实
    历史（~/.pdf_ocr_tool），会把前序测试残留的临时 PDF 路径加进面板，
    污染 paths()/selected_path() 断言"""
    import app.ui.windows.base_window as base_mod
    from app.ui.windows.ocr_main_window import OcrMainWindow
    monkeypatch.setattr(OcrMainWindow, "_history_path",
                        lambda self: str(tmp_path / "hist.json"))
    monkeypatch.setattr(base_mod, "get_ocr_engine", lambda cfg: engine)
    return OcrMainWindow({"app": {"name": "OCR", "window_size": [1200, 800]},
                          "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                          "pdf": {"render_dpi": 100}})


def test_files_cleared_resets_view(qapp, tmp_path, monkeypatch):
    """T10：清空后源文件栏/页码/双视图全部复位，无残留旧状态"""
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_cached(win, pdf)
    win.file_panel.select_file(win.file_panel.file_id_by_path(pdf))
    assert win.file_label.text() != "未选择文件"
    assert win.doc_view.text_browser.toPlainText() != ""

    win._on_files_cleared()  # 空闲清空：无确认弹窗
    assert win.file_label.text() == "未选择文件"
    assert win.page_spin.value() == 1 and win.page_spin.maximum() == 1
    assert win.total_label.text() == "/ 1"
    assert win.doc_view.text_browser.toPlainText() == ""
    assert win.doc_view.canvas.pixmap_item is None
    assert win.json_view.topLevelItemCount() == 0
    assert win.file_panel.paths() == []
    assert win.processor.get_cache(pdf) is None


def test_clear_during_run_asks_confirmation(qapp, tmp_path, monkeypatch):
    """T10：运行中清空 → 确认弹窗；No 保留文件，Yes 清空并复位视图"""
    engine = _SlowFakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    import PyQt6.QtWidgets as qt_widgets
    monkeypatch.setattr(
        qt_widgets.QMessageBox, "question",
        lambda *a, **k: qt_widgets.QMessageBox.StandardButton.No)
    win._on_files_cleared()
    assert win.file_panel.paths() == [pdf]   # No：任务与文件均保留

    monkeypatch.setattr(
        qt_widgets.QMessageBox, "question",
        lambda *a, **k: qt_widgets.QMessageBox.StandardButton.Yes)
    win._on_files_cleared()
    assert win.file_panel.paths() == []      # Yes：清空
    assert win.file_label.text() == "未选择文件"

    deadline = time.monotonic() + 5          # 等线程自然停止，避免跨测试残留
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


def test_select_cached_empty_pages_no_reenqueue(qapp, tmp_path, monkeypatch):
    """T10：0 页缓存（[]）也视为已缓存——点击不反复入队重跑"""
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    monkeypatch.setattr(win.processor, "start", lambda: None)
    # 取消等场景：进行中文件的部分结果可能为空列表，且已写入缓存
    win.processor._cache[pdf] = []

    win._on_file_selected(pdf)
    assert pdf not in win.processor.pending_items()  # 未入队、未重跑
    assert win.processor.get_cache(pdf) == []


def test_copy_warns_when_view_disconnected(qapp, tmp_path, monkeypatch):
    """T10：视图渲染来源与选中文件不一致 → 复制时 InfoBar.warning 提示，
    仍复制当前视图（渲染来源）文本"""
    from qfluentwidgets import InfoBar
    from PyQt6.QtWidgets import QApplication
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf_a = _make_pdf(tmp_path, "a.pdf")
    pdf_b = _make_pdf(tmp_path, "b.pdf")
    page_a = PageResult(blocks=[], markdown="内容 A")
    win._render_page(pdf_a, page_a, 1)           # 视图渲染来源 = A
    monkeypatch.setattr(win.processor, "start", lambda: None)
    win.file_panel.add_file(pdf_b)               # 选中 B（未缓存 → 不渲染）
    win.file_panel.select_file(win.file_panel.file_id_by_path(pdf_b))
    assert win._rendered_path == pdf_a           # 视图仍是 A 的内容

    warns = []
    monkeypatch.setattr(InfoBar, "warning",
                        lambda *a, **k: warns.append(k))
    win._on_copy()
    assert warns and "a.pdf" in warns[0]["content"]  # 脱节提示含视图来源文件名
    assert QApplication.clipboard().text() == "内容 A"  # 复制的是视图文本


def test_remove_file_clears_cache(qapp, tmp_path, monkeypatch):
    """T11：删除单个文件 → file_remove_requested → 窗口清该文件缓存"""
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_cached(win, pdf)
    assert win.processor.get_cache(pdf) is not None

    fid = win.file_panel.file_id_by_path(pdf)
    win.file_panel.remove_file(fid)
    assert pdf not in win.file_panel.paths()
    assert win.processor.get_cache(pdf) is None   # 缓存已清
    assert pdf not in win._render_cache           # 渲染图一并失效


def test_restore_history_marks_queued(qapp, tmp_path, monkeypatch):
    """T11：历史恢复的文件带"点「重试」解析"提示（未自动入队，不参与批量解析）"""
    import json
    engine = _FakeEngine()
    pdf = _make_2page_pdf(tmp_path)
    (tmp_path / "hist.json").write_text(
        json.dumps([{"path": pdf, "time": "2026-01-01T00:00:00"}]),
        encoding="utf-8")
    win = _make_isolated_window(monkeypatch, engine, tmp_path)  # 历史指向 hist.json
    fid = win.file_panel.file_id_by_path(pdf)
    assert fid is not None
    assert "重试" in win.file_panel.status_text(fid)
    assert pdf not in win.processor.pending_items()  # 未入队
    assert pdf not in win.file_panel.queued_paths()  # 不参与「解析」批量处理


def test_cancel_during_run_clears_partial_cache(qapp, tmp_path, monkeypatch):
    """T11：取消路径清理部分页孤儿缓存——file_done 先行写入的部分页在
    cancelled 到达后从缓存清除（清空确认/关闭路径不留孤儿缓存）"""
    engine = _SlowFakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    win.add_files([pdf])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    win.processor.cancel()
    _wait_signal(win.processor, "cancelled", timeout_ms=5000)
    assert win.processor.get_cache(pdf) is None  # 部分页孤儿缓存已清

    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


# ── T13：配置应用——矫正键（构造期参数）变更自动重启引擎 ─────────

def _patch_save_config(monkeypatch):
    """_on_config_apply 写盘保护：重定向到 no-op（save_config 在函数体内
    import，patch config_loader 模块属性即可拦截）"""
    import app.utils.config_loader as cfg_mod
    monkeypatch.setattr(cfg_mod, "save_config", lambda cfg: None)


def _pump_events_until(cond, timeout_ms=3000):
    """泵事件直到条件满足（后台线程信号投递到主线程的收尾等待）"""
    from PyQt6.QtCore import QCoreApplication
    deadline = time.monotonic() + timeout_ms / 1000
    while not cond() and time.monotonic() < deadline:
        QCoreApplication.processEvents()
        time.sleep(0.01)
    return cond()


def test_config_apply_restarts_engine_when_needed(qapp, tmp_path, monkeypatch):
    """T13：apply_config 返回 True → 遮罩 + 后台 unload/initialize →
    完成后信号回主线程 InfoBar 成功提示"""
    _patch_save_config(monkeypatch)
    from qfluentwidgets import InfoBar
    succ = []
    monkeypatch.setattr(InfoBar, "success", lambda *a, **k: succ.append(k))
    engine = _RestartFakeEngine()
    win = _make_window(monkeypatch, engine)
    # 等窗口构造时的初始初始化（后台 OCR-Init 线程）完成，避免其 initialize
    # 与重启路径的 reinit 计数竞态（unload 后才计数的判定会误判）
    assert _pump_events_until(lambda: win._ready_gen == win._init_gen)
    win._on_config_apply({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    # 重启在后台线程执行 → 泵事件等待 unload + reinit + 收尾信号
    ok = _pump_events_until(
        lambda: engine.unload_calls >= 1 and engine.reinit_calls >= 1
        and any("引擎已重启" in s.get("title", "") for s in succ))
    assert ok, f"重启未完成: unload={engine.unload_calls} " \
               f"reinit={engine.reinit_calls} succ={succ}"
    assert engine.unload_calls == 1
    assert engine.reinit_calls == 1
    assert any("引擎已重启" in s.get("title", "") for s in succ)


def test_config_apply_running_skips_restart(qapp, tmp_path, monkeypatch):
    """T13：任务进行中且需重启 → InfoBar.warning 提示稍后重试，跳过重启
    （不 unload——不中断任务）"""
    _patch_save_config(monkeypatch)
    from qfluentwidgets import InfoBar
    warns = []
    monkeypatch.setattr(InfoBar, "warning", lambda *a, **k: warns.append(k))
    engine = _RestartSlowEngine()
    win = _make_window(monkeypatch, engine)
    win.add_files([_make_2page_pdf(tmp_path)])
    _wait_signal(win.processor, "file_started")
    assert win.processor.is_running()

    win._on_config_apply({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    assert warns and "任务进行中" in warns[0]["content"]
    assert getattr(engine, "unload_calls", 0) == 0  # 未触发重启

    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    deadline = time.monotonic() + 5
    while win.processor.is_running() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert not win.processor.is_running()


def test_config_apply_no_restart_hot_path(qapp, tmp_path, monkeypatch):
    """T13：apply_config 返回 False → 热生效路径（成功提示，无重启）"""
    _patch_save_config(monkeypatch)
    from qfluentwidgets import InfoBar
    succ = []
    monkeypatch.setattr(InfoBar, "success", lambda *a, **k: succ.append(k))

    class _NoRestartEngine(_FakeEngine):
        def apply_config(self, patch):
            return False

    engine = _NoRestartEngine()
    win = _make_window(monkeypatch, engine)
    win._on_config_apply({"ocr": {"paddle_vl": {
        "repetition_penalty": 1.5}}})
    assert succ and "配置已应用" in succ[0]["title"]


def test_toolbar_state_context_disabled(qapp, tmp_path, monkeypatch):
    """按钮上下文可用性：无选中禁用重试/复制/导出，无等待禁用解析；
    选中/入队后逐项点亮；空态页码区隐藏，选中缓存文件后出现"""
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    win.show()
    retry_btn, copy_btn, export_btn = win._tool_buttons
    assert not retry_btn.isEnabled()
    assert not copy_btn.isEnabled()
    assert not export_btn.isEnabled()
    assert not win.parse_btn.isEnabled()
    assert not win.page_group.isVisible()          # 空态隐藏页码（防 1/1 误导）

    pdf = _make_2page_pdf(tmp_path)
    win.queue_files([pdf])
    assert win.parse_btn.isEnabled()               # 有等待文件 → 解析可点
    assert not retry_btn.isEnabled()               # 仍未选中文件
    assert not win.page_group.isVisible()

    win.processor.start()
    _wait_signal(win.processor, "all_done", timeout_ms=8000)
    fid = win.file_panel.file_id_by_path(pdf)
    win.file_panel.select_file(fid)                # 选中 → 视图展示
    assert retry_btn.isEnabled()
    assert copy_btn.isEnabled()
    assert export_btn.isEnabled()
    assert win.page_group.isVisible()              # 有页面 → 页码出现
    assert win.page_spin.maximum() == 2

    win.file_panel.clear()
    win._reset_view_after_clear()
    assert not parse_btn_enabled(win)
    assert not win.page_group.isVisible()


def parse_btn_enabled(win):
    return win.parse_btn.isEnabled()


def test_export_dispatch_formats(qapp, tmp_path, monkeypatch):
    """导出格式分发：_do_export 单格式只调对应导出器；None 三格式全调"""
    from app.ui.windows import ocr_main_window as mw
    from PyQt6.QtWidgets import QFileDialog
    engine = _FakeEngine()
    win = _make_isolated_window(monkeypatch, engine, tmp_path)
    pdf = _make_2page_pdf(tmp_path)
    win.processor._cache[pdf] = [PageResult(blocks=[], markdown="x"),
                                 PageResult(blocks=[], markdown="y")]
    win.file_panel.add_file(pdf)
    win.file_panel.select_file(win.file_panel.file_id_by_path(pdf))
    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(tmp_path))
    calls = []
    monkeypatch.setattr(mw, "export_txt",
                        lambda *a: calls.append("txt") or ["a"])
    monkeypatch.setattr(mw, "export_markdown",
                        lambda *a: calls.append("md") or ["a"])
    monkeypatch.setattr(mw, "export_json",
                        lambda *a: calls.append("json") or ["a"])
    win._do_export("txt")
    assert calls == ["txt"]
    calls.clear()
    win._do_export("md")
    assert calls == ["md"]
    calls.clear()
    win._do_export(None)
    assert calls == ["txt", "md", "json"]
