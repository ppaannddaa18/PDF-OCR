"""UI 测试共享 fixture"""

import sys
from pathlib import Path

import pytest
from PyQt6.QtWidgets import QApplication

# 将仓库根目录插入 sys.path 开头，保证裸 pytest（不带 -m）也能导入 app 包
REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from app.ui.theme_manager import ThemeManager


@pytest.fixture(scope='session')
def qapp():
    """返回 QApplication 单例，所有 UI 测试共用"""
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def reset_theme():
    """每个测试前复位主题与设计状态，避免类级全局状态跨测试污染"""
    ThemeManager.set_design('default')  # 先复位设计，set_theme 才生效
    ThemeManager.set_theme('light')
    yield
