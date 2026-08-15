"""OcrFilePanel 组件测试（offscreen）

覆盖：
- add_file 返回 file_id；select_file 触发 file_selected(path)
- set_status/status_text 徽章文案（"识别中 · 页 2/10" 等，精确断言）
- remove_file 触发 file_remove_requested(path)；clear 清空列表
- 清空按钮触发 clear_requested
- 徽章前景色：done/failed 角色颜色不同（T11）
- 右键菜单删除该文件；select/remove 未知 fid 不抛 KeyError（T11）
"""
from PyQt6.QtCore import Qt, QPoint
from PyQt6.QtGui import QColor
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QMenu

from app.ui.theme_manager import ThemeManager
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


def test_badge_foreground_colors_by_status(qapp):
    """T11：set_status 按状态设 item 前景色——done 与 failed 颜色不同，
    且与 ThemeManager 角色色一致（setText 不影响前景色）"""
    panel = OcrFilePanel()
    done_fid = panel.add_file("C:/a.pdf")
    failed_fid = panel.add_file("C:/b.pdf")
    panel.set_status(done_fid, "done")
    panel.set_status(failed_fid, "failed")
    done_item, _ = panel._items[done_fid]
    failed_item, _ = panel._items[failed_fid]
    done_color = done_item.foreground().color()
    failed_color = failed_item.foreground().color()
    assert done_color.name() != failed_color.name()  # 状态角色不同色
    assert done_color.name() == QColor(
        ThemeManager.get_color("success")).name()
    assert failed_color.name() == QColor(
        ThemeManager.get_color("error")).name()
    # setText 与前景色共存：改文案前景色不变
    panel.set_status(done_fid, "done", "2 页 · 成功 2")
    assert done_item.foreground().color().name() == done_color.name()
    assert "完成 · 2 页 · 成功 2" in done_item.text()


def test_remove_unknown_fid_is_noop(qapp):
    """T11：remove_file/select_file 对未知 fid 不抛 KeyError"""
    panel = OcrFilePanel()
    panel.add_file("C:/a.pdf")
    panel.remove_file("no-such-fid")   # 不抛异常
    panel.select_file("no-such-fid")   # 不抛异常
    assert panel.paths() == ["C:/a.pdf"]


def test_context_menu_removes_file(qapp, monkeypatch):
    """T11：右键菜单"删除该文件"→ 面板移除 + file_remove_requested(path)

    QTest.mouseClick 不产生 contextMenuEvent（该事件由窗口系统层合成），
    故直接向 viewport 派发 QContextMenuEvent，覆盖 CustomContextMenu 策略
    → customContextMenuRequested → 菜单构建的真实路径。
    """
    from PyQt6.QtGui import QContextMenuEvent
    from PyQt6.QtWidgets import QApplication

    panel = OcrFilePanel()
    fid = panel.add_file("C:/a.pdf")
    removed = []
    panel.file_remove_requested.connect(lambda p: removed.append(p))
    captured = {}

    def fake_exec(menu, *args):
        captured["menu"] = menu
        return None  # 屏蔽 QMenu.exec 事件循环阻塞

    monkeypatch.setattr(QMenu, "exec", fake_exec)
    panel.show()
    item = panel.list.item(0)
    pos = panel.list.visualItemRect(item).center()
    QApplication.sendEvent(panel.list.viewport(),
                           QContextMenuEvent(QContextMenuEvent.Reason.Mouse,
                                             pos))
    menu = captured.get("menu")
    assert menu is not None
    assert [a.text() for a in menu.actions()] == ["删除该文件"]
    menu.actions()[0].trigger()
    assert "C:/a.pdf" not in panel.paths()
    assert removed == ["C:/a.pdf"]
    assert fid not in panel._items
