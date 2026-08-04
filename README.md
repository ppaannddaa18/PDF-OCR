# PDF OCR Tool

双引擎双界面 PDF 文档 OCR 桌面工具：

- **GGUF 推理操作台** —— 本地 PaddleOCR-VL（llama.cpp GGUF）整页版面理解，关键字批量提取、汇总、核对与导出
- **RapidOCR 文档工作台** —— CPU 轻量模板框选识别，适合固定版式单据（发票、报关单等）批量提取字段

一次会话只启用一个引擎：启动时强制选择（不记忆、无默认），两个引擎有完全独立的窗口与视觉风格。

## 功能特性

| | GGUF 推理操作台 | RapidOCR 文档工作台 |
|---|---|---|
| 窗口 | 侧边导航 4 页（关键字提取 / 识别结果 / 历史记录 / 模型设置） | 顶部标签 3 页（工作区 / 识别结果 / 历史记录） |
| 视觉 | 深色「信号台」：暗松绿 × 黄铜金，顶部引擎状态发光带 | 浅色「文具档案室」：暖纸 × 档案绿，荧光笔框选 |
| 核心能力 | 关键字批量提取（VLM 整页识别 + 两级匹配）→ 汇总树（命中率徽标）→ PDF 文本层核对 → 手动修正 → 导出 Excel | 画布拖拽框选区域 → 试识别 / 批量识别 → 图像预处理 → 撤销/重做 → 导出 Excel/CSV |
| 模板 | 命名关键字集（保存 / 加载 / 管理） | 框选模板（保存 / 加载 / 设为默认模板 / 每文件独立覆盖） |
| 模型设置 | 端口、设备 GPU/CPU、n_gpu_layers、max_tokens、temperature、prompt 类型、辅助内容开关等；保存 / 重启引擎 / 测试连接 | 外观动画开关 |
| 其他 | 识别结果页、历史记录（可恢复） | 识别结果页、历史记录（可恢复） |

## 环境要求

- Windows 10/11（推荐；llama.cpp CUDA 预编译版），Python 3.10+
- GGUF 引擎：NVIDIA GPU 建议 8GB 显存（推理约 4–5GB），CPU 模式可用但较慢
- RapidOCR 引擎：CPU 即可，无外部依赖

## 安装

1. 克隆仓库：
   ```bash
   git clone https://github.com/ppaannddaa18/PDF-OCR.git
   cd PDF-OCR
   ```

2. 创建环境（二选一）：

   **方式 A：一键脚本（Windows）**
   ```bat
   setup_env.bat
   ```
   创建 GPU 主环境 `venv` 与 CPU 备用环境 `venv-cpu`。

   **方式 B：手动创建**
   ```bash
   python -m venv venv
   venv\Scripts\activate
   pip install -r requirements-gpu.txt
   ```
   CPU 环境使用 `requirements-cpu.txt`。

3. 下载 GGUF 模型与 llama-server（GGUF 引擎需要）：

   - `models/PaddleOCR-VL-1.6-GGUF.gguf`（约 892 MB）
   - `models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf`（约 841 MB）
   - `llama-b9969/llama-server.exe`：从 [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases) 下载
     `llama-bXXXX-bin-win-cuda-cu12.4.0-x64.zip` 并解压到 `llama-b9969/`（连同 CUDA DLL）。

   模型路径可在「模型设置」页配置；若仓库内默认布局存在，失效路径会自动修复。

## 运行

```bat
run.bat              :: 使用 GPU 环境，启动后选择引擎
run.bat --cpu        :: 强制 RapidOCR（CPU 环境）
```

或直接：

```bash
venv\Scripts\python.exe main.py
```

启动流程：每次启动弹出引擎选择界面（无默认选中，Esc 关闭 = 退出程序）。设置环境变量可直通跳过：

```bat
set PDFOCR_ENGINE=gguf      & venv\Scripts\python.exe main.py
set PDFOCR_ENGINE=rapidocr  & venv\Scripts\python.exe main.py
```

## 使用说明

### GGUF 推理操作台（关键字提取）

1. 上传 PDF（Ctrl+O）→ 输入关键字（逗号/顿号分隔，如 `报关单号,价税合计,合同协议号`）
2. 提取（Ctrl+Enter）→ 汇总树按文件/页面分组，命中率徽标标识待确认项
3. 双击待确认单元格 → 右侧核对面板渲染该页并高亮 PDF 文本层
4. 手动修正后导出 Excel（Ctrl+Shift+F）

> 提示：密集表格单据（如报关单）中，字段值可能在标签下方一行；提取器会跳过相邻标签行并继续向下取值，命中项以「待确认」状态标出。

### RapidOCR 文档工作台（模板框选）

1. 添加 PDF（Ctrl+O）→ 在画布上拖拽框选字段区域，右侧配置字段名与 OCR 模式
2. 试识别（Ctrl+T）确认效果 → 批量识别（Ctrl+Enter）
3. 结果页可筛选、编辑；导出 Excel/CSV

