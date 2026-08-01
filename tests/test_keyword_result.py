from app.models.keyword_result import KeywordCell, PageKeywordResult, FileKeywordResult


def test_cell_defaults():
    c = KeywordCell(keyword="报关单号")
    assert c.value == ""
    assert c.status == "not_found"
    assert c.source == "none"
    assert c.manually_edited is False


def test_page_result_shape():
    pg = PageKeywordResult(page_no=1, cells={"报关单号": KeywordCell(keyword="报关单号")})
    assert pg.success is True
    assert pg.error_msg == ""


def test_file_result_shape():
    fr = FileKeywordResult(source_file="a.pdf")
    assert fr.pages == []
    assert fr.success is True


def test_status_source_enum():
    c = KeywordCell(keyword="价税合计", value="100", status="pending", source="loose")
    assert c.status in ("confirmed", "pending", "not_found")
    assert c.source in ("exact", "loose", "none")
