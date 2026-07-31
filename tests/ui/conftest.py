"""UI 测试共享 fixture"""

import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope='session')
def qapp():
    """返回 QApplication 单例，所有 UI 测试共用"""
    return QApplication.instance() or QApplication([])
