"""
GGUF OCR 引擎 — 基于 llama.cpp 的 PaddleOCR-VL GGUF 模型
通过 HTTP API 调用本地 llama-server 进行 OCR 识别
"""
import os
import base64
import json
import logging
import subprocess
import tempfile
import time
import threading
import requests
import atexit
from typing import Tuple, Dict, List, Any, Optional
from PIL import Image
import numpy as np

from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher
from app.models.page_result import PageResult, Block

logger = logging.getLogger("PDFOCR")


class _DummyRegion:
    """虚拟Region用于单图识别（recognize方法）"""
    __slots__ = ('id', 'field_name', 'x', 'y', 'w', 'h',
                 '_pixel_bbox', 'match_keywords', 'match_mode', 'ocr_mode')

    def __init__(self, width, height, mode="general"):
        self.id = "__single__"
        self.field_name = "text"
        self.x = 0.0
        self.y = 0.0
        self.w = 1.0
        self.h = 1.0
        self._pixel_bbox = [0, 0, width, height]
        self.match_keywords = []
        self.match_mode = "value"
        self.ocr_mode = mode


def _cleanup_gguf_server():
    """atexit 回调：进程退出时自动停止 llama-server"""
    engine = GGUFOCREngine._instance
    if engine is not None:
        try:
            engine._stop_server()
        except Exception:
            pass


def _blocks_to_elements(blocks: List[Block]) -> List[dict]:
    """将 Block[] 转换为 FieldMatcher 兼容的 elements dict 格式"""
    return [
        {
            "type": b.block_type,
            "text": b.content,
            "confidence": b.confidence,
            "bbox": b.bbox if b.bbox != [0, 0, 0, 0] else None,
        }
        for b in blocks
    ]


