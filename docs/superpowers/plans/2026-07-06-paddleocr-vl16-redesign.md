# PaddleOCR-VL-1.6 双模式架构 — 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PDFOCR 从单一手动框选模式升级为 PaddleOCR-VL 自动版面解析 + RapidOCR 手动框选双模式架构，修复 `int(Variable)` 崩溃。

**Architecture:** PaddleOCR-VL 使用 `engine="paddle_dynamic"` 绕过静态图编译，`use_layout_detection=True` 启用版面检测。两种引擎产出统一 `Block[]` 结构，汇入引擎无关的 `TableExtractor` / `FinanceProcessor` 后处理管道。UI 根据引擎模式自动切换三栏/两栏布局。

**Tech Stack:** Python 3.12, PyQt6 + qfluentwidgets, PaddleOCR-VL (paddlepaddle-gpu 3.2.1), pandas, openpyxl, python-docx

**Spec:** `docs/superpowers/specs/2026-07-06-paddleocr-vl16-redesign.md`

## Global Constraints

- `paddlepaddle-gpu==3.2.1` — PaddleOCR-VL 的 engine 参数依赖此版本
- 不可破坏现有 RapidOCR 手动模式功能
- 新增文件均放在 `app/` 目录下，遵循现有模块分层（core/models/ui）
- 配置通过 `config.yaml` 管理，支持 `PDFOCR_ENGINE` 环境变量覆盖
- NPU/DCU/XPU 等硬件加速不在本次范围

---

### Task 1: 数据模型 — Block / PageResult / FinanceResult

**Files:**
- Create: `app/models/page_result.py`
- Modify: `app/models/__init__.py` (添加导出)

**Interfaces:**
- Produces: `Block`, `PageResult`, `FinanceResult`, `VALID_INVOICE_LEN`

- [ ] **Step 1: 创建 `app/models/page_result.py`**

```python
"""统一页面结果数据模型 — 引擎无关"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any


# 发票号位长集合：老专票(8)、普票(10/12)、数电发票(20)
VALID_INVOICE_LEN = {8, 10, 12, 20}


@dataclass
class Block:
    """版面块 — 引擎无关的统一结构"""
    block_type: str           # "text" | "table" | "formula" | "chart" | "seal"
    content: str              # 文本内容（表格为Markdown字符串）
    bbox: List[float]         # [x1, y1, x2, y2] 像素坐标
    confidence: float = 1.0   # 置信度 0-1
    meta: Dict[str, Any] = field(default_factory=dict)  # 引擎特定元数据


@dataclass
class PageResult:
    """整页解析结果"""
    blocks: List[Block]              # 所有版面块
    markdown: str = ""               # 全页Markdown
    tables: List[Any] = field(default_factory=list)  # DataFrame列表
    raw_json: Dict[str, Any] = field(default_factory=dict)  # VLM原始json
    image_size: tuple = (0, 0)       # (width, height)
    inference_time_ms: float = 0.0   # 推理耗时（毫秒）


@dataclass
class FinanceField:
    """单个财务字段"""
    label: str                # 字段名（如"发票号码"）
    value: str                # 提取值
    confidence: float = 1.0   # 置信度
    validated: bool = True    # 是否通过校验
    validation_msg: str = ""  # 校验失败时说明原因


@dataclass
class FinanceResult:
    """财务字段提取结果"""
    fields: List[FinanceField] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)  # 校验异常

    def get(self, label: str) -> Optional[str]:
        for f in self.fields:
            if f.label == label:
                return f.value
        return None
```

- [ ] **Step 2: 更新 `app/models/__init__.py`**

检查 `app/models/__init__.py` 是否存在，添加或更新导出：

```python
from app.models.page_result import Block, PageResult, FinanceResult, FinanceField, VALID_INVOICE_LEN
```

- [ ] **Step 3: 验证导入**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR
source venv/Scripts/activate
python -c "from app.models.page_result import Block, PageResult, FinanceResult, FinanceField, VALID_INVOICE_LEN; b = Block('text', 'hello', [0,0,10,10]); print(b)"
```
Expected: `Block(block_type='text', content='hello', bbox=[0, 0, 10, 10], confidence=1.0, meta={})`

- [ ] **Step 4: Commit**

```bash
git add app/models/page_result.py app/models/__init__.py
git commit -m "feat: add Block/PageResult/FinanceResult data models"
```

---

### Task 2: 修复 int(Variable) 崩溃 + 清理 workaround

**Files:**
- Modify: `app/core/ocr_engine_paddle.py:89-102`
- Modify: `app/core/ocr_engine_paddle.py:70` (use_layout_detection 默认值)
- Modify: `main.py:47-51`

**Interfaces:**
- Consumes: `PaddleOCRVL` constructor from `paddleocr`
- Produces: `PaddleOCREngine.initialize()` 使用 `engine="paddle_dynamic"`

- [ ] **Step 1: 修改 `ocr_engine_paddle.py` — 初始化参数**

将第 70 行的默认值改为 `True`：
```python
# 修改前 (line 70):
self._use_layout_detection = vl_cfg.get("use_layout_detection", False)
# 修改后:
self._use_layout_detection = vl_cfg.get("use_layout_detection", True)
```

将第 89-102 行的 `initialize()` 方法中 pipeline 创建改为使用 `engine="paddle_dynamic"`，并删除无效的 `enable_to_static(False)`：

```python
# 修改前 (line 89-102):
            try:
                logger.info(f"PaddleOCR-VL 开始创建 pipeline (device={self._device}, precision={self._precision})...")
                from paddleocr import PaddleOCRVL
                import paddle
                paddle.set_device(self._device)
                # PaddleOCR-VL内部使用@to_static编译, 在PaddlePaddle 3.x下
                # int(Variable)在静态图不支持, 全局禁用to_static避免编译
                paddle.jit.enable_to_static(False)
                self._pipeline = PaddleOCRVL(
                    vl_rec_model_name=self._model_name,
                    device=self._device,
                    precision=self._precision,
                    use_layout_detection=self._use_layout_detection,
                )
