import json
import pytest

from app.utils.keyword_set_manager import KeywordSetManager


@pytest.fixture
def mgr(tmp_path):
    return KeywordSetManager(storage_dir=str(tmp_path))


def test_save_load_roundtrip(mgr):
    mgr.save("发票集", ["发票号码", "价税合计", "开票日期"])
    assert mgr.load("发票集") == ["发票号码", "价税合计", "开票日期"]


def test_list_sets_sorted(mgr):
    mgr.save("b集", ["x"])
    mgr.save("a集", ["y"])
    assert mgr.list_sets() == ["a集", "b集"]


def test_load_missing_returns_none(mgr):
    assert mgr.load("不存在") is None


def test_delete(mgr):
    mgr.save("集", ["a"])
    assert mgr.delete("集") is True
    assert mgr.load("集") is None
    assert mgr.delete("集") is False


def test_overwrite_same_name(mgr):
    mgr.save("集", ["a"])
    mgr.save("集", ["b", "c"])
    assert mgr.load("集") == ["b", "c"]


def test_corrupted_file_backed_up(mgr, tmp_path):
    store = tmp_path / "keyword_sets.json"
    store.write_text("{not json", encoding="utf-8")
    assert mgr.list_sets() == []
    assert (tmp_path / "keyword_sets.json.bak").exists()


def test_chinese_names_and_keywords(mgr):
    mgr.save("报关单集", ["报关单号", "境内收货人"])
    assert mgr.load("报关单集") == ["报关单号", "境内收货人"]
