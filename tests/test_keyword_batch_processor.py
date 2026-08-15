from PIL import Image

from app.core.keyword_batch_processor import KeywordBatchProcessor
from app.models.page_result import PageResult


class FakeGGUFEngine:
    """仅 GGUF 路径（用户决策）；recognize_page_auto 返回固定 markdown"""
    engine_name = "gguf"

    def __init__(self, markdown="报关单号：090820241000039736 价税合计：100.00"):
        self.markdown = markdown

    def recognize_page_auto(self, image):
        return PageResult(blocks=[], markdown=self.markdown)


class FakeLoader:
    def __init__(self, page_counts, fail_render=()):
        self.page_counts = page_counts
        self.fail_render = set(fail_render)  # {(path, page_num0)}

    def page_count(self, path):
        return self.page_counts.get(path, 0)

    def render_page(self, path, page_num):
        if (path, page_num) in self.fail_render:
            raise RuntimeError("render fail")
        return Image.new("RGB", (200, 100), "white")


def _proc(loader=None, engine=None):
    return KeywordBatchProcessor(loader or FakeLoader({"a.pdf": 1}),
                                 engine or FakeGGUFEngine(), max_workers=2)


def test_two_files_each_extracted():
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1})
    results = _proc(loader).process_batch(["a.pdf", "b.pdf"], ["报关单号", "价税合计"])
    assert len(results) == 2
    for fr in results:
        assert fr.success is True
        assert len(fr.pages) == 1
        assert fr.pages[0].cells["报关单号"].status == "confirmed"
        assert fr.pages[0].cells["价税合计"].value == "100.00"


def test_multi_page_one_row_per_page():
    loader = FakeLoader({"m.pdf": 3})
    results = _proc(loader).process_batch(["m.pdf"], ["报关单号"])
    fr = results[0]
    assert [p.page_no for p in fr.pages] == [1, 2, 3]


def test_progress_cb_receives_total():
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1, "c.pdf": 1})
    seen = []
    _proc(loader).process_batch(["a.pdf", "b.pdf", "c.pdf"], ["x"],
                                progress_cb=lambda d, t, f: seen.append((d, t)))
    assert len(seen) == 3
    assert seen[-1] == (3, 3)


def test_single_page_render_failure_continues():
    loader = FakeLoader({"a.pdf": 2}, fail_render={("a.pdf", 0)})  # 第 1 页（0-based 0）失败
    results = _proc(loader).process_batch(["a.pdf"], ["报关单号"])
    fr = results[0]
    assert fr.pages[0].success is False
    assert fr.pages[1].success is True
    assert fr.success is True  # 有成功页


def test_all_pages_fail_marks_file_failed():
    loader = FakeLoader({"bad.pdf": 2},
                        fail_render={("bad.pdf", 0), ("bad.pdf", 1)})
    results = _proc(loader).process_batch(["bad.pdf"], ["报关单号"])
    assert results[0].success is False


def test_unopenable_file_failed():
    loader = FakeLoader({})  # page_count 返回 0
    results = _proc(loader).process_batch(["gone.pdf"], ["x"])
    fr = results[0]
    assert fr.success is False
    assert fr.error_msg


def test_ocr_exception_page_failed_not_crash():
    class BoomEngine:
        engine_name = "gguf"

        def recognize_page_auto(self, image):
            raise RuntimeError("ocr boom")

    results = _proc(engine=BoomEngine()).process_batch(["a.pdf"], ["x"])
    assert results[0].pages[0].success is False
    assert "ocr boom" in results[0].pages[0].error_msg


def test_cancel_raises_interrupted():
    """worker 的 throttled_cb 抛 InterruptedError 应向上传播（与 BatchWorker 同模式）"""
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1})
    import pytest as _pytest

    def cb(done, total, current):
        raise InterruptedError("用户取消")

    with _pytest.raises(InterruptedError):
        _proc(loader).process_batch(["a.pdf", "b.pdf"], ["x"], progress_cb=cb)


# ── batch.retry_times 接线（设置页参数此前无消费者） ─────────────

