"""
配置加载器 - 支持PyInstaller打包
"""
import yaml
import sys
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
        return get_default_config()

    with open(config_path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def get_default_config() -> dict:
    """返回默认配置"""
    return {
        "app": {
            "name": "PDF OCR Tool",
            "version": "1.0.0",
            "window_size": [1600, 1000]
        },
        "pdf": {
            "render_dpi": 200
        },
        "ocr": {
            "lang": "ch",
            "use_gpu": False,
            "use_angle_cls": True,
            "det_db_box_thresh": 0.5,
            "drop_score": 0.5
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