# 修改后:
            try:
                logger.info(f"PaddleOCR-VL 开始创建 pipeline (device={self._device}, precision={self._precision}, engine=paddle_dynamic)...")
                from paddleocr import PaddleOCRVL
                import paddle
                paddle.set_device(self._device)
                self._pipeline = PaddleOCRVL(
                    vl_rec_model_name=self._model_name,
                    device=self._device,
                    precision=self._precision,
                    engine="paddle_dynamic",       # 跳过@to_static编译，修复int(Variable)崩溃
                    use_layout_detection=self._use_layout_detection,
                )
```

- [ ] **Step 2: 修改 `main.py` — 删除 FLAGS_enable_pir_api=false**

```python
# 删除 lines 47-51：
# 修改前 (line 47-51):
    import os

    # PaddlePaddle 3.x 默认启用PIR模式，int(Tensor)在PIR下不支持，
    # 必须在import paddle之前禁用，否则VLM推理报 "int(Tensor) is not supported in static graph mode"
    os.environ["FLAGS_enable_pir_api"] = "false"

    # CPU VLM模式: 必须在导入paddle之前设置，否则PaddlePaddle内部Place(undefined:0)崩溃
    engine_type = config.get("ocr", {}).get("engine", "rapidocr")
    if engine_type == "paddleocr_vl_cpu":
        os.environ["CUDA_VISIBLE_DEVICES"] = ""

# 修改后:
    # CPU VLM模式: 必须在导入paddle之前设置，否则PaddlePaddle内部Place(undefined:0)崩溃
    engine_type = config.get("ocr", {}).get("engine", "rapidocr")
    if engine_type == "paddleocr_vl_cpu":
        import os
        os.environ["CUDA_VISIBLE_DEVICES"] = ""
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine_paddle.py main.py
git commit -m "fix: use engine=paddle_dynamic to fix int(Variable) crash, remove PIR workaround"
```

---

### Task 3: LayoutExtractor — VLM Result → Block[]

**Files:**
- Create: `app/core/layout_extractor.py`

**Interfaces:**
- Consumes: PaddleOCR-VL `Result` 对象（`.json`, `.markdown` 属性）
- Produces: `extract_blocks(output) -> List[Block]`, `extract_markdown(output) -> str`

- [ ] **Step 1: 创建 `app/core/layout_extractor.py`**

```python
"""LayoutExtractor — PaddleOCR-VL Result → 统一 Block[] 结构"""
from typing import List
import logging
from app.models.page_result import Block

logger = logging.getLogger("PDFOCR")


def extract_blocks(output) -> List[Block]:
    """
    从 PaddleOCR-VL Result 提取 blocks。

    Result 结构:
      .json -> overall_ocr_res (dt_polys, rec_texts, rec_scores)
             + parsing_res_list (block_bbox, block_label, block_content)
      .markdown -> markdown_texts
    """
    blocks = []
    try:
        data = output.json if hasattr(output, 'json') else (output if isinstance(output, dict) else {})
        # 从 overall_ocr_res 提取文字块
        ocr_res = data.get("overall_ocr_res", {})
        rec_texts = ocr_res.get("rec_texts", [])
        rec_scores = ocr_res.get("rec_scores", [])
        dt_polys = ocr_res.get("dt_polys", [])

        for i, text in enumerate(rec_texts):
            if not text or not text.strip():
                continue
            bbox = None
            if i < len(dt_polys):
                poly = dt_polys[i]
                if len(poly) >= 4:
                    xs = [p[0] for p in poly]
                    ys = [p[1] for p in poly]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
            confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
            blocks.append(Block(
                block_type="text",
                content=text,
                bbox=bbox or [0, 0, 0, 0],
                confidence=confidence,
            ))

        # 从 parsing_res_list 提取结构化块（表格/公式/图表/印章）
        label_map = {
            "table": "table",
            "formula": "formula",
            "chart": "chart",
            "seal": "seal",
        }
        for item in data.get("parsing_res_list", []):
            block_label = item.get("block_label", "")
            mapped = label_map.get(block_label, "text")
            content = item.get("block_content", "")
            coord = item.get("block_bbox", None)

            bbox = None
            if coord and isinstance(coord, list) and len(coord) >= 4:
                if isinstance(coord[0], (list, tuple)):
                    xs = [p[0] for p in coord]
                    ys = [p[1] for p in coord]
                    bbox = [min(xs), min(ys), max(xs), max(ys)]
                elif all(isinstance(v, (int, float)) for v in coord):
                    bbox = list(coord)
            blocks.append(Block(
                block_type=mapped,
                content=content if isinstance(content, str) else str(content),
                bbox=bbox or [0, 0, 0, 0],
                confidence=0.95,
            ))

    except Exception as e:
        logger.warning(f"LayoutExtractor: block extraction failed: {e}")
    return blocks


