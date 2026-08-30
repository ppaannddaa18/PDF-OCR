# PDFOCR

Windows 桌面 PDF 文档 OCR 工具集：一套共享核心库（`app/`）驱动**三个独立程序**，覆盖从轻量模板提取到整页版面理解的不同场景。

| | GGUF 推理操作台 | RapidOCR 文档工作台 | PaddleOCR-VL 观片台 |
|---|---|---|---|
| 入口 | `main.py`（启动时选择 GGUF） | `main.py`（启动时选择 RapidOCR） | `main_ocr.py`（独立程序） |
| 推理方式 | PaddleOCR-VL GGUF + llama.cpp（本地 HTTP API） | RapidOCR（ONNX，纯 CPU） | PaddleOCR-VL 官方管线（paddlex native） |
| 硬件要求 | NVIDIA GPU 建议 8GB 显存 | CPU 即可 | NVIDIA GPU 8GB（实测峰值 ~4.2GB） |
| 界面风格 | 深色「信号台」：暗松绿 × 黄铜金，侧边导航 4 页 | 浅色「文具档案室」：暖纸 × 档案绿，顶部标签 3 页 | 冷钢灰「观片台」：深海蓝点缀，单页工作区 |
| 擅长场景 | 关键字批量提取：多文件汇总 → PDF 文本层核对 → 导出 Excel | 固定版式单据（发票/报关单）模板框选批量提取 | 整页版面理解：多页文档逐页解析，行级坐标高亮，导出 TXT/MD/JSON |

一次会话只启用一个引擎：主程序启动时强制选择（不记忆、无默认），三个引擎拥有完全独立的窗口与视觉风格。

## 快速开始

### 环境要求

- Windows 10/11、Python 3.10+
- GGUF 引擎：NVIDIA GPU（推理约 4–5GB 显存），CPU 模式可用但较慢
- RapidOCR 引擎：CPU 即可，无外部依赖
- PaddleOCR-VL 观片台：NVIDIA GPU 8GB（8GB 卡实测可整页推理，含 bf16 与 SDPA 显存适配）

### 安装

1. 克隆仓库：

   ```bash
   git clone https://github.com/ppaannddaa18/PDF-OCR.git
   cd PDF-OCR
   ```

2. 创建主程序环境（二选一）：

   **方式 A：一键脚本**

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