class GGUFOCREngine(OCREngineBase):
    """
    GGUF OCR 引擎 — 使用 llama.cpp 的 HTTP API

    特性:
    - 自动管理 llama-server 进程
    - GPU 加速（通过 -ngl 参数）
    - 支持整页识别和区域匹配
    """

    _instance: Optional['GGUFOCREngine'] = None
    _lock = threading.Lock()

    @classmethod
    def reset_instance(cls):
        """重置单例，允许重新初始化（用于引擎切换）"""
        with cls._lock:
            if cls._instance is not None:
                try:
                    cls._instance.unload()
                except Exception:
                    pass
            cls._instance = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __del__(self):
        """析构函数：对象被销毁时停止 llama-server"""
        try:
            self._stop_server()
        except Exception:
            pass

    def __init__(self, config: dict):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return

            self._config = config
            gguf_cfg = config.get("ocr", {}).get("gguf", {})

            # 服务器配置
            self._server_path = gguf_cfg.get("server_path", "llama-b9969/llama-server.exe")
            self._model_path = gguf_cfg.get("model_path", "models/PaddleOCR-VL-1.6-GGUF.gguf")
            self._mmproj_path = gguf_cfg.get("mmproj_path", "models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf")
            self._port = gguf_cfg.get("port", 8080)
            self._host = gguf_cfg.get("host", "127.0.0.1")
            self._device = gguf_cfg.get("device", "gpu")  # "gpu" 或 "cpu"

            # 根据设备设置 GPU 层数
            if self._device == "cpu":
                self._n_gpu_layers = 0  # CPU 模式：不卸载到 GPU
                self._mmproj_offload = False
            else:
                self._n_gpu_layers = gguf_cfg.get("n_gpu_layers", 999)  # GPU 模式：全部卸载
                self._mmproj_offload = gguf_cfg.get("mmproj_offload", True)

            self._max_tokens = gguf_cfg.get("max_tokens", 2048)
            self._temperature = gguf_cfg.get("temperature", 0.0)

            # 解析配置参数
            self._parse_auxiliary = gguf_cfg.get("auxiliary_parsing", {})
            self._model_params = gguf_cfg.get("model_params", {})
            self._layout_geometry = gguf_cfg.get("layout_geometry", "auto")
            self._prompt_type = gguf_cfg.get("prompt_type", "text")
            self._repetition_penalty = gguf_cfg.get("repetition_penalty", 1.00)
            self._stability = gguf_cfg.get("stability", 0.00)
            self._confidence_threshold = gguf_cfg.get("confidence_threshold", 1.0)
            self._min_pixels = gguf_cfg.get("min_pixels", 147384)
            self._max_pixels = gguf_cfg.get("max_pixels", 2822400)
            self._nms_postprocess = gguf_cfg.get("nms_postprocess", True)
            self._timeout = gguf_cfg.get("timeout_seconds", 120)

            # 状态
            self._server_process: Optional[subprocess.Popen] = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._server_lock = threading.RLock()
            self._last_used_time = time.monotonic()
            self._idle_unload_seconds = gguf_cfg.get("idle_unload_seconds", 300)

            # 匹配器
            self._matcher = FieldMatcher(config)

            self._initialized_flag = True
            # 注册进程退出时的清理回调
            atexit.register(_cleanup_gguf_server)

    def _find_server_exe(self) -> str:
        """查找 llama-server.exe 路径"""
        # 获取程序根目录（main.py 所在目录）
        import sys
        if getattr(sys, 'frozen', False):
            # PyInstaller 打包后的路径
            base_dir = os.path.dirname(sys.executable)
        else:
            # 开发环境路径
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        possible_paths = [
            self._server_path,
            os.path.join(base_dir, "llama-b9969", "llama-server.exe"),
            os.path.join(base_dir, self._server_path),
            "llama-b9969/llama-server.exe",
            "./llama-b9969/llama-server.exe",
            "../llama-b9969/llama-server.exe",
            "../../llama-b9969/llama-server.exe",
        ]

        for path in possible_paths:
            if os.path.exists(path):
                return os.path.abspath(path)

        # 搜索 PATH
        for path_dir in os.environ.get("PATH", "").split(os.pathsep):
            full_path = os.path.join(path_dir, "llama-server.exe")
            if os.path.exists(full_path):
                return os.path.abspath(full_path)

        raise FileNotFoundError("llama-server.exe not found")

    def _resolve_model_path(self, path: str) -> str:
        """解析模型路径（支持相对路径和绝对路径）"""
        if os.path.isabs(path):
            return path

        # 获取程序根目录
        import sys
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

        # 尝试相对根目录的路径
        full_path = os.path.join(base_dir, path)
        if os.path.exists(full_path):
            return os.path.abspath(full_path)

        # 尝试当前工作目录
        if os.path.exists(path):
            return os.path.abspath(path)

        return os.path.abspath(full_path)  # 返回绝对路径（即使不存在）

    def _start_server(self) -> bool:
        """启动 llama-server 进程"""
        try:
            server_exe = self._find_server_exe()
            model_path = self._resolve_model_path(self._model_path)
            mmproj_path = self._resolve_model_path(self._mmproj_path)

            # 检查模型文件
            if not os.path.exists(model_path):
                raise FileNotFoundError(f"Model not found: {model_path}")
            if not os.path.exists(mmproj_path):
                raise FileNotFoundError(f"MMProj not found: {mmproj_path}")

            cmd = [
                server_exe,
                "-m", model_path,
                "--mmproj", mmproj_path,
                "--port", str(self._port),
                "--host", self._host,
                "--temp", str(self._temperature),
                "-n", str(self._max_tokens),
                "-ngl", str(self._n_gpu_layers),
            ]

            if self._mmproj_offload:
                cmd.append("--mmproj-offload")

            logger.info(f"Starting llama-server: {' '.join(cmd)}")

            # 设置工作目录为 llama-server 所在目录，确保能找到 DLL
            server_dir = os.path.dirname(server_exe)
            env = os.environ.copy()
            # 将 server 目录添加到 PATH
            current_path = env.get("PATH", "")
            if server_dir not in current_path:
                env["PATH"] = server_dir + os.pathsep + current_path

            # 确保日志目录存在
            import sys
            if getattr(sys, 'frozen', False):
                base_dir = os.path.dirname(sys.executable)
            else:
                base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            os.makedirs(os.path.join(base_dir, "logs"), exist_ok=True)
            log_path = os.path.join(base_dir, "logs", "llama-server.log")
            log_file = open(log_path, "a", encoding="utf-8", errors="replace")
            self._server_log_file = log_file
            logger.info(f"llama-server output → {log_path}")

            # 启动进程（创建新进程组，确保可以整体终止）
            self._server_process = subprocess.Popen(
                cmd,
                stdout=log_file,
                stderr=log_file,
                text=True,
                cwd=server_dir,
                env=env,
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    | subprocess.CREATE_NEW_PROCESS_GROUP
                ) if os.name == 'nt' else 0
            )

            # 等待服务器就绪
            if not self._wait_for_server(timeout=60):
                logger.error("llama-server failed to start")
                self._stop_server()
                return False

            logger.info(f"llama-server started on {self._host}:{self._port}")
            return True

        except Exception as e:
            logger.error(f"Failed to start llama-server: {e}")
            self._init_error = str(e)
            return False

    def _wait_for_server(self, timeout: int = 60) -> bool:
        """等待服务器就绪"""
        start_time = time.time()
        url = f"http://{self._host}:{self._port}/health"

        while time.time() - start_time < timeout:
            if self._server_process is not None and self._server_process.poll() is not None:
                logger.error(f"llama-server exited during startup (code={self._server_process.returncode})")
                return False
            try:
                response = requests.get(url, timeout=1)
                if response.status_code == 200:
                    return True
            except requests.exceptions.ConnectionError:
                pass
            except Exception:
                pass
            time.sleep(0.5)

        return False

    def _stop_server(self) -> None:
        """停止 llama-server 进程"""
        if self._server_process is not None:
            proc = self._server_process
            try:
                import signal
                import sys
                if sys.platform == 'win32':
                    # Windows: 发送 CTRL_BREAK_EVENT 到整个进程组
                    try:
                        os.kill(proc.pid, signal.CTRL_BREAK_EVENT)
                    except (ProcessLookupError, OSError):
                        pass
                else:
                    # Unix: 发送 SIGTERM 到进程组
                    try:
                        os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
                    except (ProcessLookupError, OSError):
                        pass
                proc.wait(timeout=1)  # 缩短超时，快速回退到强制终止
            except subprocess.TimeoutExpired:
                # 强制终止 - Windows 使用 taskkill 处理进程树
                if sys.platform == 'win32':
                    try:
                        subprocess.run(
                            ['taskkill', '/F', '/T', '/PID', str(proc.pid)],
                            capture_output=True,
                            timeout=3
                        )
                    except Exception:
                        pass
                proc.kill()
                try:
                    proc.wait(timeout=2)
                except subprocess.TimeoutExpired:
                    pass
            except Exception as e:
                logger.warning(f"Error stopping server: {e}")
            finally:
                self._server_process = None
                if hasattr(self, '_server_log_file') and self._server_log_file is not None:
                    try:
                        self._server_log_file.close()
                    except Exception:
                        pass
                    self._server_log_file = None
                logger.info("llama-server stopped")

    def terminate_async(self, callback=None) -> None:
        """异步终止服务器，在后台线程中执行"""
        def _do_stop():
            self._stop_server()
            self._initialized = False
            if callback:
                try:
                    callback()
                except Exception:
                    pass
        import threading
        threading.Thread(target=_do_stop, daemon=False, name="GGUF-Shutdown").start()

    def _ensure_server_running(self) -> bool:
        """确保服务器正在运行"""
        with self._server_lock:
            if self._server_process is None or self._server_process.poll() is not None:
                return self._start_server()
            return True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用）"""
        if self._initialized:
            return

        with self._server_lock:
            if self._initialized:
                return

            try:
                logger.info("GGUF OCR engine initializing...")

                # 检查模型文件
                resolved_model = self._resolve_model_path(self._model_path)
                resolved_mmproj = self._resolve_model_path(self._mmproj_path)
                if not os.path.exists(resolved_model):
                    raise FileNotFoundError(f"Model not found: {resolved_model}")
                if not os.path.exists(resolved_mmproj):
                    raise FileNotFoundError(f"MMProj not found: {resolved_mmproj}")

                # 启动服务器
                if not self._start_server():
                    raise RuntimeError("Failed to start llama-server")

                self._initialized = True
                self._last_used_time = time.monotonic()
                logger.info("GGUF OCR engine initialized successfully")

            except Exception as e:
                logger.error(f"GGUF initialization failed: {e}")
                self._init_error = str(e)
                self._stop_server()

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "gguf"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def unload(self) -> None:
        """卸载模型释放资源"""
        with self._server_lock:
            self._stop_server()
            self._initialized = False

    def _image_to_base64(self, image: Image.Image) -> str:
        """将 PIL Image 转换为 base64，支持像素限制预处理"""
        import io

        # 根据 min_pixels / max_pixels 参数调整图像大小
        current_pixels = image.width * image.height
        if current_pixels < self._min_pixels:
            # 图像太小，按比例放大
            scale = (self._min_pixels / current_pixels) ** 0.5
            new_width = int(image.width * scale)
            new_height = int(image.height * scale)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.debug(f"图像放大: {image.width}x{image.height} -> {new_width}x{new_height} "
                        f"(像素: {current_pixels} -> {new_width * new_height})")
        elif current_pixels > self._max_pixels:
            # 图像太大，按比例缩小
            scale = (self._max_pixels / current_pixels) ** 0.5
            new_width = int(image.width * scale)
            new_height = int(image.height * scale)
            image = image.resize((new_width, new_height), Image.LANCZOS)
            logger.debug(f"图像缩小: {image.width}x{image.height} -> {new_width}x{new_height} "
                        f"(像素: {current_pixels} -> {new_width * new_height})")

        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        return base64.b64encode(buffered.getvalue()).decode()

    def _build_prompt(self, mode: str = "general") -> str:
        """
        根据配置构建 OCR prompt

        Args:
            mode: 识别模式，"general" 或特定类型

        Returns:
            构建好的 prompt 字符串
        """
        # 基础指令 - 根据 prompt_type 选择
        type_instructions = {
            "text": "请识别图片中的所有文本内容，保持原始排版格式。",
            "formula": "请识别图片中的数学公式，使用 LaTeX 格式输出。",
            "table": "请识别图片中的表格内容，输出为 Markdown 表格格式。",
            "chart": "请识别图片中的图表内容，描述图表类型和数据。",
            "seal": "请识别图片中的印章内容，提取印章文字。",
            "detection": "请检测并识别图片中的所有文本区域，输出每个区域的坐标和文字内容。"
        }

        # mode 优先（recognize(mode='single_line') 等未映射值回退到
        # 配置的 prompt_type，行为与改造前一致）
        prompt_type = type_instructions.get(mode) or type_instructions.get(
            self._prompt_type, "请识别图片中的文本内容。")
        parts = [prompt_type]

        # 辅助内容解析指令
        aux = self._parse_auxiliary
        aux_parts = []
        if aux.get("header"):
            aux_parts.append("页眉")
        if aux.get("footer"):
            aux_parts.append("页脚")
        if aux.get("page_number"):
            aux_parts.append("页码")
        if aux.get("footnote"):
            aux_parts.append("脚注")
        if aux.get("margin_text"):
            aux_parts.append("旁注")
        if aux.get("header_image"):
            aux_parts.append("页眉图片")
        if aux.get("footer_image"):
            aux_parts.append("页脚图片")

        if aux_parts:
            parts.append(f"注意识别并保留以下辅助内容：{', '.join(aux_parts)}。")

        # 模型参数指令
        model = self._model_params
        model_parts = []
        if model.get("orientation_correction"):
            model_parts.append("矫正图片方向")
        if model.get("distortion_correction"):
            model_parts.append("矫正图片扭曲")
        if model.get("layout_analysis"):
            model_parts.append("进行版面分析")
        if model.get("chart_recognition"):
            model_parts.append("识别图表")
        if model.get("seal_recognition"):
            model_parts.append("识别印章")
        if model.get("image_text_recognition"):
            model_parts.append("识别图片中的文字")
        if model.get("cross_page_table_merge"):
            model_parts.append("合并跨页表格")
        if model.get("heading_level_recognition"):
            model_parts.append("识别标题级别")

        if model_parts:
            parts.append(f"执行以下操作：{', '.join(model_parts)}。")

        # 几何形状
        geometry_instructions = {
            "auto": "",
            "rectangle": "使用矩形框标注文本区域。",
            "quadrilateral": "使用四边形框标注文本区域。",
            "polygon": "使用多边形框精确标注文本区域。"
        }
        geo = geometry_instructions.get(self._layout_geometry, "")
        if geo:
            parts.append(geo)

        # NMS 后处理
        if self._nms_postprocess:
            parts.append("应用 NMS 后处理去除重叠框。")

        # 稳定性与置信度要求
        if self._stability > 0:
            parts.append(f"保持识别稳定性（重要性：{self._stability:.2f}）。")

        if self._confidence_threshold < 1.0:
            parts.append(f"只输出置信度高于 {self._confidence_threshold:.2f} 的结果。")

        # 像素限制提示
        if self._min_pixels > 0 or self._max_pixels < 9999999:
            parts.append(f"处理像素范围：{self._min_pixels} ~ {self._max_pixels}。")

        return " ".join(parts)

    def _call_ocr_api(self, image: Image.Image, prompt: str = None) -> Optional[str]:
        """调用 OCR API"""
        try:
            url = f"http://{self._host}:{self._port}/v1/chat/completions"

            image_data = self._image_to_base64(image)

            # 使用配置的 prompt
            if prompt is None:
                prompt = self._build_prompt()

            # 构建 API 参数
            api_params = {
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                "top_p": max(0.01, 1.0 - self._stability),  # stability 越高，top_p 越低
                "frequency_penalty": (self._repetition_penalty - 1.0) * 2.0,
                "presence_penalty": 0.0,
            }

            # 记录实际使用的参数（用于验证设置是否生效）
            logger.info(f"GGUF OCR 参数: prompt_type={self._prompt_type}, "
                       f"temperature={self._temperature}, max_tokens={self._max_tokens}, "
                       f"stability={self._stability}, top_p={api_params['top_p']:.2f}, "
                       f"repetition_penalty={self._repetition_penalty}, "
                       f"frequency_penalty={api_params['frequency_penalty']:.2f}, "
                       f"layout_geometry={self._layout_geometry}, "
                       f"nms_postprocess={self._nms_postprocess}, "
                       f"prompt_length={len(prompt)}")

            payload = {
                "model": "PaddleOCR-VL-1.6",
                "messages": [
                    {
                        "role": "user",
                        "content": [
                            {"type": "text", "text": prompt},
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/png;base64,{image_data}"
                                }
                            }
                        ]
                    }
                ],
                **api_params,
            }

            # 记录完整的 prompt（调试用，限制长度）
            debug_prompt = prompt[:200] + "..." if len(prompt) > 200 else prompt
            logger.debug(f"GGUF OCR prompt: {debug_prompt}")

            t0 = time.monotonic()
            response = requests.post(url, json=payload, timeout=self._timeout)
            response.raise_for_status()

            result = response.json()
            content = result["choices"][0]["message"]["content"]
            elapsed = time.monotonic() - t0
            if content:
                logger.info(f"GGUF OCR 响应: {response.status_code} | "
                            f"{len(response.content)} bytes | {len(content)} chars | "
                            f"耗时 {elapsed:.1f}s | 摘要: {content[:100]!r}")
            else:
                logger.info(f"GGUF OCR 响应: {response.status_code} | "
                            f"{len(response.content)} bytes | 0 chars | "
                            f"耗时 {elapsed:.1f}s | content 为空")
            return content

        except requests.exceptions.ConnectionError as e:
            logger.error("Cannot connect to llama-server")
            raise RuntimeError("无法连接 llama-server（请检查服务器是否启动）") from e
        except requests.exceptions.Timeout as e:
            logger.error(f"OCR request timeout ({self._timeout}s)")
            raise RuntimeError(f"OCR 请求超时（{self._timeout}s）") from e
        except Exception as e:
            logger.error(f"OCR API error: {e}")
            raise RuntimeError(f"OCR API 错误: {e}") from e

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """单图识别 - 使用配置构建的 prompt"""
        self._ensure_loaded()

        # 使用 _build_prompt() 构建的 prompt，传入 mode 参数
        prompt = self._build_prompt(mode=mode)
        text = self._call_ocr_api(image, prompt)
        if text:
            return text, 0.95
        return "", 0.0

    def recognize_page_auto(self, image: Image.Image) -> PageResult:
        """
        整页自动解析 - 使用配置构建的 prompt
        """
        self._ensure_loaded()
        t0 = time.monotonic()
        W, H = image.size

        try:
            # 使用 _build_prompt() 构建的 prompt
            prompt = self._build_prompt(mode="general")
            text = self._call_ocr_api(image, prompt)

            if not text:
                raise RuntimeError("OCR 服务无响应（请检查 llama-server 状态）")

            # 根据 confidence_threshold 调整置信度
            # GGUF 模型没有逐字置信度，使用整体置信度
            base_confidence = 0.95
            if self._confidence_threshold > 0 and self._confidence_threshold < 1.0:
                # 如果设置了阈值，调整输出置信度
                # 阈值越低，置信度越高（因为更容易满足条件）
                adjusted_confidence = base_confidence * (1.0 - self._confidence_threshold * 0.5)
            else:
                adjusted_confidence = base_confidence

            # 创建简单的 Block
            blocks = [Block(
                block_type="text",
                content=text,
                confidence=adjusted_confidence,
                bbox=[0, 0, W, H]
            )]

            elapsed = (time.monotonic() - t0) * 1000
            logger.info(f"GGUF 页面解析完成: {len(blocks)} blocks, {elapsed:.0f}ms, 文本 {len(text)} 字符")
            return PageResult(
                blocks=blocks,
                markdown=text,
                tables=[],
                raw_json={},
                image_size=(W, H),
                inference_time_ms=elapsed,
            )

        except Exception as e:
            logger.error(f"GGUF page recognition failed: {e}")
            raise

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — 委托给 recognize_page_auto，从 PageResult.blocks 做 FieldMatcher 匹配
        """
        self._ensure_loaded()
        W, H = image.size

        # 为每个 region 计算像素坐标
        pixel_bboxes = {}
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            pixel_bboxes[region.id] = [left, top, right, bottom]

        # 调用 auto 路径获取统一的 Block[] + Markdown
        page_result = self.recognize_page_auto(image)

        if not page_result.blocks:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # Block → elements dict 格式
        elements = _blocks_to_elements(page_result.blocks)

        # 三级匹配
        match_results = self._matcher.match(elements, regions, page_result.markdown, pixel_bboxes)

        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)

        return results

    def _ensure_loaded(self) -> None:
        """确保模型已加载（支持空闲后重新加载）"""
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError(f"GGUF initialization failed: {self._init_error}")
        self._last_used_time = time.monotonic()