def extract_markdown(output) -> str:
    """从 Result 提取全页 Markdown"""
    try:
        md = output.markdown if hasattr(output, 'markdown') else {}
        if isinstance(md, dict):
            texts = md.get("markdown_texts", [])
            return "\n\n".join(texts) if texts else ""
        return str(md) if md else ""
    except Exception:
        return ""


def extract_raw_json(output) -> dict:
    """从 Result 提取原始 JSON"""
    try:
        return output.json if hasattr(output, 'json') else (output if isinstance(output, dict) else {})
    except Exception:
        return {}
```

- [ ] **Step 2: 验证导入**

```bash
python -c "from app.core.layout_extractor import extract_blocks, extract_markdown, extract_raw_json; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/core/layout_extractor.py
git commit -m "feat: add LayoutExtractor for VLM Result → Block[] conversion"
```

---

### Task 4: BlockBuilder — RapidOCR 结果 → Block[]

**Files:**
- Create: `app/core/block_builder.py`

**Interfaces:**
- Consumes: `List[Region]` + OCR 结果 `Dict[str, Tuple[str, float]]`
- Produces: `build_blocks(regions, ocr_results) -> List[Block]`

- [ ] **Step 1: 创建 `app/core/block_builder.py`**

```python
"""BlockBuilder — RapidOCR 手动框选结果 → 统一 Block[] 结构"""
from typing import List, Dict, Tuple
from app.models.page_result import Block
from app.models.region import Region


def build_blocks(
    regions: List[Region],
    ocr_results: Dict[str, Tuple[str, float]],
    image_size: Tuple[int, int],
) -> List[Block]:
    """
    将 RapidOCR 手动框选结果转换为 Block[]。

    Args:
        regions: 用户定义的框选区域列表
        ocr_results: {region_id: (text, confidence)}
        image_size: (width, height) 用于坐标归一化→像素转换

    Returns:
        Block 列表，每个 block 对应一个 region
    """
    W, H = image_size
    blocks = []
    for region in regions:
        result = ocr_results.get(region.id, ("", 0.0))
        text, confidence = result if isinstance(result, tuple) else (str(result), 0.0)
        # 归一化坐标 → 像素坐标
        bbox = [
            region.x * W,
            region.y * H,
            (region.x + region.w) * W,
            (region.y + region.h) * H,
        ]
        blocks.append(Block(
            block_type="text",
            content=text,
            bbox=bbox,
            confidence=float(confidence),
            meta={
                "region_id": region.id,
                "field_name": region.field_name,
                "ocr_mode": region.ocr_mode,
            },
        ))
    return blocks
```

- [ ] **Step 2: 验证导入**

```bash
python -c "from app.core.block_builder import build_blocks; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add app/core/block_builder.py
git commit -m "feat: add BlockBuilder for RapidOCR result → Block[] conversion"
```

---

### Task 5: TableExtractor — Markdown table → DataFrame

**Files:**
- Create: `app/core/table_extractor.py`

**Interfaces:**
- Consumes: `str` (Markdown text containing tables)
- Produces: `extract_tables(markdown: str) -> List[pandas.DataFrame]`

- [ ] **Step 1: 创建 `app/core/table_extractor.py`**

```python
"""TableExtractor — 从 Markdown 文本中提取表格为 DataFrame"""
from typing import List
import re
import logging
from io import StringIO
import pandas as pd

logger = logging.getLogger("PDFOCR")

# 匹配 Markdown 表格行（以 | 开头和结尾的行）
_TABLE_ROW_RE = re.compile(r'^\s*\|.+\|\s*$', re.MULTILINE)
# 匹配表格分隔符行（如 |---|---|）
_TABLE_SEP_RE = re.compile(r'^\|?[\s\-:|]+\|?$')


def extract_tables(markdown: str) -> List[pd.DataFrame]:
    """
    从 Markdown 中提取所有表格为 DataFrame 列表。
    解析失败时保留原始文本在 meta 中，不抛异常。

    Args:
        markdown: 整页 Markdown 文本

    Returns:
        DataFrame 列表（可能为空）
    """
    tables = []
    lines = markdown.split('\n')
    i = 0
    while i < len(lines):
        # 找表格起始行：非分隔符的 |...| 行
        if not _TABLE_ROW_RE.match(lines[i]):
            i += 1
            continue
        if _TABLE_SEP_RE.match(lines[i]):
            i += 1
            continue

        # 收集连续表格行
        table_lines = []
        while i < len(lines) and _TABLE_ROW_RE.match(lines[i]):
            table_lines.append(lines[i])
            i += 1

        if len(table_lines) < 2:
            continue

        # 过滤掉分隔符行
        data_lines = [l for l in table_lines if not _TABLE_SEP_RE.match(l)]
        if len(data_lines) < 2:
            continue

        try:
            # 清洗并解析
            cleaned = '\n'.join(data_lines)
            df = pd.read_csv(StringIO(cleaned), sep='|', engine='python')
            # 去掉边框产生的空列
            df = df.dropna(axis=1, how='all')
            if not df.empty:
                df.columns = [str(c).strip() for c in df.columns]
                tables.append(df)
        except Exception as e:
            # 解析失败：保留原始 Markdown，不搞崩整页
            logger.debug(f"TableExtractor: parse failed, keeping raw: {e}")
            df_raw = pd.DataFrame({"raw_markdown": [l.strip() for l in table_lines]})
            tables.append(df_raw)

    return tables
