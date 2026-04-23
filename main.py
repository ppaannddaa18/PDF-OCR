import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt
from qfluentwidgets import setThemeColor
from app.ui.main_window import MainWindow
from app.utils.logger import setup_logger
from app.utils.config_loader import load_config


def main():
    setup_logger()
    config_path = Path(__file__).parent / "config.yaml"
    config = load_config(str(config_path))

    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # 设置 Fluent 主题强调色
    setThemeColor('#4a90d9')

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
