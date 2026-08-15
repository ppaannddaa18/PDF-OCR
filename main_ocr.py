"""PaddleOCR-VL 独立文档识别程序入口（venv-paddle 环境运行）"""
import sys


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

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