```

- [ ] **Step 2: 验证 — 正常表格**

```bash
python -c "
from app.core.table_extractor import extract_tables
md = '''
| Name | Age |
|------|-----|
| Alice | 30 |
| Bob | 25 |
'''
tables = extract_tables(md)
print(tables[0].to_string())
"
```
Expected: 输出包含 Name, Age, Alice, Bob 的 DataFrame

- [ ] **Step 3: 验证 — 异常表格降级**

```bash
python -c "
from app.core.table_extractor import extract_tables
md = '''
| Name, Age |
|------|
| Alice, 30 |
'''
tables = extract_tables(md)
print('raw_markdown' in tables[0].columns or len(tables) == 0)
"
```
Expected: `True`（不崩溃，要么解析成功，要么降级保留原始文本）

- [ ] **Step 4: Commit**

```bash
git add app/core/table_extractor.py
git commit -m "feat: add TableExtractor with graceful degradation on parse failure"
```

---

### Task 6: FinanceProcessor — 财务字段抽取 + 校验

**Files:**
- Create: `app/core/finance_processor.py`

**Interfaces:**
- Consumes: `List[Block]`, `config: Optional[dict]`
- Produces: `FinanceProcessor.process(blocks) -> FinanceResult`

- [ ] **Step 1: 创建 `app/core/finance_processor.py`**

```python
"""FinanceProcessor — 引擎无关的财务字段抽取与校验"""
import re
from typing import List, Optional, Dict, Set
from app.models.page_result import Block, FinanceResult, FinanceField, VALID_INVOICE_LEN


class FinanceProcessor:
    """财务字段抽取器 — 输入 Block[]，输出 FinanceResult"""

    def __init__(self, config: Optional[dict] = None):
        cfg = config or {}
        self._keywords: List[str] = cfg.get("invoice", {}).get("keywords", [
            "发票号码", "开票日期", "价税合计", "购买方", "销售方"
        ])
        self._amount_tolerance: float = cfg.get("validation", {}).get("amount_tolerance", 0.01)
        self._tax_rate: float = cfg.get("validation", {}).get("tax_rate", 0.13)

    def process(self, blocks: List[Block]) -> FinanceResult:
        """从 blocks 中抽取财务字段并校验"""
        fields = []
        warnings = []

        # 字段抽取：关键词 → 邻近值
        for kw in self._keywords:
            anchor = None
            for b in blocks:
                if kw in b.content:
                    anchor = b
                    break
            if anchor is None:
                continue
            value = _find_neighbor(blocks, anchor, direction='right')
            if not value:
                value = anchor.content  # 退步：取anchor自身的content
            fields.append(FinanceField(label=kw, value=value))

        # 校验
        self._validate(fields, warnings)
        return FinanceResult(fields=fields, warnings=warnings)

    def _validate(self, fields: List[FinanceField], warnings: List[str]) -> None:
        """对已抽取字段执行校验规则"""
        for f in fields:
            if f.label == "发票号码":
                _validate_invoice_no(f, warnings)
            elif f.label in ("开票日期", "日期"):
                _validate_date(f, warnings)
            elif "金额" in f.label or "价税" in f.label:
                _validate_amount(f, warnings)


# --- 坐标邻近查找 ---

def _find_neighbor(blocks: List[Block], anchor: Block, direction: str = 'right') -> str:
    """从 anchor 的右侧（同高度范围内）或下方（同 x 范围内）查找最近的 block"""
    if anchor.bbox is None:
        return ""
    ax1, ay1, ax2, ay2 = anchor.bbox
    candidates = []
    for b in blocks:
        if b is anchor or b.bbox is None:
            continue
        bx1, by1 = b.bbox[0], b.bbox[1]
        if direction == 'right' and abs(by1 - ay1) < 30 and bx1 >= ax2:
            candidates.append((bx1, b))
        elif direction == 'below' and abs(bx1 - ax1) < 30 and by1 >= ay2:
            candidates.append((by1, b))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1].content
    return ""


# --- 正则工具 ---

_MONEY_RE = re.compile(r'[¥￥]\s*([\d,]+\.?\d*)')

def _extract_money(text: str) -> Optional[float]:
    m = _MONEY_RE.search(text.replace(' ', ''))
    return float(m.group(1).replace(',', '')) if m else None


_DATE_RE = re.compile(r'(\d{4})[年/-](\d{1,2})[月/-](\d{1,2})')

def _extract_date(text: str) -> Optional[str]:
    text_norm = text.replace('年', '-').replace('月', '-').replace('日', '')
    m = _DATE_RE.search(text_norm)
    return f"{m[1]}-{int(m[2]):02d}-{int(m[3]):02d}" if m else None


# --- 校验 ---

from datetime import date

def _validate_invoice_no(f: FinanceField, warnings: List[str]) -> None:
    no = f.value.strip().replace(' ', '')
    if no.isdigit() and len(no) not in VALID_INVOICE_LEN:
        f.validated = False
        f.validation_msg = f"发票号位长 {len(no)} 不在合法范围 {VALID_INVOICE_LEN}"
        warnings.append(f.validation_msg)


def _validate_date(f: FinanceField, warnings: List[str]) -> None:
    d = _extract_date(f.value)
    if d is None:
        f.validated = False
        f.validation_msg = f"无法解析日期: {f.value}"
        warnings.append(f.validation_msg)
    else:
        try:
            parts = d.split('-')
            parsed = date(int(parts[0]), int(parts[1]), int(parts[2]))
            if parsed > date.today():
                f.validated = False
                f.validation_msg = f"日期 {d} 超过当前日期"
                warnings.append(f.validation_msg)
        except ValueError:
            f.validated = False
            f.validation_msg = f"非法日期: {d}"
            warnings.append(f.validation_msg)


