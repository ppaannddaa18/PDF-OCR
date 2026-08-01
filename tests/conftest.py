"""根测试共享 fixture — qapp 供 tests/ 根目录下的 QThread 信号测试使用

tests/ui/conftest.py 也定义 qapp（目录级 fixture 优先，UI 测试仍用它）。
"""
import pytest
from PyQt6.QtWidgets import QApplication


@pytest.fixture(scope='session')
def qapp():
    """返回 QApplication 单例（QThread 信号测试用）"""
    return QApplication.instance() or QApplication([])
