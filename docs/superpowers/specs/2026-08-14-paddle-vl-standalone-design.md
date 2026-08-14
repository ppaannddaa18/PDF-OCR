# PaddleOCR-VL 独立文档识别程序 — 设计文档

日期：2026-08-14
状态：已确认（用户批准方案 A：同仓库独立入口）

## 背景与动机

PaddleOCR-VL 整页 Spotting 每页约 40s，与发票关键词提取程序（批量快速提取关键字段）的定位不匹配。将其从主程序中分离为独立文档识别工具，专注于"上传 PDF / 图片 → 识别 → 查看结果"。

界面与功能参考百度 AI Studio PaddleOCR 文件任务页（https://aistudio.baidu.com/paddleocr/task/file/t-12c2182c7d11），调研确认的功能画像：

- 上传页：拖拽/点击上传（PDF/PNG/JPG/BMP/TIF，单文件≤200MB&1000页，批量≤20 个）+ 模型选择 + 能力展示
- 文件任务页：左侧文件列表（最近上传/收藏）+ 源文件面板（名/大小/页码导航/加文件）+ 解析类型切换（文档解析 / JSON）+ 工具按钮（≡配置 / ↻ / ⧉复制 / ⇩下载）
- 文档解析视图：结构化文本渲染（标题/段落/公式/表格）
- JSON 视图：树形浏览器（`layoutParsingResults → prunedResult → parsing_res_list`：block_label / block_content / block_bbox / block_id / group_id）
- 解析配置弹窗（≡ 三横线）：辅助内容过滤（页眉/页眉图片/页脚/页脚图片/页码/脚注/旁注文本）+ 模型参数（方向矫正/扭曲矫正/版面分析/图表识别/印章识别/图片文字识别/跨页表格合并/段落标题级别识别/几何形状）+ prompt 类型（文本/公式/表格/图表/印章）+ 文本检测与识别（重复抑制强度/识别稳定性/结果可信范围/图像最小最大总像素/NMS 后处理）+ 应用/重置
- 系统设置：访问令牌 + 解析配额 + API/MCP

## 已确认的决策

1. **代码关系**：同仓库独立入口（方案 A）——在现有 PDFOCR 仓库内新增 `main_ocr.py` 入口 + 独立打包 spec，复用 app/core 引擎、PdfCanvas、PdfLoader、ThemeManager 等组件
2. **功能范围（第一版）**：上传 + 文件列表 + 批量解析；解析配置弹窗；文档解析 + JSON 双视图；结果导出
3. **主程序**：启动选择界面移除 paddle_vl 卡片（只留 gguf/rapid），每次手动选择（默认值改为 rapidocr）

## 架构

### 新文件

| 文件 | 职责 |
|---|---|
| `main_ocr.py`（根目录） | 新程序入口：QApplication → 配置 → OcrMainWindow；直接用 paddle_vl 引擎，不弹引擎选择 |
| `app/core/ocr_doc_processor.py` | 文档级处理编排：文件（PDF/图片）→ 逐页渲染 → 引擎识别 → PageResult 列表 + 缓存；顺序批量队列 + 取消 + 单页失败继续 |
| `app/ui/windows/ocr_main_window.py` | OcrMainWindow（FluentWindow + AppBaseWindowMixin 复用主题/InfoBar/遮罩/历史/状态栏），单页布局：左侧文件列表 + 右侧工作区 |
| `app/ui/widgets/ocr_file_panel.py` | 左侧文件列表：文件名 + 状态徽章（等待/识别中/完成/失败）+ 耗时 + 时间，删除/清空/点击切换 |
| `app/ui/widgets/ocr_result_views.py` | 文档解析视图（QSplitter：PdfCanvas 渲染 + QTextBrowser 按 block_label 样式渲染 + 检测框高亮开关）+ JSON 树视图（QTreeWidget 基于 PageResult.raw） |
| `app/ui/widgets/ocr_parse_config_dialog.py` | 解析配置弹窗（仿三横线弹窗，字段见下） |
| `app/core/ocr_exporter.py` | 导出 TXT / Markdown / JSON（含块坐标结构） |
| `run_ocr.bat` / `PDF-OCR-VL.spec` | 启动脚本（venv-paddle）/ 打包 spec |

