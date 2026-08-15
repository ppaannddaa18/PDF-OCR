"""BatchProcessor 重试测试 — batch.retry_times 接线（设置页参数此前无消费者）"""
from PIL import Image

from app.core.batch_processor import BatchProcessor
from app.models.region import Region
from app.models.template import Template


class FakeLoader:
    def render_page(self, path, page_num):
        return Image.new("RGB", (200, 100), "white")


class FlakyRapidEngine:
    """RapidOCR 路径：前 fail_times 次 recognize 抛异常，之后正常返回"""
    engine_name = "rapidocr"

    def __init__(self, fail_times=1):
        self.fail_times = fail_times
        self.calls = 0

    def recognize(self, crop, mode):
        self.calls += 1
        if self.calls <= self.fail_times:
            raise RuntimeError("ocr transient fail")
        return "金额123", 0.9


def _template():
    return Template(name="t", regions=[
        Region(id="r1", field_name="金额", x=0.1, y=0.1, w=0.3, h=0.2)])


def _proc(engine, retry_times):
    return BatchProcessor(FakeLoader(), engine,
                          config={"batch": {"retry_times": retry_times}})


def test_retry_succeeds_after_transient_failure():
    """偶发失败（第 1 次抛异常）→ 重试后成功"""
    engine = FlakyRapidEngine(fail_times=1)
    result = _proc(engine, retry_times=2).process_one("a.pdf", _template())
    assert engine.calls == 2
    assert result.success is True
    assert result.fields["金额"].text == "金额123"


def test_retry_exhausted_marks_failed():
    """恒失败 → 调用次数 = retry_times + 1，结果失败并保留错误"""
    engine = FlakyRapidEngine(fail_times=999)
    result = _proc(engine, retry_times=2).process_one("a.pdf", _template())
    assert engine.calls == 3
    assert result.success is False
    assert "transient fail" in result.error_msg


def test_retry_times_zero_no_retry():
    """retry_times=0 → 只调用一次"""
    engine = FlakyRapidEngine(fail_times=999)
    result = _proc(engine, retry_times=0).process_one("a.pdf", _template())
    assert engine.calls == 1
    assert result.success is False


def test_retry_times_read_from_config():
    """retry_times 从 config["batch"] 读取（缺省 2）"""
    engine = FlakyRapidEngine(fail_times=999)
    result = _proc(engine, retry_times=3).process_one("a.pdf", _template())
    assert engine.calls == 4
    assert result.success is False


def test_success_path_calls_engine_once():
    """成功路径不做多余调用（不回归）"""
    engine = FlakyRapidEngine(fail_times=0)
    result = _proc(engine, retry_times=2).process_one("a.pdf", _template())
    assert engine.calls == 1
    assert result.success is True
