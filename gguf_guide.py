"""
PaddleOCR-VL GGUF 模型使用指南
===============================

由于 llama-cpp-python 在 Windows 上编译困难，推荐使用以下方案：

方案 1: 使用预编译的 llama-server.exe (推荐)
-------------------------------------------
1. 从 GitHub Releases 下载 Windows 预编译版本：
   https://github.com/ggerganov/llama.cpp/releases

2. 下载文件名格式：llama-bXXXX-bin-win-cuda-cu12.4.0-x64.zip

3. 解压后使用 llama-server.exe 启动服务：
   llama-server.exe -m models/PaddleOCR-VL-1.6-GGUF.gguf --mmproj models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf --port 8080

4. 通过 HTTP API 调用 OCR 服务

方案 2: 使用 Ollama
-------------------
1. 安装 Ollama: https://ollama.com/download

2. 创建 Modelfile：
   FROM models/PaddleOCR-VL-1.6-GGUF.gguf
   MMPROJ models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf

3. 创建模型：
   ollama create paddleocr-vl -f Modelfile

4. 运行模型：
   ollama run paddleocr-vl

方案 3: 使用 Python + ctypes 调用 DLL
--------------------------------------
如果预编译版本不可用，可以使用 ctypes 直接调用 llama.cpp 的 DLL。

当前状态
--------
- 模型文件: 已下载 (892.4 MB + 840.9 MB)
- llama-cli: 未安装
- llama-cpp-python: 编译失败 (缺少构建工具)

下一步建议
----------
1. 下载 llama-server.exe 预编译版本
2. 启动本地 OCR 服务
3. 修改现有代码，通过 HTTP API 调用服务
"""

import os
import subprocess
from pathlib import Path


def start_llama_server(model_path: str, mmproj_path: str, port: int = 8080):
    """
    启动 llama-server 服务
    注意: 需要先下载 llama-server.exe
    """
    # 查找 llama-server.exe
    llama_server = find_llama_server()

    if not llama_server:
        print("错误: 找不到 llama-server.exe")
        print("请从以下地址下载预编译版本：")
        print("https://github.com/ggerganov/llama.cpp/releases")
        return None

    cmd = [
        str(llama_server),
        "-m", model_path,
        "--mmproj", mmproj_path,
        "--port", str(port),
        "--temp", "0.0",
        "-n", "512"
    ]

    print(f"启动 llama-server: {' '.join(cmd)}")

    try:
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        return process
    except Exception as e:
        print(f"启动失败: {e}")
        return None


def find_llama_server() -> str:
    """查找 llama-server.exe"""
    # 常见位置
    possible_paths = [
        "llama-server.exe",
        "./llama-server.exe",
        "../llama-server.exe",
        "C:/Program Files/llama.cpp/llama-server.exe",
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    # 搜索 PATH
    for path in os.environ.get("PATH", "").split(os.pathsep):
        full_path = os.path.join(path, "llama-server.exe")
        if os.path.exists(full_path):
            return full_path

    return None


def ocr_with_api(image_path: str, prompt: str = "OCR:", port: int = 8080):
    """
    通过 HTTP API 调用 OCR 服务
    """
    import requests
    import base64

    # 读取图像并编码为 base64
    with open(image_path, "rb") as f:
        image_data = base64.b64encode(f.read()).decode()

    # 构建请求
    url = f"http://localhost:{port}/v1/chat/completions"

    payload = {
        "model": "PaddleOCR-VL-1.6",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_data}"}}
                ]
            }
        ],
        "temperature": 0.0,
        "max_tokens": 512
    }

    try:
        response = requests.post(url, json=payload, timeout=300)
        response.raise_for_status()
        result = response.json()
        return result["choices"][0]["message"]["content"]
    except Exception as e:
        print(f"API 调用失败: {e}")
        return None


if __name__ == "__main__":
    print(__doc__)
