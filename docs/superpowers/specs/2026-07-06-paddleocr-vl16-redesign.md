# PaddleOCR-VL-1.6 双模式架构重设计

## 1. 背景与目标

### 当前问题
- PaddleOCR-VL 推理报 `int(Variable) is not supported in static graph mode`，`disable_static()`/`FLAGS_enable_pir_api=false`/`enable_to_static(False)` 均无效（VLM worker 是子进程，穿透不到）
- 当前 `use_layout_detection=False` + 手动框选的做法绕过了 PaddleOCR-VL 最强的版面解析能力
- 对于财务票据，缺乏结构化的字段提取后处理

### 目标
- **自动模式**（PaddleOCR-VL）：整页版面解析 → 结构化结果 → Markdown预览 → 多格式导出
- **手动模式**（RapidOCR）：保留现有框选+OCR流程，不受影响
- 从根本修复 `int(Variable)` 崩溃

---

## 2. 双模式架构

```
PDFOCR
├─ 自动模式（PaddleOCR-VL）
│   PDF页 → 整页pipeline.predict() → 版面检测+VLM识别
│   → blocks(坐标+类型+内容) → Markdown预览 → 导出
│
└─ 手动模式（RapidOCR，保持不变）
    PDF页 → 用户画框 → 裁剪 → OCR → FieldMatcher → Excel
```

### 引擎切换
- 下拉框切换引擎时，UI 自动切换模式
- PaddleOCR-VL → 隐藏框选工具，显示"解析"按钮 + 版面可视化面板
- RapidOCR → 显示框选工具，隐藏版面面板，回归右侧区域列表

---

## 3. 修复 `int(Variable)` 崩溃

**根因**：PaddleOCR-VL 默认 engine 使用 `@paddle.jit.to_static` 编译，在 PaddlePaddle 3.2.1 下 `int(Variable)` 失败。

**修复**：使用官方 `engine="paddle_dynamic"` 参数，完全绕过静态图编译：

```python
self._pipeline = PaddleOCRVL(
    vl_rec_model_name=self._model_name,
    device=self._device,
    precision=self._precision,
    engine="paddle_dynamic",      # ← 关键：跳过@to_static编译
    use_layout_detection=True,    # ← 启用版面检测
)
```

**回退以前的无效 workaround**：
- `main.py`: 删除 `FLAGS_enable_pir_api=false`
- `ocr_engine_paddle.py`: 删除 `disable_static()` 调用
- `ocr_engine_paddle.py`: 删除 `enable_to_static(False)` 调用

---

## 4. 数据流 & 后处理管道

```
┌─ PaddleOCR-VL ──────────────────────────┐
│ pipeline.predict(image)                 │
│   → Result对象 (.json + .markdown)       │
│   → LayoutExtractor → Block[]           │
└─────────────────────────────────────────┘
                     ↓
┌─ RapidOCR ─────────────────────────────┐
│ 框选 → OCR每个区域                       │
│   → RegionResult → Block[]             │
└─────────────────────────────────────────┘
                     ↓
          ┌──────────────────┐
          │  统一 Block[]     │  ← 引擎无关
          └──────────────────┘
                     ↓
    ┌────────────────┼────────────────┐
    ↓                ↓                ↓
TableExtractor   FinanceProcessor   导出
DataFrame        字段抽取+校验       Markdown
                 (引擎无关)          JSON/Word/Excel
```

### 新增文件

| 文件 | 职责 |
|------|------|
| `app/core/layout_extractor.py` | VLM Result → Block[] 统一结构 |
| `app/core/block_builder.py` | RapidOCR RegionResult → Block[] 统一结构（方便两种引擎喂给同一后处理） |
| `app/core/table_extractor.py` | Markdown table → DataFrame，解析失败降级保留原始Markdown |
| `app/core/finance_processor.py` | 引擎无关，输入 Block[] → 财务字段抽取 + 校验 |
| `app/models/page_result.py` | Block / PageResult / FinanceResult 数据类 |

### 改动文件

| 文件 | 改动 |
|------|------|
| `app/core/ocr_engine_paddle.py` | 新增 `recognize_page_auto()` 返回 PageResult；`engine="paddle_dynamic"` |
| `app/ui/main_window.py` | 双模式 UI 切换、版面可视化面板、结果面板 |
| `app/ui/widgets/pdf_canvas.py` | VLM 模式下禁用框选，块覆盖层渲染 |
| `main.py` | 删除 `FLAGS_enable_pir_api=false` |
| `app/config.yaml` | 新增 `layout_visualization` / `finance` 配置段 |

### `recognize_page_auto()` 签名

```python
def recognize_page_auto(self, image: Image.Image) -> PageResult:
    """整页自动解析 — PaddleOCR-VL模式专用"""
```

### 保留不改动

- `app/core/field_matcher.py` — RapidOCR 手动模式继续使用
- `app/core/ocr_engine.py` — 工厂函数加模式判断但不改签名
- 现有 `recognize_page()` — 保留给 RapidOCR

---

## 5. UI 布局：三栏

