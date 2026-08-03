@echo off
REM PaddleOCR-VL GGUF 模型启动脚本 (CUDA GPU 加速版)
REM 使用 llama-server 提供 OCR 服务

echo ==========================================
echo PaddleOCR-VL GGUF 模型启动脚本 (GPU 加速)
echo ==========================================
echo.

REM 设置模型路径
set MODEL_PATH=models\PaddleOCR-VL-1.6-GGUF.gguf
set MMPROJ_PATH=models\PaddleOCR-VL-1.6-GGUF-mmproj.gguf
set PORT=8080

REM 设置 llama-b9969 目录（包含 CUDA 版本的 DLL）
set LLAMA_DIR=llama-b9969

REM 检查模型文件
if not exist "%MODEL_PATH%" (
    echo Error: Model file not found: %MODEL_PATH%
    exit /b 1
)

if not exist "%MMPROJ_PATH%" (
    echo Error: MMProj file not found: %MMPROJ_PATH%
    exit /b 1
)

REM 检查 CUDA DLL
if not exist "%LLAMA_DIR%\ggml-cuda.dll" (
    echo Warning: CUDA DLL not found, falling back to CPU mode
    set GPU_ARGS=
) else (
    echo CUDA GPU acceleration enabled
    set GPU_ARGS=-ngl 999 --mmproj-offload
)

echo Model: %MODEL_PATH%
echo MMProj: %MMPROJ_PATH%
echo Port: %PORT%
echo.

REM 启动 llama-server
echo Starting llama-server...
echo.

%LLAMA_DIR%\llama-server.exe ^
    -m %MODEL_PATH% ^
    --mmproj %MMPROJ_PATH% ^
    --port %PORT% ^
    --temp 0.0 ^
    -n 512 ^
    --host 127.0.0.1 ^
    %GPU_ARGS%

echo.
echo Server stopped.
pause
