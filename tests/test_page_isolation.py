"""Task P4 测试：双窗口 import 隔离（子进程内检查 sys.modules）

Rapid 窗口不得 import keyword_*；GGUF 窗口不得 import 模板工作区组件
（field_panel / pdf_canvas / compact_toolbar）。用独立子进程避免本
pytest 进程已被其他测试模块污染的 sys.modules。
"""
import os
import subprocess
import sys


def _run_check(code: str):
    env = dict(os.environ)
    env["QT_QPA_PLATFORM"] = "offscreen"
    proc = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, env=env, cwd=os.getcwd(),
        timeout=120,
    )
    assert proc.returncode == 0, (
        f"隔离检查失败:\nSTDOUT: {proc.stdout}\nSTDERR: {proc.stderr}"
    )
    return proc.stdout


def test_rapid_window_imports_no_keyword_modules():
    code = """
import sys
import app.ui.windows.rapid_main_window  # noqa: F401
bad = sorted(m for m in sys.modules if m.startswith("app.") and "keyword" in m.lower())
if bad:
    print("FORBIDDEN:", bad)
    sys.exit(1)
print("OK")
"""
    assert "OK" in _run_check(code)


def test_gguf_window_imports_no_workspace_modules():
    code = """
import sys
import app.ui.windows.gguf_main_window  # noqa: F401
bad = sorted(m for m in sys.modules
             if m.startswith("app.")
             and any(t in m for t in ("field_panel", "pdf_canvas", "compact_toolbar")))
if bad:
    print("FORBIDDEN:", bad)
    sys.exit(1)
print("OK")
"""
    assert "OK" in _run_check(code)
