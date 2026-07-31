# tests/ui/widgets/test_file_list_panel.py
"""Task 8 重构回归测试：紧凑版 FileListPanel

覆盖核心行为：
- 空状态（EmptyState 'no_files'）显示/隐藏
- 添加/移除/清空文件及对应信号
- set_pdf_config_status 状态色条（delegate 颜色映射 + tooltip + 数据角色）
- 批量添加（分批 + 进度信号 + 定时器清理）
- 拖拽 PDF 文件
"""
from PyQt6.QtCore import Qt, QMimeData, QUrl, QPointF
from PyQt6.QtGui import QDropEvent
from PyQt6.QtTest import QTest

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.file_list_panel import (
    FileListPanel, STATUS_ROLE, PATH_ROLE, status_color,
)


class TestEmptyState:
    def test_empty_state_visible_initially(self, qapp):
        panel = FileListPanel()
        panel.show()
        assert panel.empty_state.isVisible()
        assert not panel.list_widget.isVisible()
        assert not panel.btn_remove.isEnabled()
        assert not panel.btn_clear.isEnabled()

    def test_empty_state_hidden_after_add(self, qapp):
        panel = FileListPanel()
        panel.show()
        panel.add_files(['a.pdf'])
        assert not panel.empty_state.isVisible()
        assert panel.list_widget.isVisible()
        assert panel.btn_remove.isEnabled()
        assert panel.btn_clear.isEnabled()

    def test_empty_state_returns_after_clear(self, qapp):
        panel = FileListPanel()
        panel.show()
        panel.add_files(['a.pdf'])
        panel.clear_files()
        assert panel.empty_state.isVisible()
        assert not panel.list_widget.isVisible()

    def test_show_empty_state_toggle(self, qapp):
        panel = FileListPanel()
        panel.show()
        panel.add_files(['a.pdf'])
        panel.show_empty_state(True)
        assert panel.empty_state.isVisible()
        assert not panel.list_widget.isVisible()
        panel.show_empty_state(False)
        assert not panel.empty_state.isVisible()
        assert panel.list_widget.isVisible()

    def test_upload_requested_signal_from_empty_state_action(self, qapp):
        """EmptyState 操作按钮（上传 PDF）触发 upload_requested 信号"""
        panel = FileListPanel()
        panel.show()
        emitted = []
        panel.upload_requested.connect(lambda: emitted.append(True))
        QTest.mouseClick(panel.empty_state.action_button, Qt.MouseButton.LeftButton)
        assert emitted == [True]


class TestFileManagement:
    def test_add_files_emits_file_selected(self, qapp):
        panel = FileListPanel()
        selected = []
        panel.file_selected.connect(selected.append)
        panel.add_files(['a.pdf', 'b.pdf'])
        assert panel.files == ['a.pdf', 'b.pdf']
        assert selected == ['a.pdf']  # 仅首个文件触发自动加载

    def test_add_files_ignores_duplicates(self, qapp):
        panel = FileListPanel()
        panel.add_files(['a.pdf'])
        panel.add_files(['a.pdf', 'b.pdf'])
        assert panel.files == ['a.pdf', 'b.pdf']
        assert panel.list_widget.count() == 2

    def test_remove_selected_emits_file_removed(self, qapp):
        panel = FileListPanel()
        removed = []
        panel.file_removed.connect(removed.append)
        panel.add_files(['a.pdf', 'b.pdf'])
        panel.list_widget.setCurrentRow(0)
        panel.remove_selected()
        assert panel.files == ['b.pdf']
        assert removed == ['a.pdf']

    def test_clear_files_emits_files_cleared(self, qapp):
        panel = FileListPanel()
        cleared = []
        panel.files_cleared.connect(lambda: cleared.append(True))
        panel.add_files(['a.pdf'])
        panel.clear_files()
        assert panel.files == []
        assert panel.list_widget.count() == 0
        assert cleared == [True]

    def test_all_files_returns_copy(self, qapp):
        panel = FileListPanel()
        panel.add_files(['a.pdf'])
        result = panel.all_files()
        result.append('mutated.pdf')
        assert panel.files == ['a.pdf']

    def test_current_file_without_selection_returns_first(self, qapp):
        panel = FileListPanel()
        assert panel.current_file() is None
        panel.add_files(['a.pdf', 'b.pdf'])
        assert panel.current_file() == 'a.pdf'
        panel.list_widget.setCurrentRow(1)
        assert panel.current_file() == 'b.pdf'


