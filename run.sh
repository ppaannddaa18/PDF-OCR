#!/bin/bash
# PDFOCR 智能启动器 (Git Bash / Linux)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_VENV="$SCRIPT_DIR/venv"
CPU_VENV="$SCRIPT_DIR/venv-cpu"
FORCE_CPU=0

[[ "$1" == "--cpu" || "$1" == "-c" ]] && FORCE_CPU=1

if [[ $FORCE_CPU -eq 1 ]]; then
    echo "[INFO] 强制使用CPU模式"
    USE_VENV="$CPU_VENV"
    export PDFOCR_ENGINE=rapidocr
elif [[ -f "$GPU_VENV/Scripts/python.exe" ]]; then
    echo "[INFO] 使用GPU环境: PaddleOCR-VL"
    USE_VENV="$GPU_VENV"
    export PDFOCR_ENGINE=paddleocr_vl
elif [[ -f "$GPU_VENV/bin/python" ]]; then
    echo "[INFO] 使用GPU环境: PaddleOCR-VL"
    USE_VENV="$GPU_VENV"
    export PDFOCR_ENGINE=paddleocr_vl
else
    echo "[WARN] GPU环境不可用，回退到CPU环境"
    USE_VENV="$CPU_VENV"
    export PDFOCR_ENGINE=rapidocr
fi

if [[ ! -f "$USE_VENV/Scripts/python.exe" && ! -f "$USE_VENV/bin/python" ]]; then
    echo "[ERROR] 未找到Python环境！请运行 setup_env.bat 安装"
    exit 1
fi

echo "[INFO] 引擎: $PDFOCR_ENGINE"
source "$USE_VENV/Scripts/activate" 2>/dev/null || source "$USE_VENV/bin/activate" 2>/dev/null
python "$SCRIPT_DIR/main.py"