def _validate_amount(f: FinanceField, warnings: List[str]) -> None:
    amount = _extract_money(f.value)
    if amount is None:
        f.validated = False
        f.validation_msg = f"无法解析金额: {f.value}"
        warnings.append(f.validation_msg)
```

- [ ] **Step 2: 验证 — 正常字段抽取**

```bash
python -c "
from app.core.finance_processor import FinanceProcessor
from app.models.page_result import Block

blocks = [
    Block('text', '发票号码', [100, 50, 150, 70]),
    Block('text', '12345678', [160, 50, 220, 70]),
    Block('text', '开票日期', [100, 80, 150, 100]),
    Block('text', '2024年01月15日', [160, 80, 230, 100]),
    Block('text', '价税合计', [100, 110, 150, 130]),
    Block('text', '¥1,234.56', [160, 110, 230, 130]),
]
fp = FinanceProcessor()
result = fp.process(blocks)
for f in result.fields:
    print(f'{f.label}: {f.value} (valid={f.validated})')
print('Warnings:', result.warnings)
"
```
Expected: 输出发票号码/开票日期/价税合计三行，无 warnings

- [ ] **Step 3: 验证 — 发票号位长校验**

```bash
python -c "
from app.core.finance_processor import FinanceProcessor
from app.models.page_result import Block

blocks = [Block('text', '发票号码', [0,0,10,10]), Block('text', '123', [20,0,30,10])]
fp = FinanceProcessor()
result = fp.process(blocks)
for f in result.fields:
    print(f'{f.label}: {f.value}, validation_msg={f.validation_msg}')
"
```
Expected: `validation_msg` 包含位长警告

- [ ] **Step 4: Commit**

```bash
git add app/core/finance_processor.py
git commit -m "feat: add engine-agnostic FinanceProcessor with field extraction and validation"
```

---

### Task 7: PaddleOCREngine — 新增 `recognize_page_auto()`

**Files:**
- Modify: `app/core/ocr_engine_paddle.py` — 新增方法

**Interfaces:**
- Consumes: `LayoutExtractor.extract_blocks()`, `LayoutExtractor.extract_markdown()`, `TableExtractor.extract_tables()`, `PageResult`
- Produces: `PaddleOCREngine.recognize_page_auto(image) -> PageResult`

- [ ] **Step 1: 在 `ocr_engine_paddle.py` 顶部添加新导入**

在现有 `from app.core.field_matcher import FieldMatcher` 后添加：
```python
from app.core.layout_extractor import extract_blocks, extract_markdown, extract_raw_json
from app.core.table_extractor import extract_tables
from app.models.page_result import PageResult, Block
```

- [ ] **Step 2: 在 PaddleOCREngine 类中添加新方法**

放在 `recognize()` 方法之后（约第 162 行之后）：

```python
    def recognize_page_auto(self, image: Image.Image) -> PageResult:
        """
        整页自动解析 — PaddleOCR-VL模式专用。
        利用pipeline的版面检测+VLM识别，返回结构化PageResult。
        """
        t0 = time.monotonic()
        W, H = image.size

        # VRAM守卫
        max_px = self._calc_max_pixels(image.size)
        free_vram = self._get_free_vram_gb()
        if free_vram < self._min_free_vram_gb:
            logger.warning(f"VRAM不足 ({free_vram:.2f}GB < {self._min_free_vram_gb}GB)，跳过推理")
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        try:
            with self._pipeline_lock:
                self._ensure_loaded()
                if self._pipeline is None:
                    raise RuntimeError("Pipeline was unloaded after initialization")
                arr = np.array(image) if isinstance(image, Image.Image) else image
                outputs = list(self._pipeline.predict(
                    arr,
                    temperature=0,
                    max_pixels=max_px,
                ))
                self._last_used_time = time.monotonic()
            # 推理后释放缓存
            try:
                import paddle
                paddle.device.cuda.empty_cache()
            except Exception:
                pass
        except Exception as e:
            logger.error(f"PaddleOCR-VL推理失败: {e}")
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        if not outputs:
            return PageResult(blocks=[], markdown="", image_size=(W, H))

        output = outputs[0] if isinstance(outputs, list) else outputs

        # 提取
        blocks = extract_blocks(output)
        md = extract_markdown(output)
        raw = extract_raw_json(output)
        tables = extract_tables(md)

        elapsed = (time.monotonic() - t0) * 1000
        return PageResult(
            blocks=blocks,
            markdown=md,
            tables=tables,
            raw_json=raw,
            image_size=(W, H),
            inference_time_ms=elapsed,
        )
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine_paddle.py
git commit -m "feat: add recognize_page_auto() returning structured PageResult"
```

---

### Task 8: main_window — 双模式 UI 切换

**Files:**
- Modify: `app/ui/main_window.py` — 模式和布局切换

**Interfaces:**
- Consumes: `PaddleOCREngine.recognize_page_auto()`, current engine type from combo box
- Produces: UI mode change when engine combo changes

- [ ] **Step 1: 在 `MainWindow.__init__` 中添加模式状态**

在 `__init__` 中已有引擎相关变量的位置附近添加：
```python
# 双模式状态
self._current_mode = "auto" if self._config.get("ocr", {}).get("engine") in ("paddleocr_vl", "paddleocr_vl_cpu") else "manual"
# 中面板（版面可视化）— VLM模式下显示
self._layout_view = None  # QGraphicsView，延迟创建
# 右面板 StackedWidget — 根据模式切换子面板
self._result_stack = None  # QStackedWidget
```

- [ ] **Step 2: 在 `_on_engine_switched` 中添加模式切换**

在现有的引擎切换方法末尾添加：
```python
    # 判断新模式
    new_mode = "auto" if new_engine_type in ("paddleocr_vl", "paddleocr_vl_cpu") else "manual"
    if new_mode != self._current_mode:
        self._current_mode = new_mode
        self._switch_ui_mode(new_mode)
