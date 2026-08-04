"""
配置加载器 - 支持PyInstaller打包
"""
import threading
import yaml
import sys
import os
import logging
from pathlib import Path

# 写盘锁：防止多线程并发写 config.yaml 写半截
_config_write_lock = threading.Lock()
_logger = logging.getLogger("PDFOCR")


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

    _validate_config(config)

    # 路径自愈：配置里的 GGUF 路径不存在、但仓库内默认布局存在时，
    # 用默认相对路径替换（内存级修复；防止旧进程/旧配置把 C:\llama 等
    # 失效绝对路径回写后，启动选择界面误报「依赖不完整」）。
    _repair_gguf_paths(config)

    # 启动器环境变量覆盖（优先级高于配置文件）
    env_engine = os.environ.get("PDFOCR_ENGINE", "")
    if env_engine in ("gguf", "rapidocr"):
        config.setdefault("ocr", {})["engine"] = env_engine

    return config


def _project_root() -> Path:
    """GGUF 相对路径的解析根（与 engine_checker / ocr_engine_gguf 语义一致）"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]


def _repair_gguf_paths(config: dict) -> bool:
    """修复失效的 GGUF server/model/mmproj 路径；返回是否有改动。"""
    gguf_cfg = config.get("ocr", {}).get("gguf")
    if not isinstance(gguf_cfg, dict):
        return False

    defaults = get_default_config()["ocr"]["gguf"]
    root = _project_root()
    changed = False

    for key in ("server_path", "model_path", "mmproj_path"):
        value = str(gguf_cfg.get(key, "") or "")
        if not value:
            continue

        candidate = Path(value)
        exists = candidate.is_absolute() and candidate.exists()
        if not exists and not candidate.is_absolute():
            exists = (root / value).exists() or candidate.exists()
        if exists:
            continue

        default = defaults[key]
        if (root / default).exists():
            _logger.warning(
                "GGUF 配置路径不存在，已自动修复为仓库内默认路径: %s -> %s",
                value, default,
            )
            gguf_cfg[key] = default
            changed = True

    return changed


def save_config(config: dict) -> None:
    """
    将配置写回 config.yaml（与 load_config 的读取路径一致）

    线程安全：加锁防止并发写盘写半截。双窗口（Gguf/Rapid）与设置页共用。
    """
    config_path = get_base_path() / "config.yaml"
    with _config_write_lock:
        with open(config_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(config, f, allow_unicode=True, default_flow_style=False)


def _validate_config(config: dict) -> None:
    """验证配置文件的必要键和类型，缺失时用默认值填充"""
    required_keys = {
        "app": dict,
        "pdf": dict,
        "ocr": dict,
        "batch": dict,
        "export": dict,
    }
    defaults = get_default_config()
    for key, expected_type in required_keys.items():
        if key not in config:
            config[key] = defaults.get(key, {})
        elif not isinstance(config[key], expected_type):
            raise ValueError(f"配置项 '{key}' 应为 {expected_type.__name__} 类型，实际为 {type(config[key]).__name__}")

    # 检查必要子键
    if "engine" not in config.get("ocr", {}):
        config.setdefault("ocr", {})["engine"] = "gguf"


def get_default_config() -> dict:
    """返回默认配置"""
    return {
        "app": {
            "name": "PDF OCR Tool",
            "version": "2.0.0",
            "window_size": [1600, 1000]
        },
        "pdf": {
            "render_dpi": 200,
            "max_preview_size": 2000,
        },
        "ocr": {
            "engine": "gguf",       # "gguf" | "rapidocr"
            "lang": "ch",
            "use_gpu": True,
            "use_angle_cls": True,
            "det_db_box_thresh": 0.5,
            "drop_score": 0.5,
            # GGUF 专属配置
            "gguf": {
                "device": "gpu",  # "gpu" 或 "cpu"
                "server_path": "llama-b9969/llama-server.exe",
                "model_path": "models/PaddleOCR-VL-1.6-GGUF.gguf",
                "mmproj_path": "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf",
                "port": 8080,
                "host": "127.0.0.1",
                "n_gpu_layers": 999,
                "mmproj_offload": True,
                "max_tokens": 2048,
                "temperature": 0.0,
                "idle_unload_seconds": 300,
                # 辅助内容解析
                "auxiliary_parsing": {
                    "header": False,
                    "footer": False,
                    "page_number": True,
                    "footnote": False,
                    "margin_text": False,
                    "header_image": False,
                    "footer_image": False,
                },
                # 模型参数设置
                "model_params": {
                    "orientation_correction": False,
                    "distortion_correction": False,
                    "layout_analysis": True,
                    "chart_recognition": True,
                    "seal_recognition": True,
                    "image_text_recognition": True,
                    "cross_page_table_merge": True,
                    "heading_level_recognition": True,
                },
                # 版面检测结果几何形状
                "layout_geometry": "auto",
                # prompt 类型
                "prompt_type": "text",
                # 滑块参数
                "repetition_penalty": 1.00,
                "stability": 0.00,
                "confidence_threshold": 1.0,
                "min_pixels": 147384,
                "max_pixels": 2822400,
                # NMS 后处理
                "nms_postprocess": True,
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