```
┌──────────────────────────────────────────────────────────────┐
│  [引擎选择 ▼] │ [PDF页号 ◄ 1/5 ►] │  [解析] [导出▼]        │
├─────────────────┬──────────────────┬─────────────────────────┤
│   PDF 预览      │  版面可视化       │  结果面板               │
│   (原图)        │  (block彩色覆盖)  │  ┌─ Markdown预览 ────┐ │
│                 │                  │  │ ## 发票信息        │ │
│  VLM模式:只读   │  ██ 文字(蓝)     │  │ | 项目 | 金额 |    │ │
│  Rapid模式:框选 │  ██ 表格(绿)     │  │ |------|------|    │ │
│                 │  ██ 公式(橙)     │  │ | 合计 | 1234 |    │ │
│                 │  ██ 图表(紫)     │  └────────────────────┘ │
│                 │  ██ 印章(红)     │  ┌─ 字段提取 ────────┐ │
│                 │                  │  │ 发票号: 12345678   │ │
│                 │  Rapid模式:隐藏  │  │ 金额: ¥1,234.00   │ │
│                 │                  │  │ 日期: 2024-01-15   │ │
│                 │                  │  └────────────────────┘ │
├─────────────────┴──────────────────┴─────────────────────────┤
│  状态栏: GPU 2.1/8.0GB │ PaddleOCR-VL │ 解析用时 1.2s       │
└─────────────────────────────────────────────────────────────┘
```

### 模式切换行为

| | PaddleOCR-VL 自动模式 | RapidOCR 手动模式 |
|---|---|---|
| **左面板** | PDF 只读预览 | PDF 可框选 |
| **中面板** | block 覆盖层（彩色框） | 隐藏，左面板扩展 |
| **右面板** | Markdown + 字段 + 导出 | 区域列表 + 结果 + Excel |
| **工具栏** | [解析] [导出▼] | [框选工具] [删除] [OCR] [导出] |

### 版面可视化

- 从 `parsing_res_list` 的 bbox + label 生成半透明彩色覆盖矩形
- 颜色映射: `text→蓝` `table→绿` `formula→橙` `chart→紫` `seal→红`
- 悬停 tooltip 显示 block 类型和内容摘要
- 左右面板同步滚动

### 导出格式

- Markdown — 保存为 `.md` 文件
- JSON — 完整结构化数据（含坐标）
- Word — 通过 `python-docx` 生成 `.docx`
- Excel — 表格类结果写入 `.xlsx`

---

## 6. 财务后处理（FinanceProcessor）— 引擎无关

`FinanceProcessor` 不绑定任何引擎，输入统一 `Block[]` 即可。PaddleOCR-VL 通过 `LayoutExtractor` 产出 Block[]，RapidOCR 通过 `BlockBuilder` 将 `RegionResult` 转换为 Block[]——两条路径最终汇入同一个后处理管道。

### 字段抽取策略

```python
# 坐标锚点 + 关键词匹配
for block in blocks:
    if '发票号码' in block.content:
        fields['invoice_no'] = find_neighbor(blocks, block, direction='right')
    if '开票日期' in block.content:
        fields['date'] = extract_date(find_neighbor(blocks, block))
    if '价税合计' in block.content or '小写' in block.content:
        fields['amount'] = extract_money(text)
```

### 校验规则

| 校验 | 规则 |
|------|------|
| 金额勾稽 | 明细合计 ≈ 价税合计（容差0.01） |
| 税额验证 | 税额 ≈ 金额 × 税率 |
| 日期合法 | 不超当前日期 |
| 发票号位数 | `VALID_INVOICE_LEN = {8, 10, 12, 20}` — 覆盖老专票(8位)、数电发票(20位)等多种格式 |

### 正则工具函数

- `extract_money(text)` — 金额（处理¥/逗号/空格）
- `extract_date(text)` — 日期归一化（年/月/日 → YYYY-MM-DD）
- `find_neighbor(blocks, anchor, direction)` — 坐标邻近查值
- `markdown_table_to_df(md)` — Markdown表格→DataFrame，**解析失败降级保留原始Markdown文本**（`pd.read_csv(sep='|')` 在单元格含逗号/换行时易崩，try-except 兜底）

---

## 7. 配置扩展

```yaml
# app/config.yaml 新增段
paddleocr_vl:
  engine: paddle_dynamic     # 新增: paddle | paddle_static | paddle_dynamic | transformers
  use_layout_detection: true # 改为默认true
  # ... 保留现有字段 ...

layout_visualization:
  enabled: true
  colors:
    text: "#4A90D9"
    table: "#27AE60"
    formula: "#E67E22"
    chart: "#8E44AD"
    seal: "#E74C3C"

finance:
  enabled: false  # 财务模式开关
  invoice:
    keywords: ["发票号码", "开票日期", "价税合计", "购买方", "销售方"]
  validation:
    amount_tolerance: 0.01
    tax_rate: 0.13
```

---

## 8. 验证

```bash
# 1. PaddleOCR-VL 模式 — 启动 → 加载PDF → 点击"解析" → 确认无 int(Variable) 错误 → 版面可视化显示 → Markdown正确
# 2. RapidOCR 模式 — 切换引擎 → 确认框选功能正常 → 区域OCR → Excel导出
# 3. 引擎切换 — PaddleOCR-VL ↔ RapidOCR 反复切换 → 确认UI模式切换正确
# 4. 导出 — 四种格式各测试一次
python main.py
```
