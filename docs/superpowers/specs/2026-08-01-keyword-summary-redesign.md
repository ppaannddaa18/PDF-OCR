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

## 10. 实现偏差记录（Task 1–11 实际实现 vs 本 spec / 实现计划）

| # | 偏差 | 原因与处理 |
|---|---|---|
| 1 | `_extract_value` 非模块级函数 | 它是 `StructuredExtractor` 的 staticmethod；`keyword_extractor` 用 `_extract_value = StructuredExtractor._extract_value` 取用，行为不变 |
| 2 | 精确 pass 跨行锚点跳过 | `_SEP` 尾部 `\s*` 贪婪吞换行符（`价税合计\n¥1,234.56` 的 m.end() 越过行尾），行尾截断失效 → 宽松 L2 永远无法触发。`_exact_pass` 检查 `m.group(0)` 含 `\n` 则跳过交宽松 pass（恢复 spec 决策 12 两级语义） |
| 3 | 宽松 L3 blob 兜底实际冗余 | 单行时精确 pass 与 L3 等价或更优（`_SEP` 容忍无分隔符），L3 在两级语义下无独有成功场景；保留为安全网，测试改为断言「精确优先」 |
| 4 | `KeywordBatchWorker._completed_results` 成功路径赋值 | 计划实现只 clear 不赋值，Task 10 取消分支取不到部分结果；`run()` 成功时 `self._completed_results = results` |
| 5 | tests/conftest.py 新增 | `qapp` fixture 原只在 tests/ui/conftest.py（目录级）；根目录 worker 测试需要，新建根 conftest 提供（tests/ui 的目录级 fixture 优先，无冲突） |
| 6 | 汇总树 apply_theme 重建整树 | 计划实现 `_refresh_subtree` 只清空不重涂，主题切换后状态底色丢失；改为 `load_results(self._results)` 幂等重建 |
| 7 | `_KW_SPLIT_RE` 补全角分号 | 计划正则漏 `；`（仅 `;`），用户输入"报关单号,价税合计；发票号码"会切不开 |
| 8 | Task 10 页面数为 **4 页** 非 3 页 | 模板工作区页保留（方案 B 的"单据处理"），加关键字汇总后 stackedWidget 共 4 页（工作区/识别结果/历史记录/关键字汇总） |
| 9 | `right_panel`（SlidablePanel）**保留** | 计划 3e 误判"right_panel 已删"；它承载字段面板（模板模式核心），`test_theme_refresh` 的 right_panel 断言保留 |
| 10 | `_switch_ui_mode` 整体删除 | auto/manual 模式切换 UI（结果面板/解析按钮/导航图）随删除组件失效；模板模式 UI 不随引擎切换，引擎切换仅更新 `_current_mode` 状态 |
| 11 | `_right_content_stack` 删除 | 删 ResultPanel 后栈中只剩字段面板，直接布局替代 QStackedWidget |
| 12 | `_invalidate_current_result` 删除 | 双向高亮删除后无高亮源，预处理换图路径的清理调用一并移除（`PdfCanvas.load_image` 内部 `scene_.clear()` 已清所有 item） |
| 13 | `compact_toolbar` 删除 nav_toggle 按钮/信号 | 导航图删除后按钮残留显示且无连接，一并删除（含其测试） |
| 14 | 测试修正（计划测试与实现/spec 矛盾处） | blob 截断需列入后文锚点（keywords 加"预录入编号"）；纯汉字剔除行输入改为无标点行（含"：" 按 spec 决策 12 属可信）；`fail_render` 0-based 页码笔误；PyQt6 `QBrush.style()` 返回枚举 `bool()` 恒 True 改用 `== Qt.BrushStyle.NoBrush`；setCurrentText 需切换项才触发信号；无窗口环境用 isHidden 断言显隐 |

### deferred（spec 范围外，后续迭代）
- 关键字结果进历史记录（HistoryManager 整合）
- 校验委托 `FinanceProcessor.validate_field` 接入汇总表单元格
- 关键字集导入/导出文件
