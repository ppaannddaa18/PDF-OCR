"""PDF 文本层定位：fitz 词级坐标 → 矩形（合成内存 PDF）"""
import fitz
import pytest

from app.core.text_layer_locator import locate_words


@pytest.fixture
def page():
    doc = fitz.open()
    pg = doc.new_page()
    # 中文 insert_text 需字体，测试用英文（定位逻辑与语言无关）
    pg.insert_text((72, 72), "Invoice No: 12345678")
    pg.insert_text((72, 100), "Total: 99.50")
    return pg


def test_locate_existing_text(page):
    rects = locate_words(page, "12345678")
    assert len(rects) == 1
    x0, y0, x1, y1 = rects[0]
    assert x0 < x1 and y0 < y1


def test_scale_applied(page):
    rects = locate_words(page, "12345678", scale=2.0)
    rects_1x = locate_words(page, "12345678", scale=1.0)
    assert rects[0][0] == pytest.approx(rects_1x[0][0] * 2)
    assert rects[0][3] == pytest.approx(rects_1x[0][3] * 2)


def test_locate_missing_returns_empty(page):
    assert locate_words(page, "99999999") == []


def test_locate_multi_word_value(page):
    rects = locate_words(page, "99.50")
    assert len(rects) == 1


def test_empty_text_returns_empty(page):
    assert locate_words(page, "") == []


def test_first_only_returns_one(page):
    pg2 = page  # 同页重复文本
    doc = fitz.open()
    pg3 = doc.new_page()
    pg3.insert_text((72, 72), "X 111")
    pg3.insert_text((72, 120), "X 111")
    assert len(locate_words(pg3, "111", first_only=True)) == 1
    assert len(locate_words(pg3, "111", first_only=False)) >= 2


def test_rect_matches_word_not_line_prefix(page):
    """矩形应从匹配文本开始，不含行首无关词（回归：行首拼接合并 bug）"""
    words = page.get_text("words")
    target = next(w for w in words if w[4] == "12345678")
    x0, y0, x1, y1 = locate_words(page, "12345678")[0]
    assert x0 >= target[0] - 2
    assert x1 <= target[2] + 2


def test_rect_not_merge_first_line(page):
    """第二行值的矩形应位于第二行，不从第一行行首开始"""
    target = next(w for w in page.get_text("words") if w[4] == "99.50")
    x0, y0, x1, y1 = locate_words(page, "99.50")[0]
    assert x0 >= target[0] - 2
    assert x1 <= target[2] + 2
    assert y0 >= target[1] - 2  # 修复前 y0 会取到第一行（合并了行首词）


def test_rotation_90_maps_into_rendered_canvas():
    """页面 rotation=90：坐标须经 rotation_matrix 变换，落在旋转后渲染图内
    （回归：修复前未变换 → 高亮框 y 超出画布，GUI 预览不可见）"""
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "Invoice No: 12345678")
    pg.set_rotation(90)
    rects = locate_words(pg, "12345678")
    assert len(rects) == 1
    x0, y0, x1, y1 = rects[0]
    # 渲染图像（200dpi，旋转 90 后横向）：宽高与原始页面互换
    pix = pg.get_pixmap(matrix=fitz.Matrix(200 / 72, 200 / 72))
    # rotation_matrix 变换后为旋转方向坐标 → ×scale 应在画布内
    assert 0 <= x0 < x1 <= pix.width + 1
    assert 0 <= y0 < y1 <= pix.height + 1


def test_rotation_0_unchanged(page):
    """rotation=0 时行为不变（单位矩阵）"""
    before = locate_words(page, "12345678")
    assert before[0][0] > 0


def test_search_for_exact_substring_in_word():
    """T14：fitz 把相邻同字体文本合并为一个 word（"ABC123DEF"）——search_for
    优先路径返回词内子串"123"的精确边界（x0 在 123 起始、x1 在 123 结束，
    不含 ABC/DEF 段）；修复前拼接匹配返回整词矩形、水平超宽"""
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "ABC123DEF")
    word = next(w for w in pg.get_text("words") if w[4] == "ABC123DEF")
    rects = locate_words(pg, "123")
    assert len(rects) == 1
    x0, _y0, x1, _y1 = rects[0]
    assert x0 > word[0] + 1    # 不含 ABC 段（修复前 x0 取整词起点）
    assert x1 < word[2] - 1    # 不含 DEF 段（修复前 x1 取整词终点）
    # 与 search_for 直接结果 0 偏差（未旋转页 rotation_matrix 为单位矩阵）
    srect = pg.search_for("123")[0]
    assert x0 == pytest.approx(srect.x0)
    assert x1 == pytest.approx(srect.x1)


def test_cross_word_text_matches_or_falls_back(page):
    """T14：跨词文本（含空白）——search_for 能精确匹配则同样精确，否则回退
    跨词拼接；两路径矩形都覆盖两词完整区间（回归：高亮不丢失/不超宽）"""
    words = {w[4]: w for w in page.get_text("words")}
    rects = locate_words(page, "Total: 99.50")
    assert len(rects) == 1
    x0, _y0, x1, _y1 = rects[0]
    assert x0 <= words["Total:"][0] + 2   # 起始不晚于 Total: 词起点
    assert x1 >= words["99.50"][2] - 2    # 结束不早于 99.50 词终点
    # 精确路径（search_for 命中）时与直接结果一致
    srects = page.search_for("Total: 99.50")
    if srects:
        assert x0 == pytest.approx(srects[0].x0)
        assert x1 == pytest.approx(srects[0].x1)