3. GGUF 引擎额外需要（RapidOCR / 观片台不需要）：

   - `models/PaddleOCR-VL-1.6-GGUF.gguf`（约 892 MB）与 `models/PaddleOCR-VL-1.6-GGUF-mmproj.gguf`（约 841 MB）
   - `llama-b9969/llama-server.exe`：从 [llama.cpp Releases](https://github.com/ggerganov/llama.cpp/releases) 下载 `llama-bXXXX-bin-win-cuda-cu12.4.0-x64.zip` 解压到 `llama-b9969/`（连同 CUDA DLL）

   模型路径可在「模型设置」页配置；默认布局存在时失效路径会自动修复。

4. PaddleOCR-VL 观片台使用独立环境 `venv-paddle`（paddlepaddle / paddlex / paddleocr，与主程序依赖隔离），首次使用请自行创建并安装 PaddleOCR-VL 相关依赖。

### 运行

**主程序（GGUF / RapidOCR）：**

```bat
run.bat              :: GPU 环境，启动后选择引擎
run.bat --cpu        :: 强制 RapidOCR（CPU 环境）
```

启动时弹出引擎选择界面（无默认选中，Esc = 退出）。可用环境变量直通跳过：

```bat
set PDFOCR_ENGINE=gguf      & venv\Scripts\python.exe main.py
set PDFOCR_ENGINE=rapidocr  & venv\Scripts\python.exe main.py
```

**PaddleOCR-VL 观片台（独立程序）：**

```bat
run_ocr.bat
```

或直接 `venv-paddle\Scripts\python.exe main_ocr.py`，启动后直接进入识别主窗口。

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

### PaddleOCR-VL 观片台（独立识别程序）

1. 「+ 加文件」或直接拖拽 PDF/图片入队（手动模式：点「解析」才开始处理）
2. 解析完成后左侧文件列表逐个查看；「版面检视 / 原始 JSON」双视图切换
3. 底部「显示检测框」可在预览上叠加识别区域高亮；预览支持右键拖动平移、缩放
4. 「复制」复制当前视图文本；「导出」选择 TXT / Markdown / JSON / 全部格式
5. 历史文件自动归入「历史记录」分组（默认折叠），选中后点「重试」单独重新解析

#### 解析配置

工具栏「配置」打开解析配置弹窗，参数按五张卡片分组：

| 卡片 | 内容 | 生效条件 |
|---|---|---|
| 识别模式 | 整页识别 / 版面分析（互斥单选） | — |
| 识别内容 | 页眉/页脚/页码/脚注/旁注等辅助内容的保留与过滤 | 仅版面分析 |
| 专项识别 | 图表识别、印章识别、图片文字识别、跨页表格合并 | 仅版面分析 |
| 文档矫正 | 图片方向矫正、图片扭曲矫正 | 两种模式，**修改需重启引擎** |
| 识别质量与效率 | 重复抑制强度、图像最小/最大总像素（含官方默认/省显存预设） | 两种模式 |

- **整页识别**：整页一次识别，每行文字都带高亮框；**版面分析**：按表格/图表/文本/图片分开处理，表格识别更结构化、辅助内容可过滤、表格区域以整块高亮呈现
- 模式未开启时，依赖它的卡片整体置灰并显示「整页模式下未生效」角标（勾选值保留，开启后立即生效）
- 参数悬停可查看说明；带 `*` 的参数表示已偏离默认值（重置可恢复）；像素上下限矛盾时应用会被阻止

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

> PaddleOCR-VL 观片台暂无全局快捷键，全部操作通过界面按钮完成。

## 配置说明

**生效配置文件为 `app/config.yaml`**（代码读取路径与写盘路径一致）。仓库根目录的 `config.yaml` 为历史遗留副本，不再使用。

> 注意：应用内「保存配置」会程序化重写 `app/config.yaml`（注释丢失、键按字母排序）；如需手工编辑，建议改完立即备份或参考本仓库提交历史中的注释版。

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
| `appearance.animations_enabled` | `true` | 全局动画开关（各窗口设置入口） |

PaddleOCR-VL 关键项（详见应用内「解析配置」弹窗，悬停参数可查看说明）：`ocr.paddle_vl.block_spotting`（版面分析）、`repetition_penalty`（重复抑制）、`spotting_max_pixels`（显存/坐标精度权衡，默认官方 1605632）、`use_doc_orientation_classify` / `use_doc_unwarping`（矫正，修改需重启引擎）等。

## 项目结构

```
PDFOCR/
├── main.py                          # 主程序入口（引擎选择 → GGUF / RapidOCR 分流）
├── main_ocr.py                      # PaddleOCR-VL 观片台入口（独立程序）
├── app/
│   ├── config.yaml                  # 生效配置文件
│   ├── core/                        # 引擎与核心逻辑
│   │   ├── ocr_engine_gguf.py       # GGUF 引擎（llama-server HTTP API）
│   │   ├── ocr_engine_rapid.py      # RapidOCR 引擎
│   │   ├── ocr_engine_paddle_vl.py  # PaddleOCR-VL 官方管线引擎（观片台）
│   │   ├── ocr_doc_processor.py     # 文档级解析编排（队列/缓存/取消/续跑）
│   │   ├── ocr_exporter.py          # TXT / Markdown / JSON 导出
│   │   ├── keyword_extractor.py     # 关键字两级匹配提取
│   │   ├── field_matcher.py         # 区域三级匹配（IoU/就近/关键词）
│   │   ├── batch_processor.py       # 模板批量识别
│   │   └── pdf_loader.py / exporter.py / structured_extractor.py 等
│   ├── ui/
│   │   ├── windows/                 # base / gguf / rapid / ocr 主窗口
│   │   ├── widgets/                 # 设置页 / 解析配置弹窗 / 汇总树 / pdf_canvas 等
│   │   ├── theme_manager.py         # 多设计 token 管道（default/gguf/rapid/paddle_vl）
│   │   └── engine_select_dialog.py
│   ├── models/                      # 数据模型（keyword_result / ocr_result / region / template）
│   ├── utils/                       # config_loader / history_manager / engine_checker 等
│   └── workers/                     # batch_worker / keyword_batch_worker
├── docs/
│   ├── UI-DESIGN.md                 # 双引擎双界面设计说明
│   └── superpowers/specs/           # 功能设计文档
├── tests/                           # 单元测试（含 UI offscreen 测试）
├── requirements-gpu.txt / requirements-cpu.txt
├── run.bat / run.sh / setup_env.bat / run_ocr.bat
├── GGUF_README.md                   # GGUF 模型部署指南
├── llama-b9969/                     # llama-server.exe 与 CUDA DLL（需自行下载）
└── models/                          # GGUF 模型文件
```

## 测试

```bash
QT_QPA_PLATFORM=offscreen venv\Scripts\python.exe -m pytest tests/ -q
```

当前全量：**745 passed, 1 skipped**。UI 测试在 offscreen 平台运行，不会真实启动引擎或连接网络。

## 相关文档

- [GGUF_README.md](GGUF_README.md) —— PaddleOCR-VL GGUF 模型部署与 llama-server 使用
- [docs/UI-DESIGN.md](docs/UI-DESIGN.md) —— 双引擎双界面架构、视觉 token 与快捷键说明
- [docs/superpowers/specs/](docs/superpowers/specs/) —— 各功能设计文档（观片台、解析配置弹窗、检测框高亮等）

## 许可证

MIT License
