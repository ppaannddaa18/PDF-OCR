"""main_ocr.check_paddle_environment 纯函数测试（不依赖 QApplication / GUI 弹窗）"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import main_ocr


def test_environment_ok_returns_none(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: object())
    assert main_ocr.check_paddle_environment() is None


def test_environment_missing_both(monkeypatch):
    monkeypatch.setattr("importlib.util.find_spec", lambda name: None)
    msg = main_ocr.check_paddle_environment()
    assert msg is not None
    assert "缺少 Python 包：paddle、paddleocr" in msg
    assert "venv-paddle" in msg and "run_ocr.bat" in msg


def test_environment_missing_one(monkeypatch):
    def fake_find_spec(name):
        return None if name == "paddleocr" else object()

    monkeypatch.setattr("importlib.util.find_spec", fake_find_spec)
    msg = main_ocr.check_paddle_environment()
    assert msg is not None
    assert "缺少 Python 包：paddleocr" in msg  # 只列缺失项，不含 paddle
    assert "run_ocr.bat" in msg
