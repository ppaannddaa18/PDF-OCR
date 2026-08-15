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
