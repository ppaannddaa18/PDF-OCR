"""
引擎可用性检查器 - 启动时轻量检查，结果作为引擎选择卡的依赖状态徽章

纯函数、无 GUI 依赖（可单测），不阻塞选择流程。

路径解析规则对齐 app/core/ocr_engine_gguf.py 的 _find_server_exe / _resolve_model_path：
- base_dir = 程序根目录（PyInstaller 打包后为 sys._MEIPASS / sys.executable 所在目录）
- 相对路径先按 base_dir 解析，再按当前工作目录解析
"""
import importlib.util
import os
import sys
from pathlib import Path


def _get_base_dir() -> Path:
    """程序根目录（与 ocr_engine_gguf._find_server_exe 的 base_dir 语义一致）"""
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[2]  # app/utils/engine_checker.py → 项目根


def _path_exists(path: str, base_dir: Path) -> bool:
    """路径存在性检查（对齐 _resolve_model_path：绝对直查，相对先 base_dir 再 cwd）"""
    p = Path(path)
    if p.is_absolute():
        return p.exists()
    return (base_dir / path).exists() or p.exists()


def _server_exe_findable(server_path: str, base_dir: Path) -> bool:
    """判定能否找到 llama-server.exe（模拟 _find_server_exe 的候选搜索顺序）"""
    # 1. server_path 原样（当前工作目录）
    if server_path and os.path.exists(server_path):
        return True
    # 2. base_dir/llama-b9969/llama-server.exe（默认布局）
    if (base_dir / "llama-b9969" / "llama-server.exe").exists():
        return True
    # 3. base_dir 下的 server_path
    if server_path and (base_dir / server_path).exists():
        return True
    # 4. PATH 兜底
    for path_dir in os.environ.get("PATH", "").split(os.pathsep):
        if path_dir and os.path.exists(os.path.join(path_dir, "llama-server.exe")):
            return True
    return False


def _check_gguf(gguf_cfg: dict) -> dict:
    """GGUF 引擎检查：server/model/mmproj 存在性为硬性项，ggml-cuda.dll 为警告级"""
    available = True
    issues = []

    server_path = str(gguf_cfg.get("server_path", "") or "")
    model_path = str(gguf_cfg.get("model_path", "") or "")
    mmproj_path = str(gguf_cfg.get("mmproj_path", "") or "")
    base_dir = _get_base_dir()

    if not _server_exe_findable(server_path, base_dir):
        available = False
        issues.append(f"未找到 llama-server.exe（server_path: {server_path or '未配置'}）")

    if not model_path:
        available = False
        issues.append("未配置模型路径 model_path")
    elif not _path_exists(model_path, base_dir):
        available = False
        issues.append(f"模型文件不存在: {model_path}")

    if not mmproj_path:
        available = False
        issues.append("未配置 MMProj 路径 mmproj_path")
    elif not _path_exists(mmproj_path, base_dir):
        available = False
        issues.append(f"MMProj 文件不存在: {mmproj_path}")

    # ggml-cuda.dll 缺失为警告级（GPU 推理可能失败，不阻塞选择）
    dll_dir = base_dir / "llama-b9969"
    if server_path and os.path.isabs(server_path):
        dll_dir = Path(os.path.dirname(server_path))
    if not (dll_dir / "ggml-cuda.dll").exists():
        issues.append(
            f"警告：{dll_dir / 'ggml-cuda.dll'} 缺失"
            "（GPU 推理可能失败；可到『模型设置』页修正路径，"
            "或切换设备为 CPU 后重启引擎）")

    return {"available": available, "issues": issues}


def _find_spec(name: str):
    """importlib.util.find_spec 封装（便于测试隔离）"""
    return importlib.util.find_spec(name)


def _check_rapidocr() -> dict:
    """RapidOCR 引擎检查：包可导入 + 构造可成功（构造不加载模型，速度快）"""
    if _find_spec("rapidocr_onnxruntime") is None:
        return {"available": False, "issues": ["未安装 rapidocr_onnxruntime 包"]}
    try:
        from rapidocr_onnxruntime import RapidOCR
        RapidOCR()
    except Exception as e:
        return {"available": False, "issues": [f"RapidOCR 初始化失败: {e}"]}
    return {"available": True, "issues": []}


def _check_paddle_vl(paddle_vl_cfg: dict) -> dict:
    """PaddleOCR-VL 引擎检查：paddleocr 官方管线可安装（隐含 paddle/paddlex）+ 模型目录存在"""
    issues = []
    if _find_spec("paddleocr") is None:
        issues.append("未安装 paddleocr 包（官方管线：pip install paddleocr paddlex）")
    if _find_spec("paddle") is None:
        issues.append("未安装 paddle（paddleocr 推理依赖，需 GPU 版）")
    if issues:
        return {"available": False, "issues": issues}

    # 模型目录：配置 → 默认探测路径（与 ocr_engine_paddle_vl._default_model_dir 一致）
    model_dir = str(paddle_vl_cfg.get("model_dir", "") or "")
    if model_dir:
        if not Path(model_dir).is_dir():
            return {"available": False,
                    "issues": [f"模型目录不存在: {model_dir}"]}
    else:
        home = Path.home()
        default_dir = home / ".paddlex" / "official_models" / "PaddleOCR-VL-1.6"
        if not default_dir.is_dir():
            return {"available": False,
                    "issues": [
                        "未找到模型目录（默认 "
                        f"{default_dir}），请下载 PaddleOCR-VL-1.6 官方权重"
                        "或到『模型设置』页配置 model_dir"]}
    return {"available": True, "issues": issues}


def check_engine_availability(config: dict) -> dict:
    """检查全部引擎可用性

    Args:
        config: load_config() 返回的配置字典

    Returns:
        {
            'gguf': {'available': bool, 'issues': [str]},
            'rapidocr': {'available': bool, 'issues': [str]},
        }
        available=False 的 issues 为硬性缺失；available=True 但带 issues 的为警告级。
    """
    gguf_cfg = config.get("ocr", {}).get("gguf", {})
    return {
        "gguf": _check_gguf(gguf_cfg),
        "rapidocr": _check_rapidocr(),
    }
