@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM PDFOCR 智能启动器
REM 默认使用 GPU 环境，不可用时回退到 CPU 环境

set "SCRIPT_DIR=%~dp0"
set "GPU_VENV=%SCRIPT_DIR%venv"
set "CPU_VENV=%SCRIPT_DIR%venv-cpu"
set "FORCE_CPU=0"

REM 检查命令行参数
if "%1"=="--cpu" set "FORCE_CPU=1"
if "%1"=="-c" set "FORCE_CPU=1"

if "%FORCE_CPU%"=="1" (
    echo [INFO] 强制使用CPU模式
    set "USE_VENV=%CPU_VENV%"
    set "PDFOCR_ENGINE=rapidocr"
    goto :check_venv
)

REM 检查GPU环境
if exist "%GPU_VENV%\Scripts\python.exe" (
    echo [INFO] 使用GPU环境
    set "USE_VENV=%GPU_VENV%"
    goto :check_venv
)

REM GPU环境不可用，回退CPU
echo [WARN] GPU环境不可用，回退到CPU环境
set "USE_VENV=%CPU_VENV%"
set "PDFOCR_ENGINE=rapidocr"

:check_venv
if not exist "%USE_VENV%\Scripts\python.exe" (
    echo [ERROR] 未找到Python环境！
    echo   请运行 setup_env.bat 安装环境
    pause
    exit /b 1
)

REM 激活并启动
call "%USE_VENV%\Scripts\activate.bat"
if defined PDFOCR_ENGINE (
    echo [INFO] 引擎(环境变量直通): %PDFOCR_ENGINE%
) else (
    echo [INFO] 请在启动窗口中选择引擎（GGUF / RapidOCR）
)
echo [INFO] 启动中...
python "%SCRIPT_DIR%main.py"

endlocal