class TestStatusIndicator:
    def test_status_color_mapping_uses_theme_roles(self, qapp):
        """状态色必须来自 ThemeManager 角色色（禁止硬编码）"""
        assert status_color('custom') == ThemeManager.get_color('primary')
        assert status_color('default') == ThemeManager.get_color('success')
        assert status_color('empty') == ThemeManager.get_color('text_disabled')
        assert status_color('none') == ThemeManager.get_color('text_disabled')
        assert status_color(None) == ThemeManager.get_color('text_disabled')
        assert status_color('unknown') == ThemeManager.get_color('text_disabled')

    def test_set_pdf_config_status_updates_item(self, qapp):
        panel = FileListPanel()
        panel.add_files(['a.pdf', 'b.pdf'])
        panel.set_pdf_config_status('b.pdf', 'custom')
        item = panel.list_widget.item(1)
        assert item.data(STATUS_ROLE) == 'custom'
        assert item.data(PATH_ROLE) == 'b.pdf'
        assert '使用自定义字段配置' in item.toolTip()
        assert panel._pdf_configs['b.pdf'] == 'custom'

    def test_set_pdf_config_status_default(self, qapp):
        panel = FileListPanel()
        panel.add_files(['a.pdf'])
        panel.set_pdf_config_status('a.pdf', 'default')
        assert panel.list_widget.item(0).data(STATUS_ROLE) == 'default'
        assert '使用默认模板' in panel.list_widget.item(0).toolTip()

    def test_set_pdf_config_status_empty(self, qapp):
        panel = FileListPanel()
        panel.add_files(['a.pdf'])
        panel.set_pdf_config_status('a.pdf', 'empty')
        assert panel.list_widget.item(0).data(STATUS_ROLE) == 'empty'
        assert '无字段配置' in panel.list_widget.item(0).toolTip()

    def test_set_pdf_config_status_unknown_path_no_crash(self, qapp):
        """main_window 会对所有 files 调状态；不存在的路径不应崩溃"""
        panel = FileListPanel()
        panel.add_files(['a.pdf'])
        panel.set_pdf_config_status('ghost.pdf', 'custom')
        assert panel.list_widget.item(0).data(STATUS_ROLE) is None

    def test_status_bar_renders_on_left_edge(self, qapp):
        """渲染验证：delegate 在列表项左侧绘制 3px 状态色条"""
        from PyQt6.QtGui import QPixmap

        panel = FileListPanel()
        panel.setFixedSize(240, 160)
        panel.add_files(['a.pdf', 'b.pdf'])
        panel.set_pdf_config_status('a.pdf', 'custom')
        panel.set_pdf_config_status('b.pdf', 'default')
        panel.show()
        qapp.processEvents()

        # 只采样 viewport 内完整可见的行（不可见行不参与绘制）
        viewport_rect = panel.list_widget.viewport().rect()
        visible = []
        for row in range(panel.list_widget.count()):
            r = panel.list_widget.visualItemRect(panel.list_widget.item(row))
            if (viewport_rect.contains(r.topLeft())
                    and viewport_rect.contains(r.bottomRight())):
                visible.append(row)

        pix = QPixmap(panel.list_widget.size())
        panel.list_widget.render(pix)
        img = pix.toImage()

        # 行 0 左侧色条 = primary；行 1 = success
        expected = [ThemeManager.get_color('primary'),
                    ThemeManager.get_color('success')]
        for row in visible:
            rect = panel.list_widget.visualItemRect(panel.list_widget.item(row))
            y = rect.top() + rect.height() // 2
            actual = img.pixelColor(1, y).name().lower()
            assert actual == expected[row].lower(), (
                f"row {row} bar color {actual}, expected {expected[row]}")


class TestBatchAdd:
    def test_batch_add_completes_and_emits_progress(self, qapp):
        panel = FileListPanel()
        progress = []
        panel.batch_add_progress.connect(
            lambda cur, total: progress.append((cur, total)))
        files = [f'f{i:02d}.pdf' for i in range(12)]  # 超过 BATCH_SIZE=10
        panel.add_files(files)
        QTest.qWait(300)  # 等待分批定时器全部触发
        assert panel.files == files
        assert panel.list_widget.count() == 12
        assert progress[-1] == (12, 12)
        assert not panel.progress_label.isVisible()

    def test_clear_files_during_batch_stops_timers(self, qapp):
        panel = FileListPanel()
        files = [f'f{i:02d}.pdf' for i in range(12)]
        panel.add_files(files)
        panel.clear_files()  # 清空时应停掉并清理待处理定时器
        assert panel.files == []
        assert panel.list_widget.count() == 0
        assert panel._pending_timers == []


class TestDragDrop:
    def test_drop_pdf_files(self, qapp):
        panel = FileListPanel()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile('a.pdf'), QUrl.fromLocalFile('b.pdf')])
        event = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.dropEvent(event)
        assert len(panel.files) == 2
        assert all(f.endswith('.pdf') for f in panel.files)

    def test_drop_rejects_non_pdf(self, qapp):
        panel = FileListPanel()
        mime = QMimeData()
        mime.setUrls([QUrl.fromLocalFile('note.txt')])
        event = QDropEvent(
            QPointF(10, 10), Qt.DropAction.CopyAction, mime,
            Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.dropEvent(event)
        assert panel.files == []
