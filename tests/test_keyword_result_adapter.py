"""Task P4 测试：keyword_result_adapter（FileKeywordResult → FileResult）"""
from app.core.keyword_result_adapter import to_file_results
from app.models.keyword_result import (
    FileKeywordResult, KeywordCell, PageKeywordResult,
)


def _cell(keyword, value, status="confirmed", confidence=1.0, edited=False):
    return KeywordCell(
        keyword=keyword, value=value, status=status,
        confidence=confidence, manually_edited=edited)


def test_basic_mapping_one_keyword_per_row():
    results = [
        FileKeywordResult(
            source_file="a.pdf",
            pages=[PageKeywordResult(page_no=1, cells={
                "发票号码": _cell("发票号码", "123", confidence=0.9),
                "价税合计": _cell("价税合计", "456", status="pending", confidence=0.4),
            })],
            success=True,
        ),
    ]
    converted = to_file_results(results)
    assert len(converted) == 1
    fr = converted[0]
    assert fr.source_file == "a.pdf"
    assert fr.success is True
    assert set(fr.fields) == {"发票号码", "价税合计"}
    assert fr.fields["发票号码"].text == "123"
    assert fr.fields["发票号码"].confidence == 0.9
    assert fr.fields["发票号码"].engine == "gguf"
    assert fr.fields["价税合计"].manually_edited is False


def test_duplicate_keyword_across_pages_gets_suffix():
    results = [
        FileKeywordResult(
            source_file="a.pdf",
            pages=[
                PageKeywordResult(page_no=1, cells={
                    "金额": _cell("金额", "111"),
                }),
                PageKeywordResult(page_no=2, cells={
                    "金额": _cell("金额", "222"),
                }),
                PageKeywordResult(page_no=3, cells={
                    "金额": _cell("金额", "333"),
                }),
            ],
            success=True,
        ),
    ]
    fr = to_file_results(results)[0]
    assert set(fr.fields) == {"金额", "金额_2", "金额_3"}
    assert fr.fields["金额_2"].text == "222"


def test_manual_edited_flag_preserved():
    results = [
        FileKeywordResult(
            source_file="a.pdf",
            pages=[PageKeywordResult(page_no=1, cells={
                "备注": _cell("备注", "手工改", edited=True),
            })],
            success=True,
        ),
    ]
    fr = to_file_results(results)[0]
    assert fr.fields["备注"].manually_edited is True


def test_failed_file_passes_success_and_error():
    results = [
        FileKeywordResult(source_file="b.pdf", pages=[], success=False, error_msg="boom"),
    ]
    fr = to_file_results(results)[0]
    assert fr.success is False
    assert fr.error_msg == "boom"
    assert fr.fields == {}


def test_empty_input_returns_empty_list():
    assert to_file_results([]) == []