### 引擎扩展（app/core/ocr_engine_paddle_vl.py + app/models/page_result.py）

1. **解析配置透传**：`_predict_once` 从 `self._config` 读取完整参数组传入 `predict()`：
   - `use_doc_orientation_classify`（图片方向矫正）
   - `use_doc_unwarping`（图片扭曲矫正）
   - `use_layout_detection`（版面分析，并入现有 `block_spotting` 开关）
   - `use_chart_recognition` / `use_seal_recognition` / `use_ocr_for_image_block` / `merge_layout_blocks`（透传，paddlex 支持则生效，不支持忽略）
2. **重复抑制热生效**：`repetition_penalty` 从"initialize 时注入"改为"每次 predict 前注入 `generation_config`"——改配置无需重启管线
3. **辅助内容过滤**：页眉/页眉图片/页脚/页脚图片/页码/脚注/旁注文本开关 → `markdown_ignore_labels` 集合，blocks→markdown 组装时过滤
4. **原始结果保留**：`PageResult` 增加 `raw: dict` 字段，保存 paddlex 返回的 prunedResult 原始结构（JSON 视图与 JSON 导出使用，与参考页面结构一致）
5. **图片输入**：`recognize_page_auto` 已接受 PIL Image；`ocr_doc_processor` 层对图片文件直接 PIL 打开识别
6. 新增 spot 像素下限配置（`spotting_min_pixels`，默认 0）；预留参数（识别稳定性/结果可信范围/NMS/prompt 类型）透传，不支持则忽略

### 主窗口布局

```
┌────────┬──────────────────────────────────────────────────────┐
│ 文件列表 │  源文件面板：文件名 | 大小 | ◀ 1/17 ▶ | 加文件      │
│ (最近)  │  解析模型: [PaddleOCR-VL-1.6 ▾]                     │
│        │  [文档解析] [JSON]  [≡配置] [↻] [⧉复制] [⇩导出]     │
│ 文件A   │ ┌──────────────┬───────────────────────────────────┐ │
│ ✓ 完成  │ │  PDF 页渲染   │  结构化文本（标题加粗/段落/公式/   │ │
│ ⏳ 识别中 │ │  (PdfCanvas)  │  表格等宽）＋检测框高亮开关        │ │
│ ⏸ 等待  │ │              │  （JSON 视图时换成折叠树）         │ │
│ ✗ 失败  │ └──────────────┴───────────────────────────────────┘ │
└────────┴──────────────────────────────────────────────────────┘
```

- 文件列表点击 → 有缓存直接显示，无缓存自动解析；状态徽章实时更新
- 源文件面板：页码导航（QSpinBox + 前后页），"加文件" = 上传按钮（QFileDialog 多选）
- 视图切换：文档解析 / JSON 分段按钮；JSON 树基于 `PageResult.raw`，节点可折叠
- 检测框开关：`PageResult.line_boxes` → PdfCanvas `highlight_bbox`（复用）
- 复制：当前页结构化文本到剪贴板
- 状态栏：文件 x/y、页 n/m、单页耗时、累计耗时、GPU 显存

### 批量处理与生命周期

- 顺序队列（GPU 单任务，避免并发 OOM），后台 QThread 逐文件逐页：`render_page`（PDF，dpi 取 config `pdf.render_dpi`）→ `recognize_page_auto`
- 信号：`file_started` / `page_progress` / `file_done` / `file_failed` / `cancelled`
- 取消：worker 标志位 + 引擎 `_infer_lock`；已解析页保留，未完成文件标记"已取消"
- 缓存与历史：内存缓存 `{path: {pages, raw}}`（仅当前会话）；历史记录复用 `HistoryManager` 只持久化文件路径列表；启动时恢复列表，点击历史文件若无内存缓存则自动重新识别
- 单页失败不中断文件（失败页标记）；OOM 走引擎 `_hard_reset` 自愈
- 关闭时任务进行中 → 确认弹窗

