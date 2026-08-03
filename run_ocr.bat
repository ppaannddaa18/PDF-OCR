@echo off
REM PaddleOCR-VL GGUF 模型启动脚本
REM 使用 llama-llava-cli 进行 OCR

echo ==========================================
echo PaddleOCR-VL GGUF 模型 OCR 脚本
echo ==========================================
echo.

REM 设置模型路径
set MODEL_PATH=models\PaddleOCR-VL-1.6-GGUF.gguf
set MMPROJ_PATH=models\PaddleOCR-VL-1.6-GGUF-mmproj.gguf

REM 检查模型文件
if not exist "%MODEL_PATH%" (
    echo Error: Model file not found: %MODEL_PATH%
    exit /b 1
)

if not exist "%MMPROJ_PATH%" (
    echo Error: MMProj file not found: %MMPROJ_PATH%
    exit /b 1
)

echo Model: %MODEL_PATH%
echo MMProj: %MMPROJ_PATH%
echo.

REM 检查命令行参数
if "%~1"=="" (
    echo Usage: %0 ^<image_path^> [prompt]
    echo.
    echo Example:
    echo   %0 test_image.png "OCR:"
    echo   %0 "C:\Users\Panda\OneDrive\桌面\L24040002报关单.pdf" "OCR:"
    exit /b 1
)

set IMAGE_PATH=%~1
set PROMPT=%~2

if "%PROMPT%"=="" set PROMPT=OCR:

echo Image: %IMAGE_PATH%
echo Prompt: %PROMPT%
echo.

REM 运行 OCR
llama-llava-cli.exe ^
    -m %MODEL_PATH% ^
    --mmproj %MMPROJ_PATH% ^
    --image "%IMAGE_PATH%" ^
    -p "%PROMPT%" ^
    --temp 0.0 ^
    -n 512

echo.
pause
