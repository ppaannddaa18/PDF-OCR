import sys
from pathlib import Path
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.utils.logger import setup_logger
from app.utils.config_loader import load_config


def main():
    setup_logger()
    config_path = Path(__file__).parent / "config.yaml"
    config = load_config(str(config_path))

    app = QApplication(sys.argv)
    style_path = Path(__file__).parent / "app" / "ui" / "styles" / "app.qss"
    if style_path.exists():
        with open(style_path, "r", encoding="utf-8") as f:
            app.setStyleSheet(f.read())

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
