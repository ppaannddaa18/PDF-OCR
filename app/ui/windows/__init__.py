"""
双界面窗口包（Task P3a：拆主窗口）

- AppBaseWindowMixin：双窗口共享底座（从旧 main_window.py 机械提取）
- RapidMainWindow：RapidOCR 固定浅色工作台（MSFluentWindow 顶部标签导航）
"""
from app.ui.windows.base_window import AppBaseWindowMixin
from app.ui.windows.rapid_main_window import RapidMainWindow

__all__ = ["AppBaseWindowMixin", "RapidMainWindow"]
