"""
程序入口 - 优化启动速度
"""
import sys


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

    # 异步初始化日志（不阻塞启动）
    setup_logger()

    # 加载配置（自动查找，支持PyInstaller打包）
    config = load_config()

    # CPU VLM模式: 必须在导入paddle之前设置，否则PaddlePaddle内部Place(undefined:0)崩溃
    engine_type = config.get("ocr", {}).get("engine", "rapidocr")
    if engine_type == "paddleocr_vl_cpu":
        import os
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

    from app.ui.main_window import MainWindow

    # 设置 Fluent 主题强调色
    setThemeColor('#4a90d9')

    # 阶段4：创建主窗口
    try:
        window = MainWindow(config)
    finally:
        # 确保启动画面关闭
        if splash:
            splash.close()

    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