```

- [ ] **Step 3: 实现 `_switch_ui_mode(mode)`**

```python
    def _switch_ui_mode(self, mode: str):
        """切换 UI 模式：auto(VLM) ↔ manual(RapidOCR)"""
        # 获取UI组件（延迟加载）
        Ui = _get_ui_components()

        if mode == "auto":
            # 隐藏手动框选工具栏
            if hasattr(self, '_field_panel') and self._field_panel:
                self._field_panel.hide()
            # 显示版面可视化面板
            if self._layout_view is not None:
                self._layout_view.show()
                # 调整splitter比例：左:中:右 = 1:1:2
            # 禁用 PDF canvas 的框选功能
            if hasattr(self, '_pdf_canvas') and self._pdf_canvas:
                self._pdf_canvas.set_drawing_enabled(False)
            # 工具栏切换
            # [框选工具] [删除] [OCR] 隐藏
            # [解析] [导出▼] 显示
        else:
            # 显示手动框选工具栏
            if hasattr(self, '_field_panel') and self._field_panel:
                self._field_panel.show()
            # 隐藏版面可视化
            if self._layout_view is not None:
                self._layout_view.hide()
            # 启用框选
            if hasattr(self, '_pdf_canvas') and self._pdf_canvas:
                self._pdf_canvas.set_drawing_enabled(True)
```

- [ ] **Step 4: 在工具栏添加"解析"按钮（VLM模式）**

```python
    # 解析按钮 — 仅VLM模式显示
    self._btn_parse = PushButton("解析")
    self._btn_parse.clicked.connect(self._on_parse_current_page)
    self._btn_parse.hide()  # 默认隐藏，VLM模式显示
    # 添加到toolbar
    toolbar_layout.addWidget(self._btn_parse)
```

- [ ] **Step 5: 实现 `_on_parse_current_page`**

```python
    def _on_parse_current_page(self):
        """点击'解析'按钮 — 触发当前页VLM解析"""
        from app.core.ocr_engine import get_ocr_engine
        engine = get_ocr_engine(self._config)
        if not hasattr(engine, 'recognize_page_auto'):
            InfoBar.error(self, "错误", "当前引擎不支持自动解析")
            return

        # 获取当前页图片
        if self._current_page_image is None:
            return
        self._btn_parse.setEnabled(False)
        self._btn_parse.setText("解析中...")

        # 在工作线程中执行（避免阻塞UI）
        Ui = _get_ui_components()
        # 简化：直接调用（后续可改为 QThread）
        try:
            self._current_page_result = engine.recognize_page_auto(self._current_page_image)
            self._on_page_parsed(self._current_page_result)
        finally:
            self._btn_parse.setEnabled(True)
            self._btn_parse.setText("解析")

    def _on_page_parsed(self, result):
        """解析完成回调"""
        # 更新版面可视化
        if self._layout_view:
            self._layout_view.update_blocks(result.blocks)
        # 更新结果面板
        # (Task 10 实现详细内容)
        InfoBar.success(self, "解析完成",
            f"识别 {len(result.blocks)} 个元素, 耗时 {result.inference_time_ms:.0f}ms",
            position=InfoBarPosition.BOTTOM_RIGHT)
```

- [ ] **Step 6: Commit**

```bash
git add app/ui/main_window.py
git commit -m "feat: add dual-mode UI switching logic and parse button"
```

---

### Task 9: LayoutVisualizer — 版面块覆盖层

**Files:**
- Create: `app/ui/widgets/layout_visualizer.py` — 独立的 QGraphicsView
- Modify: `app/ui/main_window.py` — 集成到三栏布局

**Interfaces:**
- Consumes: `List[Block]`
- Produces: `LayoutVisualizer.update_blocks(blocks)`, 同步滚动信号

- [ ] **Step 1: 创建 `app/ui/widgets/layout_visualizer.py`**

```python
"""LayoutVisualizer — 在PDF图片上叠加彩色block覆盖层"""
from PyQt6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsRectItem
from PyQt6.QtGui import QPixmap, QPen, QColor, QBrush, QPainter
from PyQt6.QtCore import Qt, QRectF, pyqtSignal as Signal
from typing import List
from app.models.page_result import Block

# 颜色映射
BLOCK_COLORS = {
    "text": QColor("#4A90D9"),
    "table": QColor("#27AE60"),
    "formula": QColor("#E67E22"),
    "chart": QColor("#8E44AD"),
    "seal": QColor("#E74C3C"),
}
# 透明填充色（半透明）
BLOCK_FILL = {
    k: QColor(c.red(), c.green(), c.blue(), 40) for k, c in BLOCK_COLORS.items()
}


