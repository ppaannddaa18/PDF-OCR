"""OcrFilePanel 组件测试（offscreen）

覆盖：
- add_file 返回 file_id；select_file 触发 file_selected(path)
- set_status/status_text 徽章文案（"识别中 · 页 2/10" 等，精确断言）
- remove_file 触发 file_remove_requested(path)；clear 清空列表
- 清空按钮触发 clear_requested
- 徽章前景色：done/failed 角色颜色不同（T11）
- 会话/历史分组：会话置顶、历史默认折叠、计数角标只统计会话
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
    且与 ThemeManager 角色色一致（分组重绘后新 item 沿用状态色）"""
    panel = OcrFilePanel()
    done_fid = panel.add_file("C:/a.pdf")
    failed_fid = panel.add_file("C:/b.pdf")
    panel.set_status(done_fid, "done")
    panel.set_status(failed_fid, "failed")

    def item_for_path(path):
        for i in range(panel.list.count()):
            it = panel.list.item(i)
            if it.data(Qt.ItemDataRole.UserRole) == path:
                return it
        return None

    done_item = item_for_path("C:/a.pdf")
    failed_item = item_for_path("C:/b.pdf")
    done_color = done_item.foreground().color()
    failed_color = failed_item.foreground().color()
    assert done_color.name() != failed_color.name()  # 状态角色不同色
    assert done_color.name() == QColor(
        ThemeManager.get_color("success")).name()
    assert failed_color.name() == QColor(
        ThemeManager.get_color("error")).name()
    # 带详情重设状态：重建后的新 item 沿用状态前景色 + 新文案
    panel.set_status(done_fid, "done", "2 页 · 成功 2")
    done_item2 = item_for_path("C:/a.pdf")
    assert done_item2.foreground().color().name() == done_color.name()
    assert "完成 · 2 页 · 成功 2" in done_item2.text()


def test_session_history_grouping(qapp):
    """会话/历史分组：会话置顶、历史默认折叠、计数角标只统计会话"""
    panel = OcrFilePanel()
    panel.add_file("C:/new.pdf")
    panel.add_file("C:/old.pdf", history=True)
    panel.add_file("C:/older.pdf", history=True)
    texts = [panel.list.item(i).text() for i in range(panel.list.count())]
    # 会话标题行 + 会话文件行 + 历史标题行（默认折叠，无历史文件行）
    assert texts[0] == "本次会话 (1)"
    assert "new.pdf" in texts[1]
    assert texts[2].startswith("历史记录 (2)")
    assert "old.pdf" not in texts        # 折叠 → 历史文件不可见
    assert panel.session_paths() == ["C:/new.pdf"]
    assert panel.count_badge.text() == "1"
    # 点击历史标题展开 → 历史文件出现（列表项为两行文本：文件名\n状态）
    panel._on_item_clicked(panel.list.item(2))
    texts2 = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert any("old.pdf" in t for t in texts2)
    assert any("older.pdf" in t for t in texts2)
    # 会话文件仍保持可见
    assert any("new.pdf" in t for t in texts2)
    # paths() 覆盖全部（含折叠的历史）
    assert panel.paths() == ["C:/new.pdf", "C:/old.pdf", "C:/older.pdf"]


def test_additional_session_file_goes_top(qapp):
    """会话文件按加入顺序排在本会话分组；再加一条历史不影响会话分组"""
    panel = OcrFilePanel()
    panel.add_file("C:/old.pdf", history=True)
    a = panel.add_file("C:/a.pdf")
    panel.add_file("C:/b.pdf")
    texts = [panel.list.item(i).text() for i in range(panel.list.count())]
    assert texts[0] == "本次会话 (2)"
    assert "a.pdf" in texts[1] and "b.pdf" in texts[2]
    assert texts[3].startswith("历史记录 (1)")
    assert panel.session_paths() == ["C:/a.pdf", "C:/b.pdf"]
    assert panel.selected_path() is None
    panel.select_file(a)
    assert panel.selected_path() == "C:/a.pdf"
    assert panel.list.currentItem().data(Qt.ItemDataRole.UserRole) == "C:/a.pdf"


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
    # 分组结构下文件行不再是第 0 行：按路径定位文件行
    item = None
    for i in range(panel.list.count()):
        it = panel.list.item(i)
        if it.data(Qt.ItemDataRole.UserRole) == "C:/a.pdf":
            item = it
            break
    assert item is not None
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


def test_drop_files_filters_and_emits(qapp):
    """拖拽入队：白名单过滤后 emit files_dropped（txt 被过滤）"""
    from PyQt6.QtCore import QMimeData, QPointF, QUrl, QEvent
    from PyQt6.QtGui import QDropEvent
    panel = OcrFilePanel()
    got = []
    panel.files_dropped.connect(lambda p: got.append(p))
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/docs/a.pdf"),
                  QUrl.fromLocalFile("C:/docs/b.txt"),
                  QUrl.fromLocalFile("C:/docs/c.png")])
    ev = QDropEvent(QPointF(5, 5), Qt.DropAction.CopyAction, mime,
                    Qt.MouseButton.LeftButton,
                    Qt.KeyboardModifier.NoModifier)
    panel.dropEvent(ev)
    assert got == [["C:/docs/a.pdf", "C:/docs/c.png"]]
    assert panel._drag_active is False  # drop 后复位


def test_drag_enter_highlights_drag_leave_resets(qapp):
    """拖拽悬停高亮：可拖入时 _drag_active=True 且卡片样式带 accent；
    拖出/离开复位为默认卡片样式"""
    from PyQt6.QtCore import QMimeData, QPointF, QPoint, QUrl, QEvent
    from PyQt6.QtGui import QDragEnterEvent, QDragLeaveEvent
    panel = OcrFilePanel()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/docs/a.pdf")])
    enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    panel.dragEnterEvent(enter)
    assert panel._drag_active is True
    assert "rgba(" in panel.styleSheet()  # 高亮样式已挂载
    panel.dragLeaveEvent(QDragLeaveEvent())
    assert panel._drag_active is False
    assert "rgba(" not in panel.styleSheet()  # 恢复默认卡片样式


def test_drag_enter_ignored_for_unsupported(qapp):
    """不支持的扩展名拖入：不进入高亮态"""
    from PyQt6.QtCore import QMimeData, QPoint, QUrl
    from PyQt6.QtGui import QDragEnterEvent
    panel = OcrFilePanel()
    mime = QMimeData()
    mime.setUrls([QUrl.fromLocalFile("C:/docs/note.txt")])
    enter = QDragEnterEvent(QPoint(5, 5), Qt.DropAction.CopyAction, mime,
                            Qt.MouseButton.LeftButton,
                            Qt.KeyboardModifier.NoModifier)
    panel.dragEnterEvent(enter)
    assert panel._drag_active is False
