"""KeywordBatchWorker 薄层：信号转发与取消传播（QThread，需 qapp）"""
import pytest

from app.workers.keyword_batch_worker import KeywordBatchWorker
from app.core.keyword_batch_processor import KeywordBatchProcessor


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def process_batch(self, pdf_files, keywords, progress_cb=None,
                      completed_results=None):
        self.calls.append(("process_batch", keywords))
        progress_cb(1, 1, "a.pdf")
        return []


def _make_worker(processor=None):
    proc = processor or FakeProcessor()
    return KeywordBatchWorker(proc, ["a.pdf"], ["报关单号"]), proc


def test_worker_signals_finished(qapp):
    worker, proc = _make_worker()
    finished = []
    worker.finished_all.connect(finished.append)
    worker.run()
    assert finished == [[]]
    assert proc.calls[0][1] == ["报关单号"]


def test_worker_progress_forwarded(qapp):
    worker, _ = _make_worker()
    seen = []
    worker.progress.connect(lambda d, t, f: seen.append((d, t, f)))
    worker.run()
    assert seen == [(1, 1, "a.pdf")]


def test_worker_cancel_emits_cancelled(qapp):
    class ThrowingProcessor:
        def process_batch(self, pdf_files, keywords, progress_cb=None,
                          completed_results=None):
            raise InterruptedError("用户取消")

    worker = KeywordBatchWorker(ThrowingProcessor(), ["a.pdf"], ["x"])
    cancelled = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.run()
    assert cancelled == [True]


def test_worker_cancel_keeps_partial_results(qapp):
    """取消时已完成文件的部分结果保留在 _completed_results（供界面展示）"""

    class PartialThenThrowProcessor:
        def process_batch(self, pdf_files, keywords, progress_cb=None,
                          completed_results=None):
            completed_results.append({"file": "a.pdf"})
            progress_cb(1, 2, "a.pdf")
            raise InterruptedError("用户取消")

    worker = KeywordBatchWorker(
        PartialThenThrowProcessor(), ["a.pdf", "b.pdf"], ["x"])
    cancelled = []
    finished = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.finished_all.connect(lambda r: finished.append(r))
    worker.run()
    assert cancelled == [True]
    assert finished == []
    assert worker._completed_results == [{"file": "a.pdf"}]


def test_worker_completed_results_accumulate(qapp):
    class CollectingProcessor:
        def process_batch(self, pdf_files, keywords, progress_cb=None,
                          completed_results=None):
            progress_cb(1, 2, "a.pdf")
            return [1]  # 部分结果

    worker = KeywordBatchWorker(CollectingProcessor(), ["a.pdf", "b.pdf"], ["x"])
    worker.run()
    assert worker._completed_results == [1]