class LayoutVisualizer(QGraphicsView):
    """同步滚动的版面块覆盖层视图"""
    scrolled = Signal(int)  # 垂直滚动值（同步用）

    def __init__(self, parent=None):
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._bg_item = None  # 背景图片（与左面板相同PDF页）
        self._block_items = []  # block覆盖矩形
        self.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self._scale = 1.0

    def set_page_image(self, pixmap: QPixmap):
        """设置当前页图片（与PDF预览同步）"""
        self._scene.clear()
        self._block_items = []
        self._bg_item = self._scene.addPixmap(pixmap)
        self._scene.setSceneRect(QRectF(pixmap.rect()))
        self.fitInView(self._scene.sceneRect(), Qt.AspectRatioMode.KeepAspectRatio)
        self._scale = self.transform().m11()

    def update_blocks(self, blocks: List[Block]):
        """根据blocks绘制彩色覆盖层"""
        # 移除旧覆盖层
        for item in self._block_items:
            self._scene.removeItem(item)
        self._block_items = []

        for block in blocks:
            if block.bbox is None:
                continue
            x1, y1, x2, y2 = block.bbox
            rect = QRectF(x1, y1, x2 - x1, y2 - y1)
            color = BLOCK_COLORS.get(block.block_type, QColor("#999999"))
            fill = BLOCK_FILL.get(block.block_type, QColor(150, 150, 150, 40))

            item = self._scene.addRect(rect, QPen(color, 2), QBrush(fill))
            item.setToolTip(f"[{block.block_type}] {block.content[:100]}")
            self._block_items.append(item)

    def scroll_to(self, value: int):
        """外部同步滚动"""
        self.verticalScrollBar().setValue(value)

    def wheelEvent(self, event):
        """转发滚动事件"""
        super().wheelEvent(event)
        self.scrolled.emit(self.verticalScrollBar().value())
```

- [ ] **Step 2: 集成到 main_window**

在 `main_window.py` 的布局创建中，将 PDF 预览区与 `LayoutVisualizer` 并排放置，用 `QSplitter` 分隔。两边的 `scrolled` 信号和 `scroll_to` 互连实现同步。

- [ ] **Step 3: Commit**

```bash
git add app/ui/widgets/layout_visualizer.py app/ui/main_window.py
git commit -m "feat: add LayoutVisualizer with colored block overlay"
```

---

### Task 10: ResultPanel — Markdown预览 + 字段提取 + 导出

**Files:**
- Create: `app/ui/widgets/result_panel.py`
- Modify: `app/ui/main_window.py` — 集成右面板

**Interfaces:**
- Consumes: `PageResult`, `FinanceProcessor`
- Produces: 可切换的 Markdown/字段/导出 面板

- [ ] **Step 1: 创建 `app/ui/widgets/result_panel.py`**

```python
"""ResultPanel — VLM解析结果展示 + 导出"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTextEdit, QTableWidget,
    QTableWidgetItem, QPushButton, QFileDialog, QStackedWidget,
    QComboBox, QLabel, QMessageBox,
)
from PyQt6.QtCore import Qt
from typing import Optional
import json
import logging

logger = logging.getLogger("PDFOCR")


class ResultPanel(QWidget):
    """右面板：Markdown预览 / 字段提取 / 导出"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._page_result = None
        self._finance_result = None
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        # 视图切换下拉框
        top_bar = QHBoxLayout()
        self._view_selector = QComboBox()
        self._view_selector.addItems(["Markdown预览", "字段提取", "表格数据"])
        self._view_selector.currentIndexChanged.connect(self._on_view_changed)
        top_bar.addWidget(QLabel("视图:"))
        top_bar.addWidget(self._view_selector)
        top_bar.addStretch()

        # 导出按钮
        self._btn_export = QPushButton("导出...")
        self._btn_export.clicked.connect(self._on_export)
        top_bar.addWidget(self._btn_export)
        layout.addLayout(top_bar)

        # 堆叠视图
        self._stack = QStackedWidget()

        # 视图1: Markdown预览
        self._md_view = QTextEdit()
        self._md_view.setReadOnly(True)
        self._stack.addWidget(self._md_view)

        # 视图2: 字段提取表格
        self._field_table = QTableWidget()
        self._field_table.setColumnCount(3)
        self._field_table.setHorizontalHeaderLabels(["字段", "值", "状态"])
        self._stack.addWidget(self._field_table)

        # 视图3: 表格数据预览
        self._table_view = QTextEdit()
        self._table_view.setReadOnly(True)
        self._stack.addWidget(self._table_view)

        layout.addWidget(self._stack)

    def load_result(self, page_result, finance_result=None):
        """加载解析结果"""
        self._page_result = page_result
        self._finance_result = finance_result
        self._update_current_view()

    def _on_view_changed(self, idx: int):
        self._update_current_view()

    def _update_current_view(self):
        idx = self._view_selector.currentIndex()
        if self._page_result is None:
            return
        if idx == 0:
            # Markdown
            self._md_view.setMarkdown(self._page_result.markdown or "(无内容)")
        elif idx == 1:
            # 字段提取
            if self._finance_result:
                self._field_table.setRowCount(len(self._finance_result.fields))
                for i, f in enumerate(self._finance_result.fields):
                    self._field_table.setItem(i, 0, QTableWidgetItem(f.label))
                    self._field_table.setItem(i, 1, QTableWidgetItem(f.value))
                    status = "✓" if f.validated else f"⚠ {f.validation_msg}"
                    item = QTableWidgetItem(status)
                    if not f.validated:
                        item.setForeground(Qt.GlobalColor.red)
                    self._field_table.setItem(i, 2, item)
                self._field_table.resizeColumnsToContents()
        elif idx == 2:
            # 表格数据
            if self._page_result.tables:
                texts = []
                for i, df in enumerate(self._page_result.tables):
                    texts.append(f"### 表格 {i+1}\n\n{df.to_markdown(index=False)}")
                self._table_view.setMarkdown("\n\n".join(texts))
            else:
                self._table_view.setPlainText("(未检测到表格)")

    def _on_export(self):
        """导出当前结果"""
        if self._page_result is None:
            return
        filepath, _ = QFileDialog.getSaveFileName(
            self, "导出结果", "",
            "Markdown (*.md);;JSON (*.json);;Word (*.docx);;Excel (*.xlsx)"
        )
        if not filepath:
            return
        try:
            if filepath.endswith('.md'):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(self._page_result.markdown or "")
            elif filepath.endswith('.json'):
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(self._page_result.raw_json, f, ensure_ascii=False, indent=2)
            elif filepath.endswith('.docx'):
                from docx import Document
                doc = Document()
                doc.add_paragraph(self._page_result.markdown or "(空)")
                doc.save(filepath)
            elif filepath.endswith('.xlsx'):
                import pandas as pd
                if self._page_result.tables:
                    with pd.ExcelWriter(filepath) as writer:
                        for i, df in enumerate(self._page_result.tables):
                            df.to_excel(writer, sheet_name=f"Table_{i+1}", index=False)
                else:
                    pd.DataFrame().to_excel(filepath, index=False)
            QMessageBox.information(self, "导出成功", f"已保存到:\n{filepath}")
        except Exception as e:
            QMessageBox.critical(self, "导出失败", str(e))