class FlakyEngine:
    """前 fail_times 次调用抛异常，之后返回固定 markdown"""
    engine_name = "gguf"

    def __init__(self, fail_times=1, markdown="报关单号：090820241000039736"):
        self.fail_times = fail_times
        self.calls = 0
        self.markdown = markdown

    def recognize_page_auto(self, image):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("ocr transient fail")
        return PageResult(blocks=[], markdown=self.markdown)


def _proc_with_retry(engine, retry_times):
    return KeywordBatchProcessor(FakeLoader({"a.pdf": 1}), engine,
                                 config={"batch": {"retry_times": retry_times}})


def test_retry_succeeds_after_transient_failure():
    """偶发失败（第 1 次抛异常）→ 重试后成功，页结果为成功"""
    engine = FlakyEngine(fail_times=1)
    results = _proc_with_retry(engine, retry_times=2).process_batch(
        ["a.pdf"], ["报关单号"])
    assert engine.calls == 2
    assert results[0].pages[0].success is True
    assert results[0].pages[0].cells["报关单号"].status == "confirmed"


def test_retry_exhausted_marks_page_failed():
    """恒失败 → 调用次数 = retry_times + 1，页标记失败并保留错误"""
    engine = FlakyEngine(fail_times=999)
    results = _proc_with_retry(engine, retry_times=2).process_batch(
        ["a.pdf"], ["报关单号"])
    assert engine.calls == 3
    assert results[0].pages[0].success is False
    assert "transient fail" in results[0].pages[0].error_msg


def test_retry_times_zero_no_retry():
    """retry_times=0 → 只调用一次"""
    engine = FlakyEngine(fail_times=999)
    results = _proc_with_retry(engine, retry_times=0).process_batch(
        ["a.pdf"], ["报关单号"])
    assert engine.calls == 1
    assert results[0].pages[0].success is False


def test_retry_times_read_from_config():
    """retry_times 从 config["batch"] 读取（默认 2，缺省配置也生效）"""
    engine = FlakyEngine(fail_times=999)
    _proc_with_retry(engine, retry_times=3).process_batch(["a.pdf"], ["x"])
    assert engine.calls == 4


def test_retry_default_when_no_batch_config():
    """config 无 batch 段 → 默认重试 2 次（共 3 次尝试）"""
    engine = FlakyEngine(fail_times=999)
    proc = KeywordBatchProcessor(FakeLoader({"a.pdf": 1}), engine, config={})
    assert proc.retry_times == 2
    proc.process_batch(["a.pdf"], ["x"])
    assert engine.calls == 3


# ── line_boxes 透传（检测层行盒 → 预览核对） ─────────────────

class FakeLineBoxEngine:
    """带检测层行盒的引擎（PaddleOCR-VL 路径）"""
    engine_name = "paddle_vl"

    def __init__(self):
        from app.models.page_result import Block
        self.blocks = [
            Block(block_type="text", content="报关单号：090820241000039736",
                  bbox=[100, 200, 500, 240]),
            Block(block_type="text", content="价税合计：100.00",
                  bbox=[100, 300, 400, 330]),
        ]

    def recognize_page_auto(self, image):
        from app.models.page_result import PageResult
        return PageResult(blocks=self.blocks,
                          markdown="\n".join(b.content for b in self.blocks),
                          line_boxes=self.blocks)


def test_line_boxes_passed_through():
    engine = FakeLineBoxEngine()
    loader = FakeLoader({"a.pdf": 1})
    results = _proc(loader, engine).process_batch(["a.pdf"], ["报关单号"])
    page = results[0].pages[0]
    assert len(page.line_boxes) == 2
    assert page.line_boxes[0].content == "报关单号：090820241000039736"
    assert page.line_boxes[0].bbox == [100, 200, 500, 240]


def test_line_boxes_empty_when_engine_no_boxes():
    """旧引擎（无 line_boxes 字段）→ 空列表，行为不变"""
    results = _proc().process_batch(["a.pdf"], ["报关单号"])
    assert results[0].pages[0].line_boxes == []
