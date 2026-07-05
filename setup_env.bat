@echo off
chcp 65001 >nul
echo ============================================
echo  PDFOCR 环境安装 - PaddleOCR-VL GPU版
echo  硬件: NVIDIA RTX 5060 Laptop (8GB VRAM)
echo ============================================
echo.

set "SCRIPT_DIR=%~dp0"

REM 1. 创建 GPU 主环境
echo [1/3] 创建GPU主环境 (PaddleOCR-VL)...
python -m venv "%SCRIPT_DIR%venv"
call "%SCRIPT_DIR%venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install paddlepaddle-gpu==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install "paddleocr[doc-parser]>=3.6.0"
pip install PyQt6>=6.5.0 PyQt6-Fluent-Widgets>=1.4.0 QtAwesome>=1.2.0
pip install PyMuPDF>=1.23.0 Pillow>=10.0.0 opencv-python>=4.8.0
pip install numpy>=1.24.0 pandas>=2.0.0 openpyxl>=3.1.0 PyYAML>=6.0
pip install rapidocr-onnxruntime>=1.3.0 pynvml>=11.0

REM 验证 GPU
echo.
echo [2/3] 验证GPU环境...
python -c "import paddle; print('CUDA可用:', paddle.is_compiled_with_cuda())"

REM 创建 CPU 备用环境
echo.
echo [3/3] 创建CPU备用环境 (RapidOCR)...
python -m venv "%SCRIPT_DIR%venv-cpu"
call "%SCRIPT_DIR%venv-cpu\Scripts\activate.bat"
pip install rapidocr-onnxruntime>=1.3.0
pip install PyQt6>=6.5.0 PyQt6-Fluent-Widgets>=1.4.0 QtAwesome>=1.2.0
pip install PyMuPDF>=1.23.0 Pillow>=10.0.0 opencv-python>=4.8.0
pip install numpy>=1.24.0 pandas>=2.0.0 openpyxl>=3.1.0 PyYAML>=6.0

echo.
echo ============================================
echo  安装完成！
echo  启动方式:
echo    run.bat          - 自动使用GPU环境
echo    run.bat --cpu    - 强制使用CPU环境
echo ============================================
pause
