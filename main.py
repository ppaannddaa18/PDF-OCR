"""
程序入口 - 优化启动速度
"""
import sys
from pathlib import Path


def main():
    # 阶段1：最小化初始导入，快速创建QApplication
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt

    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)

    # 阶段2：显示启动画面（可选，提升用户体验）
    splash = None
    try:
        # 创建简单的启动提示
        from PyQt6.QtWidgets import QLabel, QVBoxLayout, QWidget
        splash = QWidget()
        splash.setFixedSize(300, 100)
        splash.setWindowTitle("PDF OCR Tool")
        layout = QVBoxLayout(splash)
        label = QLabel("正在加载...")
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(label)
        splash.show()
        app.processEvents()
    except Exception:
        pass

    # 阶段3：延迟加载重型模块
    from qfluentwidgets import setThemeColor
    from app.utils.logger import setup_logger
    from app.utils.config_loader import load_config
    from app.ui.main_window import MainWindow

    # 异步初始化日志（不阻塞启动）
    setup_logger()

    # 加载配置
    config_path = Path(__file__).parent / "config.yaml"
    config = load_config(str(config_path))

    # 设置 Fluent 主题强调色
    setThemeColor('#4a90d9')

    # 阶段4：创建主窗口
    window = MainWindow(config)

    # 关闭启动画面
    if splash:
        splash.close()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