## 快捷键

### GGUF（推理操作台）

| 快捷键 | 动作 |
|---|---|
| Ctrl+O | 上传 PDF 文件 |
| Ctrl+Enter | 提取关键字 |
| Ctrl+S | 保存当前输入为命名关键字集 |
| Ctrl+Shift+N | 新建关键字集 |
| Ctrl+Shift+F | 导出关键字汇总 Excel |
| Delete | 删除选中 PDF 文件 |
| Ctrl+↑ / Ctrl+↓ | 上移 / 下移选中文件 |

### RapidOCR（文档工作台）

| 快捷键 | 动作 |
|---|---|
| Ctrl+O | 添加 PDF 文件 |
| Ctrl+T | 试识别 |
| Ctrl+Enter | 批量识别 |
| Ctrl+S | 保存模板 |
| Ctrl+Shift+N | 新建模板 |
| Ctrl+Z / Ctrl+Y | 撤销 / 重做框选 |
| Ctrl+Shift+L / Ctrl+Shift+R | 折叠 / 滑出左右面板 |
| Delete | 删除选中字段区域 |
| Space | 快速预览试识别结果 |

## 配置说明

**生效配置文件为 `app/config.yaml`**（代码读取路径与写盘路径一致）。仓库根目录的 `config.yaml` 为历史遗留副本，不再使用。

GGUF 引擎关键项：

| 配置项 | 默认值 | 说明 |
|---|---|---|
| `ocr.engine` | `gguf` | 自动化兜底引擎；交互启动由选择对话框决定 |
| `ocr.gguf.max_tokens` | `2048` | 单页最大生成 token；密集表单建议 2048（512 会截断，2560 以上易出现重复退化） |
| `ocr.gguf.prompt_type` | `text` | `text` / `table` / `formula` 等；表格类整页建议 `text`（`table` 在长输出下易重复） |
| `ocr.gguf.layout_geometry` | `auto` | `auto` / `rectangle` / `quadrilateral` / `polygon` |
| `ocr.gguf.port` / `host` | `9999` / `127.0.0.1` | llama-server 监听地址 |
| `ocr.gguf.device` | `gpu` | GPU/CPU；切换设备需重启程序 |
| `ocr.gguf.n_gpu_layers` | `99` | 加载到 GPU 的层数 |
| `ocr.gguf.temperature` | `0.2` | 采样温度 |
| `appearance.animations_enabled` | `true` | 全局动画开关（两窗口设置入口） |

## 项目结构

```
PDFOCR/
├── main.py                      # 程序入口（引擎选择 → 双窗口分流）
├── app/
│   ├── config.yaml              # 生效配置文件
│   ├── core/                    # 引擎与核心逻辑
│   │   ├── ocr_engine_gguf.py   # GGUF 引擎（llama-server HTTP API）
│   │   ├── ocr_engine_rapid.py  # RapidOCR 引擎
│   │   ├── keyword_extractor.py # 关键字两级匹配提取
│   │   ├── keyword_batch_processor.py / keyword_result_adapter.py
│   │   ├── field_matcher.py     # 区域三级匹配（IoU/就近/关键词）
│   │   ├── batch_processor.py   # 模板批量识别
│   │   ├── pdf_loader.py / exporter.py / structured_extractor.py 等
│   ├── ui/
│   │   ├── windows/             # base_window / gguf_main_window / rapid_main_window
│   │   ├── widgets/             # keyword_summary_page / gguf_settings_page / pdf_canvas / field_panel 等
│   │   ├── theme_manager.py     # 双设计 token 管道（default/gguf/rapid）
│   │   └── engine_select_dialog.py
│   ├── models/                  # 数据模型（keyword_result / ocr_result / region / template）
│   ├── utils/                   # config_loader / history_manager / engine_checker 等
│   └── workers/                 # batch_worker / keyword_batch_worker
├── llama-b9969/                 # llama-server.exe 与 CUDA DLL（需自行下载）
├── models/                      # GGUF 模型文件
├── tests/                       # 单元测试（含 UI offscreen 测试）
├── requirements-gpu.txt / requirements-cpu.txt
├── run.bat / run.sh / setup_env.bat
├── GGUF_README.md               # GGUF 模型部署指南
└── docs/UI-DESIGN.md            # 双引擎双界面设计说明
```

## 测试

```bash
QT_QPA_PLATFORM=offscreen venv\Scripts\python.exe -m pytest tests/ -q
```

当前全量：**528 passed, 1 skipped**。UI 测试在 offscreen 平台运行，不会真实启动引擎或连接网络。

## 相关文档

- [GGUF_README.md](GGUF_README.md) —— PaddleOCR-VL GGUF 模型部署与 llama-server 使用
- [docs/UI-DESIGN.md](docs/UI-DESIGN.md) —— 双引擎双界面架构、视觉 token 与快捷键说明

## 许可证

MIT License
