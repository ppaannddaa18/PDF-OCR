@echo off
REM PaddleOCR-VL 独立文档识别程序（venv-paddle 环境）
cd /d %~dp0
venv-paddle\Scripts\python.exe main_ocr.py
