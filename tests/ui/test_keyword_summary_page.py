"""汇总页：守卫/集合下拉/统计/进度"""
from app.ui.widgets.keyword_summary_page import KeywordSummaryPage
from app.utils.keyword_set_manager import KeywordSetManager


def _make_page(tmp_path):
    mgr = KeywordSetManager(storage_dir=str(tmp_path))
    page = KeywordSummaryPage(mgr)
    return page, mgr


def test_construct(qapp, tmp_path):
    page, _ = _make_page(tmp_path)
    assert page.tree is not None


def test_extract_guard_empty_keywords(qapp, tmp_path):
    """关键字为空 → 不发提取信号"""
    page, _ = _make_page(tmp_path)
    emitted = []
    page.extract_requested.connect(lambda k: emitted.append(k))
    page.keyword_input.setText("   ")
    page._on_extract_clicked()
    assert emitted == []


def test_extract_emits_parsed_keywords(qapp, tmp_path):
    page, _ = _make_page(tmp_path)
    emitted = []
    page.extract_requested.connect(lambda k: emitted.append(k))
    page.keyword_input.setText("报关单号,价税合计；发票号码")
    page._on_extract_clicked()
    assert emitted == [["报关单号", "价税合计", "发票号码"]]


def test_set_combo_filled_from_manager(qapp, tmp_path):
    page, mgr = _make_page(tmp_path)
    mgr.save("发票集", ["发票号码"])
    page.refresh_sets()
    assert page.set_combo.count() == 1
    assert page.set_combo.itemText(0) == "发票集"


def test_set_combo_load_fills_input(qapp, tmp_path):
    page, mgr = _make_page(tmp_path)
    mgr.save("发票集", ["发票号码"])
    mgr.save("报关单集", ["报关单号", "境内收货人"])
    page.refresh_sets()
    # refresh_sets 后自动选中第一项（排序后：发票集在报关单集前）；切换触发信号
    assert page.set_combo.currentText() == "发票集"
    page.set_combo.setCurrentText("报关单集")
    assert "报关单号" in page.keyword_input.text()


def test_running_state_controls_progress(qapp, tmp_path):
    """isVisible 依赖父链显示，无窗口环境用 isHidden 断言显隐"""
    page, _ = _make_page(tmp_path)
    page.set_running(True)
    assert not page.progress_bar.isHidden()
    assert not page.btn_cancel.isHidden()
    page.set_running(False)
    assert page.progress_bar.isHidden()
