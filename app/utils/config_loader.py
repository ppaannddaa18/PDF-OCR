"""
配置加载器 - 支持PyInstaller打包
"""
import yaml
import sys
import os
from pathlib import Path


def get_base_path() -> Path:
    """
    获取基础路径（支持PyInstaller打包）

    PyInstaller打包后，资源文件在 sys._MEIPASS 目录下
    """
    if getattr(sys, 'frozen', False):
        # PyInstaller打包后运行
        return Path(sys._MEIPASS)
    else:
        # 正常Python运行
        return Path(__file__).parent.parent


def load_config(path: str = None) -> dict:
    """
    加载配置文件

    Args:
        path: 配置文件路径，如果为None则自动查找

    Returns:
        配置字典
    """
    if path is None:
        # 自动查找配置文件
        base_path = get_base_path()
        config_path = base_path / "config.yaml"
    else:
        config_path = Path(path)

    # 如果配置文件不存在，返回默认配置
    if not config_path.exists():
        config = get_default_config()
    else:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        if config is None:
            config = {}

    # 启动器环境变量覆盖（优先级高于配置文件）
    env_engine = os.environ.get("PDFOCR_ENGINE", "")
    if env_engine in ("paddleocr_vl", "rapidocr"):
        config.setdefault("ocr", {})["engine"] = env_engine

    return config


def get_default_config() -> dict:
    """返回默认配置"""
    return {
        "app": {
            "name": "PDF OCR Tool",
            "version": "2.0.0",
            "window_size": [1600, 1000]
        },
        "pdf": {
            "render_dpi": 200
        },
        "ocr": {
            "engine": "paddleocr_vl",       # "paddleocr_vl" | "rapidocr"
            "lang": "ch",
            "use_gpu": True,
            "use_angle_cls": True,
            "det_db_box_thresh": 0.5,
            "drop_score": 0.5,
            # PaddleOCR-VL 专属（官方 API: PaddleOCRVL(vl_rec_model_name, device, precision)）
            "paddleocr_vl": {
                "vl_rec_model_name": "PaddleOCR-VL-1.6-0.9B",
                "device": "gpu:0",
                "precision": "fp16",
                "warmup_on_startup": True,
                "idle_unload_seconds": 300,
                "page_dpi": 200,
                "high_quality_dpi": 300,
                "match_iou_threshold": 0.5,
                "match_neighbor_radius": 50,
            },
            # RapidOCR 专属
            "rapidocr": {
                "use_gpu": False,
                "lang": "ch",
                "det_db_box_thresh": 0.3,
                "drop_score": 0.5,
            },
        },
        "batch": {
            "max_workers": 4,
            "retry_times": 2
        },
        "export": {
            "default_format": "xlsx",
            "include_confidence": True
        }
    }
