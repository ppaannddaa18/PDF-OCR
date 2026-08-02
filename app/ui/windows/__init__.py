"""双界面窗口包（Task P3a：拆主窗口）

- AppBaseWindowMixin：双窗口共享底座（从旧 main_window.py 机械提取）
- GgufMainWindow：GGUF 深色推理操作台（FluentWindow 侧边导航 4 页）
- RapidMainWindow：RapidOCR 固定浅色工作台（MSFluentWindow 顶部标签导航）

注意：本包 __init__ 刻意不做任何导入（P4 import 隔离约束）——两个窗口模块
各自独立导入自己的组件；import app.ui.windows.rapid_main_window 绝不能
连带导入 GGUF 的 keyword_* 模块，反之亦然。请按模块路径直接导入。
"""

__all__ = []
