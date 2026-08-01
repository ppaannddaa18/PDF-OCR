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
