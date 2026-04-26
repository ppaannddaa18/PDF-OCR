# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec file for PDF OCR Tool
"""
from pathlib import Path
import site
import sys

block_cipher = None

# 获取项目根目录和site-packages路径
project_root = Path(SPECPATH)
site_packages = site.getsitepackages()[0]
venv_site_packages = Path(sys.executable).parent.parent / 'Lib' / 'site-packages'

# 隐式导入模块列表
hiddenimports = [
    'app',
    'app.utils',
    'app.utils.config_loader',
    'app.utils.logger',
    'app.utils.lru_cache',
    'app.utils.image_utils',
    'app.utils.image_preprocessor',
    'app.utils.validators',
    'app.utils.command_history',
    'app.utils.history_manager',
    'app.core',
    'app.core.ocr_engine',
    'app.core.pdf_loader',
    'app.core.batch_processor',
    'app.core.template_manager',
    'app.core.exporter',
    'app.core.coordinate_utils',
    'app.ui',
    'app.ui.main_window',
    'app.ui.widgets',
    'app.ui.widgets.pdf_canvas',
    'app.ui.widgets.file_list_panel',
    'app.ui.widgets.field_panel',
    'app.ui.widgets.result_table',
    'app.ui.widgets.history_panel',
    'app.ui.widgets.preprocess_toolbar',
    'app.models',
    'app.models.region',
    'app.models.template',
    'app.models.ocr_result',
    'app.workers',
    'app.workers.batch_worker',
    'app.workers.ocr_worker',
]

# 数据文件
datas = [
    ('config.yaml', '.'),  # 应用配置
    (str(venv_site_packages / 'rapidocr_onnxruntime' / 'config.yaml'), 'rapidocr_onnxruntime'),  # RapidOCR配置
    (str(venv_site_packages / 'rapidocr_onnxruntime' / 'models'), 'rapidocr_onnxruntime/models'),  # ONNX模型
]

a = Analysis(
    ['main.py'],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=['tkinter', 'matplotlib', 'scipy', 'pytest', 'IPython', 'jupyter'],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='PDF-OCR',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=r'C:\Users\30726\Downloads\favicon.ico',
)
