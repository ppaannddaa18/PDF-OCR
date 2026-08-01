# 关键字驱动的批量单据关键信息汇总 — 主题化重设计（Design Spec）

> 生成时间：2026-08-01。经 superpowers:brainstorming 澄清 + frontend-design 视觉方向确认，计划批准后落盘。

## 1. 背景与目标

用户方向变更：将"关键字驱动的批量单据关键信息汇总"作为程序主题，删除无关功能，重新设计 PDF OCR Tool。用户是财务工作者：上传批量发票/各类报表（形式各异），输入关键字（如"报关单号"），程序自动在每张单据中提取对应值，汇总成可核对、可修正、可导出的表。

## 2. 需求决策（用户已拍板）

1. **程序主题**：关键字批量汇总；删除无关功能
2. **半批处理**：汇总表为主，待确认单元格可点开核对原文
3. **引擎分工**：关键字提取走 **GGUF**（GPU 优先，VLM 版面理解）；模板框选走 **RapidOCR**
4. **模板框选模式保留**（字段面板/模板管理/批量识别全保留）
5. **内嵌核对**：点单元格 → 程序内渲染该 PDF 页 + 提取区域高亮（PDF 文本层定位）
6. **保留**：核心链路、模板模式、内嵌预览、历史记录；**删除**：表格数据提取、单页字段视图、版面导航图
7. **多页 PDF**：逐页扫、每页一行，按文件分组、默认折叠
8. **单元格可编辑 + 人工修正标记**
9. 重设计路线：**主题化重组**（保留引擎层/模板/批量/历史，UI 按新主题重排）

## 3. 视觉方向（frontend-design）

- 主题锚定"财务工作台"：底稿、档案、核对；骨架用现有灰体系，个性由状态色承担
- 新增 ThemeManager 角色：`success_bg`/`warning_bg`/`error_bg`（单元格状态底色，明暗两主题）
- **Signature：关键字列头"命中率徽标"**——每列显示命中比例（如 92%），低命中列警示色
- 文件组头：档案夹样式（主色色块 + 文件名 + 页数徽标 + 组内待确认数）
- 数值单元格右对齐 + 等宽数字；徽标 caption 小号
- 全部颜色/字体/间距走 ThemeManager（项目硬约束）

## 4. 总体架构（三页导航）

```
FluentWindow 侧边导航：单据处理 | 关键字汇总 | 历史记录
页① 单据处理（现状重组）：文件列表 + PDF 预览画布 + 模板框选（RapidOCR）+ 批量识别
页② 关键字汇总（新核心）：
   操作带：[关键字输入] [提取] [导出] | [集合下拉] [保存为集合] [管理集合]
   汇总树（按文件分组折叠，每页一行；列头=关键字+命中率徽标）
   点击单元格 → 右侧滑出核对面板（渲染该页 + 文本层高亮 + 该页单元格表）
   底部统计条：文件数/页数/待确认/进度条/取消
页③ 历史记录（保留 HistoryManager/HistoryPanel）
```

## 5. 组件设计

### 新建
| 文件 | 职责 |
|---|---|
| `app/models/keyword_result.py` | `KeywordCell`/`PageKeywordResult`/`FileKeywordResult` 纯 dataclass |
| `app/core/keyword_extractor.py` | 两级匹配提取（精确锚点复用 structured_extractor 函数；宽松 L1 同行/L2 跨行/L3 blob；状态 exact→confirmed、loose→pending、无→not_found；校验委托 FinanceProcessor） |
| `app/core/keyword_batch_processor.py` | 逐页扫描（渲染→GGUF recognize_page_auto→extract），ThreadPoolExecutor 并行文件、页串行，单页失败不中断，cancel 抛 InterruptedError |
| `app/workers/keyword_batch_worker.py` | QThread 薄层镜像 BatchWorker（progress/finished_all/cancelled + 节流 + _completed_results） |
| `app/utils/keyword_set_manager.py` | 命名关键字集 CRUD，JSON 持久化 ~/.pdf_ocr_tool/（原子写/损坏备份） |
| `app/core/keyword_exporter.py` | Excel/CSV：每页一行（文件名\|页号\|kw\|kw_状态\|…\|文件状态） |
| `app/core/text_layer_locator.py` | PDF 文本层词级定位（fitz get_text('words')，跨词匹配），核对高亮唯一坐标源 |
| `app/ui/widgets/keyword_summary_tree.py` | 分组折叠汇总树（档案夹组头/页行/命中率徽标/状态底色/tooltip/双击编辑+人工修正标记/cell_inspect_requested 信号） |
| `app/ui/widgets/keyword_summary_page.py` | 汇总页组装 + 守卫 + 集合下拉 |
| `app/ui/widgets/keyword_inspection_panel.py` | 右侧滑出核对面板（复用 PdfCanvas 渲染+高亮，无框选） |
| `app/ui/widgets/keyword_set_dialog.py` | 关键字集管理对话框 |

### 修改
- `app/ui/theme_manager.py`：加 `success_bg/warning_bg/error_bg` 明暗两主题
- `app/ui/widgets/pdf_canvas.py`：简化（保留 load_image/缩放/高亮，移除框选/导航交互）
- `app/ui/main_window.py`：三页导航重组 + 关键字提取/核对/导出接线 + 互斥守卫 + 删除 auto 单页解析接线

### 删除
- `layout_visualizer.py`（导航图）、`result_panel.py`（单页视图）、table_extractor 接线、ParseWorker、双向高亮接线
- `structured_extractor.py` 保留为函数库（提取函数被 keyword_extractor 复用）

## 6. 数据流

```
上传 → 关键字汇总页输入/加载关键字集 → 提取（逐页 GGUF）→ FileKeywordResult
→ 汇总树（文件组折叠 + 命中率徽标 + 统计）→ 点单元格 → 核对面板（渲染+文本层高亮+单元格表）
→ 双击改值（人工修正标记）→ 导出 Excel（每页一行）
```

## 7. 错误处理

守卫（引擎未就绪/无文件/无关键字/双 worker 互斥）→ InfoBar；单页失败标记不中断；GGUF 冷启动在 worker 线程；取消保留已完成；无文本层 PDF 只渲染不高亮。

## 8. 测试

无头：extractor（两级匹配矩阵）/set_manager（CRUD）/batch_processor（逐页/取消/失败）/exporter（Excel 读回）/text_layer_locator（词级定位）。
UI（qapp）：summary_tree（折叠/底色/徽标/编辑）/summary_page（守卫/集合/主题刷新）/inspection_panel（渲染/高亮/回写）。
回归：模板模式/历史记录/主题相关测试保持绿。

## 9. 约束

颜色走 ThemeManager；`venv/Scripts/python.exe -m pytest tests/`；工作树脏只 add 明确路径；UI 测试复用 conftest qapp fixture。
