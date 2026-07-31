import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.toast_notification import ToastNotification


class TestToastNotification:
    def test_create_toast(self, qapp):
        toast = ToastNotification()
        assert toast is not None
        assert toast.width() == 320

    def test_show_message(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        toast = ToastNotification(parent)
        toast.show_message('测试消息', 'success')
        assert toast.message_label.text() == '测试消息'
        assert toast.icon_label.text() == '✓'
        toast.close()

    def test_type_colors(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        for type_name, icon in [('success', '✓'), ('warning', '⚠'),
                                ('error', '✗'), ('info', 'ℹ')]:
            toast = ToastNotification(parent)
            toast.show_message(f'Test {type_name}', type_name, duration=100)
            # 图标字符正确
            assert toast.icon_label.text() == icon
            # 图标与边框颜色为对应主题角色色（conftest 已复位 light 主题）
            expected_color = ThemeManager.get_color(
                ToastNotification.TYPE_COLORS[type_name])
            assert expected_color in toast.icon_label.styleSheet()
            assert expected_color in toast.styleSheet()
            toast.close()

    def test_class_method_show(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        toast = ToastNotification.show('快速通知', parent=parent)
        assert toast is not None
        toast.close()
