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


@pytest.fixture(autouse=True)
def guard_save_config(monkeypatch):
    """全库防线：测试路径一律不允许把内存配置写回真实 app/config.yaml。

    个别测试显式验证保存路径时再自行打桩（monkeypatch 后设覆盖本桩），
    不会被本防线拦截；未被显式覆盖的调用点（如窗口内部的保存逻辑漏桩）
    会被静默吞掉，防止污染开发配置。
    """
    import app.utils.config_loader as cfg_mod
    monkeypatch.setattr(cfg_mod, "save_config", lambda config: None)
