"""
程序入口 - 优化启动速度

启动流程：QApplication → splash → load_config → choose_engine（引擎选择）
→ 选 GGUF 才注入 llama-b9969 PATH → 构造主窗口
"""
import logging
import os
import sys


def _normalize_engine(choice: str) -> str:
    """对话框卡片 key（'gguf'|'rapid'）→ 配置权威值（'gguf'|'rapidocr'）"""
    return "rapidocr" if choice == "rapid" else choice


def _show_engine_dialog(config) -> str:
    """弹出引擎选择对话框，返回卡片 key（'gguf'|'rapid'）；rejected 时退出程序"""
    from PyQt6.QtWidgets import QApplication, QDialog
    from app.ui.engine_select_dialog import EngineSelectDialog
    from app.utils.engine_checker import check_engine_availability

    dialog = EngineSelectDialog(config)
    dialog.set_availability(check_engine_availability(config))
    if dialog.exec() != QDialog.DialogCode.Accepted:
        # Esc / 关闭 = 退出程序，绝不静默带默认值进入
        QApplication.quit()
        sys.exit(0)
    return dialog.selected_engine()


def choose_engine(config) -> str:
    """
    返回 'gguf' | 'rapidocr'。PDFOCR_ENGINE 环境变量直通；否则弹 EngineSelectDialog 强制选择。

    - PDFOCR_ENGINE 只认 gguf/rapidocr，其他值忽略 → 弹窗（与 config_loader 语义一致）
    - env 存在时不弹窗直接返回（不构造对话框）
    - 对话框 Accepted 后写入内存 config["ocr"]["engine"]（归一化为权威值），不写回 config.yaml
    - 对话框 rejected → 退出程序（QApplication.quit() + sys.exit(0)），绝不静默带默认值进入
    """
    env_engine = os.environ.get("PDFOCR_ENGINE", "")
    if env_engine in ("gguf", "rapidocr"):
        config.setdefault("ocr", {})["engine"] = env_engine
        return env_engine

    choice = _show_engine_dialog(config)
    config.setdefault("ocr", {})["engine"] = _normalize_engine(choice)
    return config["ocr"]["engine"]


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
    from app.utils.logger import setup_logger
    from app.utils.config_loader import load_config

    # 异步初始化日志（不阻塞启动）
    setup_logger()
    logger = logging.getLogger("PDFOCR")

    # 加载配置（自动查找，支持PyInstaller打包）
    config = load_config()

    # 关闭启动画面，进入引擎选择
    if splash:
        splash.close()

    engine = choose_engine(config)
    logger.info("Session start | engine=%s", engine)

    # 选 GGUF 才执行 llama-b9969 PATH 注入（CUDA DLL）
    if engine == "gguf":
        llama_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "llama-b9969")
        if os.path.exists(llama_dir):
            # 将llama-b9969目录添加到PATH，确保能找到CUDA DLL
            current_path = os.environ.get("PATH", "")
            if llama_dir not in current_path:
                os.environ["PATH"] = llama_dir + os.pathsep + current_path
                print(f"[GGUF] Added {llama_dir} to PATH")

    # 阶段4：按引擎构造对应窗口（P4 起新双界面；旧 MainWindow 保留至 P7 供回滚）
    if engine == "gguf":
        from app.ui.windows.gguf_main_window import GgufMainWindow
        window = GgufMainWindow(config)
    else:
        from app.ui.windows.rapid_main_window import RapidMainWindow
        window = RapidMainWindow(config)
    try:
        window.show()
    finally:
        # 确保启动画面关闭
        if splash:
            splash.close()

    sys.exit(app.exec())


if __name__ == "__main__":
    main()