### 导出（OcrExporter）

| 格式 | 内容 |
|---|---|
| TXT | 逐页纯文本（markdown 去标记） |
| Markdown | 每页 `PageResult.markdown` |
| JSON | 每页 `raw` 原始结构（`layoutParsingResults→prunedResult→parsing_res_list`） |

导出方式：QFileDialog 选目录，按"文件名_页码.ext"或整文件合并导出。

### 解析配置弹窗（OcrParseConfigDialog）

| 分组 | 字段 | 映射 |
|---|---|---|
| 辅助内容过滤 | 页眉/页眉图片/页脚/页脚图片/页码（默认开）/脚注/旁注文本 | `markdown_ignore_labels` |
| 模型参数 | 图片方向矫正、图片扭曲矫正（默认关） | `use_doc_orientation_classify` / `use_doc_unwarping` |
| | 版面分析（默认关） | `use_layout_detection` |
| | 图表识别、印章识别、图片文字识别、跨页表格合并（默认开） | predict 透传 |
| | 段落标题级别识别、几何形状（自动/矩形/四边形/多边形） | 预留 `format_block_content` / `return_layout_polygon_points` |
| Prompt 类型 | 文本/公式/表格/图表/印章 | 官方 spotting 固定 "spotting"，保留为综合展示 |
| 文本检测与识别 | 重复抑制强度（默认 1.1）、识别稳定性、结果可信范围 | `repetition_penalty`（predict 前注入）；后两项透传 |
| | 图像最小/最大总像素数 | `spotting_min_pixels`（新）/ `spotting_max_pixels`（默认 1048576） |
| | NMS 后处理 | 透传 |

- 应用 → 保存到 `app/config.yaml` 的 `ocr.paddle_vl` 段 → 热生效（无需重启管线）
- 重置 → 恢复默认值

### 主程序改动（最小侵入）

1. `app/ui/engine_select_dialog.py`：`_CARD_SPECS` 删除 `paddle_vl` 卡片
2. `main.py`：环境变量校验 + 窗口分派移除 paddle_vl 分支；config `engine: paddle_vl` 视为无效 → 回退 rapid 并提示
3. `app/config.yaml` + 根 `config.yaml`：主程序 `engine` 默认改 `rapidocr`；`ocr.paddle_vl` 段保留并同步新参数（新程序使用）
4. `app/utils/engine_checker.py`：可用性检测不再检查 paddle_vl（对话框不再调用）
5. 新增 `run_ocr.bat`：`venv-paddle\Scripts\python.exe main_ocr.py`

## 测试计划

| 测试 | 内容 |
|---|---|
| 引擎扩展 | predict 参数透传断言、repetition_penalty 每次注入、markdown 过滤（辅助内容开关）、`PageResult.raw` 保存 |
| OcrDocProcessor | 批量顺序/进度信号/取消/单页失败继续/图片文件直接识别（fake 引擎） |
| UI 组件 | 文件面板增删与状态徽章；双视图切换；JSON 树构建；配置弹窗字段 roundtrip/默认/重置 |
| 主窗口（offscreen） | 加载文件→解析→结果显示链路（fake 引擎）；关闭确认 |
| 主程序改动 | engine_select_dialog 卡片只剩 2 张；main.py 校验回退 |
| 全量回归 | 现有 615+ 测试全绿 |

## 风险与兜底

- 引擎改动影响主程序 keyword 路径 → 全量回归 + 主程序关键字提取端到端复验
- paddlex 版本升级导致透传参数签名变化 → 抛错时降级为默认参数（try/except + 日志）
- 批量长文档耗时（40s/页）→ 状态栏/徽章持续反馈，不阻塞 UI
- 解析配置部分参数对 VLM spotting 路径无实际效果 → 弹窗中标注"引擎支持情况"，透传不报错
