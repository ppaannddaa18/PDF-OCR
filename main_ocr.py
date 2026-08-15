"""PaddleOCR-VL 独立文档识别程序入口（venv-paddle 环境运行）"""
import importlib.util
import sys
from typing import Optional


def check_paddle_environment() -> Optional[str]:
    """检查 paddle/paddleocr 是否可导入。

    返回缺失依赖的描述文案（含解决指引），全部齐全时返回 None。
    纯函数，不依赖 QApplication，便于单元测试。
    """
    missing = [m for m in ("paddle", "paddleocr")
               if importlib.util.find_spec(m) is None]
    if not missing:
        return None
    names = "、".join(missing)
    return (
        f"缺少 Python 包：{names}\n\n"
        "当前环境未安装 PaddleOCR-VL 运行所需依赖，无法使用 PaddleOCR-VL 引擎。\n"
        "请改用 venv-paddle 环境运行本程序：\n\n"
        "    run_ocr.bat"
    )


def main():
    from PyQt6.QtWidgets import QApplication, QMessageBox
    from PyQt6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    problem = check_paddle_environment()
    if problem is not None:
        QMessageBox.critical(None, "缺少依赖", problem)
        sys.exit(1)

    from app.utils.logger import setup_logger
    from app.utils.config_loader import load_config
    setup_logger()
    config = load_config()
    config.setdefault("ocr", {})["engine"] = "paddle_vl"  # 固定引擎

    from app.ui.windows.ocr_main_window import OcrMainWindow
    window = OcrMainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
