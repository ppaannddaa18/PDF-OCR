import pytest
from PyQt6.QtWidgets import QApplication, QWidget
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
        for type_name in ['success', 'warning', 'error', 'info']:
            toast = ToastNotification(parent)
            toast.show_message(f'Test {type_name}', type_name, duration=100)
            toast.close()

    def test_class_method_show(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        toast = ToastNotification.show('快速通知', parent=parent)
        assert toast is not None
        toast.close()