```

- [ ] **Step 2: 集成到 main_window 右侧面板**

在 `_on_page_parsed()` 方法中调用 `self._result_panel.load_result(result)`。
同时注入 `FinanceProcessor` 处理结果（如果配置启用了财务模式）。

- [ ] **Step 3: Commit**

```bash
git add app/ui/widgets/result_panel.py app/ui/main_window.py
git commit -m "feat: add ResultPanel with markdown/field/table views and multi-format export"
```

---

### Task 11: 配置更新 + PdfCanvas 框选开关

**Files:**
- Modify: `app/config.yaml` — 新增 `engine` 和 `layout_visualization` 配置段
- Modify: `app/ui/widgets/pdf_canvas.py` — 添加 `set_drawing_enabled(bool)` 方法

**Interfaces:**
- Consumes: 框架配置
- Produces: `PdfCanvas.set_drawing_enabled(enabled: bool)`

- [ ] **Step 1: 更新 `config.yaml`**

```yaml
# paddleocr_vl 段新增 engine 字段，use_layout_detection 改为 true
  paddleocr_vl:
    device: gpu:0             # ← 如果是GPU模式改这里
    engine: paddle_dynamic     # 新增
    use_layout_detection: true # 改为 true
    # ... 保留其他字段 ...

# 新增段
layout_visualization:
  enabled: true
  colors:
    text: "#4A90D9"
    table: "#27AE60"
    formula: "#E67E22"
    chart: "#8E44AD"
    seal: "#E74C3C"

finance:
  enabled: false
  invoice:
    keywords: ["发票号码", "开票日期", "价税合计", "购买方", "销售方"]
  validation:
    amount_tolerance: 0.01
    tax_rate: 0.13
```

- [ ] **Step 2: 给 PdfCanvas 添加框选开关**

```python
# 在 pdf_canvas.py 的 PdfCanvas 类中添加:
    def set_drawing_enabled(self, enabled: bool):
        """启用/禁用框选功能（VLM模式下禁用）"""
        self._drawing_enabled = enabled
        if not enabled:
            self.setCursor(Qt.CursorShape.ArrowCursor)
```

在 `__init__` 中初始化：
```python
        self._drawing_enabled = True
```

在 `mousePressEvent` / `mouseMoveEvent` / `mouseReleaseEvent` 中框选相关逻辑前检查：
```python
        if not self._drawing_enabled:
            super().mousePressEvent(event)
            return
```

- [ ] **Step 3: Commit**

```bash
git add app/config.yaml app/ui/widgets/pdf_canvas.py
git commit -m "feat: add config fields for engine/layout/finance, drawing toggle for pdf_canvas"
```

---

### Task 12: 端到端验证

- [ ] **Step 1: 验证 PaddleOCR-VL 自动模式**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR
source venv/Scripts/activate
python main.py
```
操作：启动 → 确认引擎为 PaddleOCR-VL → 加载 PDF → 点击"解析"
Expected:
- 无 `int(Variable)` 错误
- 日志显示 `engine=paddle_dynamic`
- 版面可视化显示彩色 block 覆盖层
- Markdown 预览正常显示

- [ ] **Step 2: 验证 RapidOCR 手动模式**

操作：下拉框切换到 RapidOCR → 确认框选功能正常 → 画框 → OCR
Expected: 区域OCR正常工作，Excel导出正常

- [ ] **Step 3: 验证引擎切换**

操作：PaddleOCR-VL ↔ RapidOCR 反复切换
Expected: UI 布局正确切换（工具栏/面板显隐），无崩溃

- [ ] **Step 4: 验证导出**

操作：四种格式各导出一次
Expected: `.md` / `.json` / `.docx` / `.xlsx` 均正确生成

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "chore: final integration - dual mode architecture complete"
```
