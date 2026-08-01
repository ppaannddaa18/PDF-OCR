"""
RapidMainWindow — RapidOCR 双界面（轻量浅色工作台，Task P3a）

MRO 契约（硬性，详见 base_window.py 顶部注释）：
    RapidMainWindow → AppBaseWindowMixin → MSFluentWindow → ... → QWidget

构造协议：
    _init_app_base(config)（纯数据）必须在 super().__init__() 之前；
    _post_init_base()（UI 部件）在 super().__init__() 之后。

引擎路径固定 rapid：config["ocr"]["engine"] 强制 'rapidocr'（get_ocr_engine
据此构造 RapidOCREngine；GGUF 分支由 GgufMainWindow（P4）承担）。
窗口固定浅色配色（design=rapid，强调色 #0C8CE9），不监听系统主题。
"""
import logging

from qfluentwidgets import MSFluentWindow

from app.ui.windows.base_window import AppBaseWindowMixin


class RapidMainWindow(AppBaseWindowMixin, MSFluentWindow):
    """RapidOCR 工作台：顶部标签 工作区 / 识别结果 / 历史记录"""

    WINDOW_TITLE = "PDF OCR — 文档工作台"
    WINDOW_ICON = 'fa5s.file-pdf'

    def __init__(self, config):
        # 固定 rapid 路径：config 引擎强制 rapidocr（构造期直接
        # get_ocr_engine 初始化按 rapid 路径，去掉 gguf 分支逻辑）
        config.setdefault("ocr", {})["engine"] = "rapidocr"
        self._init_app_base(config)  # pre-super：纯数据（config/世代/shutting_down/design）
        super().__init__()
        logging.getLogger("PDFOCR").info(
            f"Session start | engine={self.engine_type} | design={self.design} | window=RapidMainWindow")
        self._post_init_base()  # post-super：UI 部件（页面/导航/引擎异步初始化）
