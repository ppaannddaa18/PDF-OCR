"""OcrFilePanel 组件测试（offscreen）

覆盖：
- add_file 返回 file_id；select_file 触发 file_selected(path)
- set_status/status_text 徽章文案（"识别中 · 页 2/10" 等，精确断言）
- remove_file 触发 file_remove_requested(path)；clear 清空列表
- 清空按钮触发 clear_requested
"""
from PyQt6.QtCore import Qt
from PyQt6.QtTest import QTest

from app.ui.widgets.ocr_file_panel import OcrFilePanel


def test_add_and_select(qapp):
    panel = OcrFilePanel()
    fid = panel.add_file("C:/docs/a.pdf")
    selected = []
    panel.file_selected.connect(lambda p: selected.append(p))
    panel.select_file(fid)
    assert selected == ["C:/docs/a.pdf"]
    assert panel.paths() == ["C:/docs/a.pdf"]
    assert panel.selected_path() == "C:/docs/a.pdf"


def test_status_badge_text(qapp):
    panel = OcrFilePanel()
    fid = panel.add_file("C:/docs/a.pdf")
    panel.set_status(fid, "processing", "页 2/10")
    assert panel.status_text(fid) == "识别中 · 页 2/10"
    panel.set_status(fid, "done", "12.3s")
    assert panel.status_text(fid) == "完成 · 12.3s"
    panel.set_status(fid, "failed", "OOM")
    assert "失败" in panel.status_text(fid)


def test_file_id_by_path(qapp):
    panel = OcrFilePanel()
    fid = panel.add_file("C:/docs/a.pdf")
    panel.add_file("C:/docs/b.pdf")
    assert panel.file_id_by_path("C:/docs/a.pdf") == fid
    assert panel.file_id_by_path("C:/docs/b.pdf") != fid
    assert panel.file_id_by_path("C:/nope.pdf") is None


def test_remove_and_clear(qapp):
    panel = OcrFilePanel()
    a = panel.add_file("C:/a.pdf")
    panel.add_file("C:/b.pdf")
    removed = []
    panel.file_remove_requested.connect(lambda p: removed.append(p))
    panel.remove_file(a)
    assert "C:/a.pdf" not in panel.paths()
    assert removed == ["C:/a.pdf"]
    panel.clear()
    assert panel.paths() == []


def test_clear_button_emits_clear_requested(qapp):
    panel = OcrFilePanel()
    panel.add_file("C:/a.pdf")
    cleared = []
    panel.clear_requested.connect(lambda: cleared.append(True))
    panel.show()
    QTest.mouseClick(panel.clear_btn, Qt.MouseButton.LeftButton)
    assert cleared == [True]
