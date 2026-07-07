# Bug 修复 + 性能/显存优化 实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax.

**Goal:** 修复 14 个 Bug（4高+5中+5低），增加 5 项性能/显存优化（基于 PaddleOCR-VL 官方文档）

**Architecture:** 逐文件修改，高优 Bug 优先。ocr_engine_paddle.py 变更最多（11项），分两个 Task 先后处理。其余文件各自成 Task

**Tech Stack:** Python 3.12, PyQt6, PaddleOCR-VL, RapidOCR

## Global Constraints

- 保持现有 API 兼容（`recognize_page` 签名不变，`FileResult` 结构兼容旧数据）
- 修改后 64 个现有测试必须通过
- 所有新增配置项提供合理默认值
- 遵循项目现有代码风格（中文注释、logging 格式）

---

### Task 1: FinanceProcessor — B1 (配置路径) + B3 (退步值) + B7 (阈值DPI)

**Files:**
- Modify: `app/core/finance_processor.py`

**Interfaces:**
- Produces: `FinanceProcessor.__init__` 正确从 `cfg["finance"]["invoice"]` 和 `cfg["finance"]["validation"]` 读取；`process()` 的 fallback 不返回关键词自身；`_find_neighbor` 使用 DPI 感知阈值

- [ ] **Step 1: 修复配置路径 (B1)**

将 `finance_processor.py:12-17` 改为：
```python
def __init__(self, config: Optional[dict] = None):
    cfg = config or {}
    finance_cfg = cfg.get("finance", {})
    self._keywords: List[str] = finance_cfg.get("invoice", {}).get("keywords", [
        "发票号码", "开票日期", "价税合计", "购买方", "销售方"
    ])
    self._amount_tolerance: float = finance_cfg.get("validation", {}).get("amount_tolerance", 0.01)
    self._tax_rate: float = finance_cfg.get("validation", {}).get("tax_rate", 0.13)
```

- [ ] **Step 2: 修复退步值返回关键词自身 (B3)**

将 `finance_processor.py:33-35` 改为：
```python
value = _find_neighbor(blocks, anchor, direction='right')
if not value:
    # 从anchor.content中提取关键词后的值部分（如"发票号码：12345678" → "12345678"）
    parts = re.split(r'[：:]\s*', anchor.content, maxsplit=1)
    value = parts[1].strip() if len(parts) > 1 else ""
```

文件顶部添加（已存在 `import re`，无需新增导入）

- [ ] **Step 3: 修复邻近搜索阈值硬编码 (B7)**

将 `_find_neighbor` 函数签名和 Y 阈值计算改为 DPI 感知：

```python
def _find_neighbor(blocks: List[Block], anchor: Block, direction: str = 'right') -> str:
    if anchor.bbox is None:
        return ""
    ax1, ay1, ax2, ay2 = anchor.bbox
    
    # 从中位 block 高度计算行高阈值，下限 30px
    heights = [(b.bbox[3] - b.bbox[1]) for b in blocks if b.bbox is not None and (b.bbox[3] - b.bbox[1]) > 0]
    median_h = sorted(heights)[len(heights)//2] if heights else 0
    y_tolerance = max(30, int(median_h * 1.5))
    
    candidates = []
    for b in blocks:
        if b is anchor or b.bbox is None:
            continue
        bx1, by1 = b.bbox[0], b.bbox[1]
        if direction == 'right' and abs(by1 - ay1) < y_tolerance and bx1 >= ax2:
            candidates.append((bx1, b))
        elif direction == 'below' and abs(bx1 - ax1) < 30 and by1 >= ay2:
            candidates.append((by1, b))
    if candidates:
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1].content
    return ""
```

- [ ] **Step 4: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/core/finance_processor.py
git commit -m "fix: FinanceProcessor config path (B1), fallback value (B3), DPI-aware neighbor threshold (B7)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: MainWindow — B2 (复用 FinanceProcessor)

**Files:**
- Modify: `app/ui/main_window.py`

**Interfaces:**
- Consumes: `FinanceProcessor(self.config)` from Task 1 (config 路径已修复)
- Produces: `self._finance_processor` 属性在 `__init__` 中创建

- [ ] **Step 1: 在 __init__ 中创建 FinanceProcessor 实例**

在 `main_window.py` 的 `__init__` 方法末尾（约第 194 行 `QTimer.singleShot(100, ...)` 之前），添加：

```python
# 财务字段处理器（引擎无关，复用实例）
try:
    from app.core.finance_processor import FinanceProcessor
    self._finance_processor = FinanceProcessor(self.config)
except ImportError:
    self._finance_processor = None
```

- [ ] **Step 2: 修改 _on_page_parsed 复用实例 (B2)**

将 `main_window.py:2172-2180` 改为：

```python
        # 财务字段提取
        finance_result = None
        if result.blocks:
            try:
                if self._finance_processor is not None:
                    finance_result = self._finance_processor.process(result.blocks)
            except Exception:
                pass
```

删除原来的 `from app.core.finance_processor import FinanceProcessor` 导入行。

- [ ] **Step 3: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add app/ui/main_window.py
git commit -m "fix: reuse FinanceProcessor instance, fix config passing (B2)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: FileResult key 改为 region_id (B4)

**Files:**
- Modify: `app/models/ocr_result.py`
- Modify: `app/core/batch_processor.py`
- Modify: `app/core/exporter.py`
- Modify: `app/ui/widgets/field_panel.py`

**Interfaces:**
- Produces: `FileResult.fields` key 从 `field_name` 改为 `region_id`；`FieldResult` 新增 `region_id` 字段
- Consumed by: `show_preview_result()`, `Exporter.to_excel()`, `Exporter.to_csv()`

- [ ] **Step 1: 修改 FieldResult — 新增 region_id**

将 `app/models/ocr_result.py` 改为：

```python
from dataclasses import dataclass
from typing import Dict


@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    region_id: str = ""       # 新增：关联的 Region.id
    manually_edited: bool = False
    match_level: int = 0
    engine: str = ""


@dataclass
class FileResult:
    source_file: str
    fields: Dict[str, FieldResult]  # key=region_id (不再是 field_name)
    success: bool = True
    error_msg: str = ""
```

- [ ] **Step 2: 修改 batch_processor.py — key 改为 region_id**

将 `batch_processor.py:88-98` 的 VL 路径改为：

```python
                    for region in regions:
                        text, conf, match_level, _ = page_results.get(
                            region.id, ("", 0.0, 0, None)
                        )
                        fields[region.id] = FieldResult(
                            field_name=region.field_name,
                            text=text,
                            confidence=conf,
                            match_level=match_level,
                            engine=self.ocr.engine_name,
                            region_id=region.id,
                        )
```

将 `batch_processor.py:111-117` 的 RapidOCR 路径改为：

```python
                        text, conf = self.ocr.recognize(crop, region.ocr_mode)
                        fields[region.id] = FieldResult(
                            field_name=region.field_name,
                            text=text,
                            confidence=conf,
                            engine="rapidocr",
                            region_id=region.id,
                        )
```

- [ ] **Step 3: 修改 Exporter — 使用 region_id 遍历并按 field_name 去重显示**

将 `exporter.py:11-13` 的 `to_excel` 中字段遍历改为：

```python
            seen_names = set()
            for region_id, fr in r.fields.items():
                # 如果多个 region 有同名 field_name，用 region_id 区分列名
                col_name = fr.field_name
                if col_name in seen_names:
                    col_name = f"{fr.field_name}_{region_id[:8]}"
                seen_names.add(fr.field_name)
                row[col_name] = fr.text
                if include_confidence:
                    row[f"{col_name}_置信度"] = round(fr.confidence, 3)
                row[f"{col_name}_引擎"] = fr.engine
                row[f"{col_name}_匹配级别"] = fr.match_level
                row[f"{col_name}_人工修正"] = "是" if fr.manually_edited else "否"
```

将 `to_csv` 方法做同样修改（与 `to_excel` 模式一致）。

- [ ] **Step 4: 修改 show_preview_result — 用 region_id 直接查找**

将 `field_panel.py:338-343` 改为：

```python
            # 使用 region_id 直接查找结果（B4 修复后 FileResult.fields key=region_id）
            if rid in file_result.fields:
                fr = file_result.fields[rid]
                self._preview_results[rid] = fr
```

删除原来的 `field_name = region.field_name` 和 `if field_name in file_result.fields` 行。

- [ ] **Step 5: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add app/models/ocr_result.py app/core/batch_processor.py app/core/exporter.py app/ui/widgets/field_panel.py
git commit -m "fix: use region_id as FileResult.fields key to prevent same-name overwrite (B4)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: OcrEnginePaddle Part 1 — 基础设施 (B8, B9, B10, B11, B12)

**Files:**
- Modify: `app/core/ocr_engine_paddle.py`

**Interfaces:**
- Produces: `_vram_guard(image_size) -> int`, `_post_inference_cleanup()`, 更新 `_calc_max_pixels`
- Consumed by: Task 5 中 `recognize_page_auto` 和 `recognize_page`

- [ ] **Step 1: 抽取 `_vram_guard` 方法 (B8)**

在 `_calc_max_pixels` 方法之后添加：

```python
    def _vram_guard(self, image_size: Tuple[int, int]) -> int:
        """VRAM守卫：返回安全的 max_pixels，-1 表示应跳过推理"""
        max_px = self._calc_max_pixels(image_size)
        free_vram = self._get_free_vram_gb()
        if free_vram < self._min_free_vram_gb:
            logger.warning(f"VRAM不足 ({free_vram:.2f}GB < {self._min_free_vram_gb}GB)，跳过推理")
            return -1
        elif free_vram < 1.0:
            max_px = min(max_px, 2 * 1024 * 1024)
            logger.info(f"VRAM紧张 ({free_vram:.2f}GB)，降低分辨率到 {max_px/1e6:.1f}M 像素")
        return max_px

    def _post_inference_cleanup(self) -> None:
        """推理后释放 CUDA 临时缓存（CPU 模式下安全跳过）"""
        try:
            import paddle
            paddle.device.cuda.empty_cache()
        except (OSError, RuntimeError, AttributeError):
            pass  # CPU 模式或 Paddle 未加载时安全跳过
```

- [ ] **Step 2: 用 `_vram_guard` 替换 recognize_page_auto 中的内联代码 (B8)**

将 `recognize_page_auto` 方法中第 173-177 行替换为：

```python
        max_px = self._vram_guard(image.size)
        if max_px < 0:
            return PageResult(blocks=[], markdown="", image_size=(W, H))
```

将 `recognize_page_auto` 中第 193-196 行的 `try/except` 替换为：

```python
            self._last_used_time = time.monotonic()
            self._post_inference_cleanup()
```

- [ ] **Step 3: 用 `_vram_guard` 替换 recognize_page 中的内联代码 (B8)**

将 `recognize_page` 方法中第 238-248 行替换为：

```python
        max_px = self._vram_guard(image.size)
        if max_px < 0:
            return {r.id: ("", 0.0, 0, None) for r in regions}
```

将 `recognize_page` 中第 263-267 行的 `try/except` 替换为：

```python
            self._last_used_time = time.monotonic()
            self._post_inference_cleanup()
```

- [ ] **Step 4: 修复 empty_cache 异常捕获 (B9)**

（已在上一步中通过 `_post_inference_cleanup()` 统一处理）

- [ ] **Step 5: Warmup 后清理 CUDA 缓存 (B10)**

将 `_warmup` 方法中第 121-124 行改为：

```python
    def _warmup(self) -> None:
        if not self._pipeline:
            return
        try:
            dummy = np.zeros((64, 64, 3), dtype=np.uint8)
            list(self._pipeline.predict(dummy, temperature=0))
            self._post_inference_cleanup()
        except Exception:
            pass
```

- [ ] **Step 6: 调整 max_pixels 界限 (B11)**

将 `_calc_max_pixels` 方法改为：

```python
    def _calc_max_pixels(self, image_size: Tuple[int, int]) -> int:
        """根据图片尺寸计算 max_pixels，上限 8M（8GB 显卡安全），下限 0.5M"""
        w, h = image_size
        actual_pixels = w * h
        return max(min(actual_pixels, 8 * 1024 * 1024), 512 * 1024)
```

- [ ] **Step 7: numpy 转换移出锁外 (B12)**

将 `recognize_page_auto` 中的第 184 行移到锁外：

```python
        try:
            arr = np.array(image) if isinstance(image, Image.Image) else image
            with self._pipeline_lock:
                self._ensure_loaded()
                if self._pipeline is None:
                    raise RuntimeError("Pipeline was unloaded after initialization")
                outputs = list(self._pipeline.predict(
                    arr,
                    temperature=0,
                    max_pixels=max_px,
                ))
                self._last_used_time = time.monotonic()
            self._post_inference_cleanup()
```

将 `recognize_page` 中第 255 行做同样的修改（numpy 转换移出锁外）。

- [ ] **Step 8: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 9: Commit**

```bash
git add app/core/ocr_engine_paddle.py
git commit -m "refactor: extract _vram_guard/_post_inference_cleanup, fix exception handling, warmup cleanup, max_pixels tuning, numpy outside lock (B8,B9,B10,B11,B12)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: OcrEnginePaddle Part 2 — 统一解析 + 性能优化 (B5, P1, P2, P3, P4, P5)

**Files:**
- Modify: `app/core/ocr_engine_paddle.py`

**Interfaces:**
- Consumes: `_vram_guard`, `_post_inference_cleanup` (from Task 4); `extract_blocks` from `layout_extractor.py`
- Produces: 精简的 `_extract_elements`；`recognize_page` 委托给 `recognize_page_auto`；`vlm_extra_args`, `max_new_tokens`, `min_pixels` 传入 `pipeline.predict()`

- [ ] **Step 1: 配置读取 — 新增配置项**

在 `__init__` 方法中添加新配置读取（在 `self._warmup_on_startup` 行之后）：

```python
            self._max_new_tokens = vl_cfg.get("max_new_tokens", 2048)
            self._min_pixels = vl_cfg.get("min_pixels", 512 * 512)
            self._use_tensorrt = vl_cfg.get("use_tensorrt", False)
            self._enable_hpi = vl_cfg.get("enable_hpi", False)
            # vlm_extra_args: 按元素类型分级分辨率
            vlm_res_cfg = vl_cfg.get("vlm_resolution", {})
            self._vlm_extra_args = {
                "ocr_min_pixels": vlm_res_cfg.get("text", {}).get("min_pixels", 262144),
                "ocr_max_pixels": vlm_res_cfg.get("text", {}).get("max_pixels", 1048576),
                "table_min_pixels": vlm_res_cfg.get("table", {}).get("min_pixels", 524288),
                "table_max_pixels": vlm_res_cfg.get("table", {}).get("max_pixels", 4194304),
                "formula_min_pixels": vlm_res_cfg.get("formula", {}).get("min_pixels", 524288),
                "formula_max_pixels": vlm_res_cfg.get("formula", {}).get("max_pixels", 4194304),
                "chart_min_pixels": vlm_res_cfg.get("chart", {}).get("min_pixels", 524288),
                "chart_max_pixels": vlm_res_cfg.get("chart", {}).get("max_pixels", 4194304),
                "seal_min_pixels": vlm_res_cfg.get("seal", {}).get("min_pixels", 65536),
                "seal_max_pixels": vlm_res_cfg.get("seal", {}).get("max_pixels", 262144),
            }
```

- [ ] **Step 2: 修改 `recognize_page_auto` 传递新参数 (P2, P3, P5)**

将 `recognize_page_auto` 中 `self._pipeline.predict(...)` 调用改为：

```python
                outputs = list(self._pipeline.predict(
                    arr,
                    temperature=0,
                    max_pixels=max_px,
                    min_pixels=self._min_pixels,
                    max_new_tokens=self._max_new_tokens,
                    vlm_extra_args=self._vlm_extra_args,
                ))
```

同样修改 `recognize_page` 中对应的 `predict` 调用。

- [ ] **Step 3: 修改 `initialize` 传递 TensorRT/HPI 参数 (P4)**

将 `initialize` 方法中 `PaddleOCRVL(...)` 构造函数改为：

```python
                self._pipeline = PaddleOCRVL(
                    vl_rec_model_name=self._model_name,
                    device=self._device,
                    precision=self._precision,
                    engine="paddle_dynamic",
                    use_layout_detection=self._use_layout_detection,
                    use_tensorrt=self._use_tensorrt,
                    enable_hpi=self._enable_hpi,
                )
```

- [ ] **Step 4: 精简 `_extract_elements` — 委托给 `extract_blocks` (B5)**

将 `_extract_elements` 方法整个替换为：

```python
    def _extract_elements(self, output) -> List[dict]:
        """从 VLM Result 提取 elements 列表（委托给 LayoutExtractor 的 extract_blocks）"""
        blocks = extract_blocks(output)
        return [
            {
                "type": b.block_type,
                "text": b.content,
                "confidence": b.confidence,
                "bbox": b.bbox if b.bbox != [0, 0, 0, 0] else None,
            }
            for b in blocks
        ]
```

- [ ] **Step 5: 重构 `recognize_page` — 委托给 `recognize_page_auto` (P1)**

将 `recognize_page` 方法整个替换为：

```python
    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — 委托给 recognize_page_auto，从 PageResult.blocks 做 FieldMatcher 匹配。
        保留三级匹配（IoU/就近/关键词）行为不变。
        """
        W, H = image.size

        # 为每个 region 计算像素坐标
        pixel_bboxes = {}
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            pixel_bboxes[region.id] = [left, top, right, bottom]

        # 调用 auto 路径获取统一的 Block[] + Markdown（复用一次推理）
        page_result = self.recognize_page_auto(image)

        if not page_result.blocks:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # Block → elements dict 格式（供 FieldMatcher 消费）
        elements = _blocks_to_elements(page_result.blocks)

        # 三级匹配
        match_results = self._matcher.match(elements, regions, page_result.markdown, pixel_bboxes)

        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)

        return results
```

在文件顶部模块级添加辅助函数（放在 import 区之后）：

```python
def _blocks_to_elements(blocks: List[Block]) -> List[dict]:
    """将 Block[] 转换为 FieldMatcher 兼容的 elements dict 格式"""
    return [
        {
            "type": b.block_type,
            "text": b.content,
            "confidence": b.confidence,
            "bbox": b.bbox if b.bbox != [0, 0, 0, 0] else None,
        }
        for b in blocks
    ]
```

在 `ocr_engine_paddle.py` 文件头部 import 区增加 `Block` 导入（已有 `from app.models.page_result import PageResult, Block`，确认无误）。

- [ ] **Step 6: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add app/core/ocr_engine_paddle.py
git commit -m "perf: unify element extraction, recognize_page delegates to auto path, add vlm_extra_args/max_new_tokens/tensorrt support (B5,P1,P2,P3,P4,P5)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: PdfCanvas — handle 重建优化 (B6)

**Files:**
- Modify: `app/ui/widgets/pdf_canvas.py`

- [ ] **Step 1: 修改 `_create_handles` 实现增量更新**

将 `SelectableRectItem._create_handles` 方法（约第 80-95 行）改为：

```python
    def _create_handles(self):
        """创建或更新调整手柄的位置（首次创建，后续仅移动）"""
        if self.handles:
            # handles 已存在：仅更新位置
            self.update_handle_positions()
            return
        rect = self.rect()
        self.handles.append(ResizeHandle(rect.left(), rect.top(), HANDLE_SIZE, 'tl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.top(), HANDLE_SIZE, 'tr', self))
        self.handles.append(ResizeHandle(rect.left(), rect.bottom(), HANDLE_SIZE, 'bl', self))
        self.handles.append(ResizeHandle(rect.right(), rect.bottom(), HANDLE_SIZE, 'br', self))
        self.handles.append(ResizeHandle(rect.center().x(), rect.center().y(), HANDLE_SIZE, 'move', self))
        self._update_handles_visibility(False)
```

- [ ] **Step 2: 修改 `update_region` 不再调用 `_create_handles`**

将 `PdfCanvas.update_region` 方法（约第 578-591 行）中第 586 行的 `item._create_handles()` 改为 `item.update_handle_positions()`：

```python
    def update_region(self, region_id: str, region: Region):
        if region_id in self.region_items:
            item = self.region_items[region_id]
            rect = QRectF(region.x * self.img_w, region.y * self.img_h,
                         region.w * self.img_w, region.h * self.img_h)
            item.setRect(rect)
            item.update_handle_positions()
            item._update_handles_visibility(item.isSelected())
            self.regions_data[region_id] = region
        else:
            self._add_region_item(region)
```

- [ ] **Step 3: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add app/ui/widgets/pdf_canvas.py
git commit -m "perf: avoid handle recreation in update_region, reuse existing handles (B6)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: Config 对齐 + 新增配置项 (B13, P2, P3, P4)

**Files:**
- Modify: `app/utils/config_loader.py`
- Modify: `app/config.yaml`

- [ ] **Step 1: 修正默认配置 (B13)**

将 `config_loader.py:105-106` 的默认值改为与 `config.yaml` 一致：

```python
                "use_layout_detection": True,  # 与 config.yaml 对齐
                "warmup_on_startup": True,  # 与 config.yaml 对齐
```

- [ ] **Step 2: 添加新配置项到 config.yaml (P2, P3, P4)**

在 `app/config.yaml` 的 `paddleocr_vl:` 段末尾添加：

```yaml
    use_tensorrt: false
    enable_hpi: false
    max_new_tokens: 2048
    min_pixels: 262144
    vlm_resolution:
      text:
        min_pixels: 262144
        max_pixels: 1048576
      table:
        min_pixels: 524288
        max_pixels: 4194304
      formula:
        min_pixels: 524288
        max_pixels: 4194304
      chart:
        min_pixels: 524288
        max_pixels: 4194304
      seal:
        min_pixels: 65536
        max_pixels: 262144
```

- [ ] **Step 3: 确保 config_loader 默认配置也包含新配置项**

在 `config_loader.py` 的 `get_default_config()` 中 `paddleocr_vl` 段添加相同默认值（与 Step 2 的 YAML 一致）。

- [ ] **Step 4: Run tests**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/config.yaml app/utils/config_loader.py
git commit -m "chore: align default config with config.yaml, add vlm_resolution/max_new_tokens/tensorrt config fields (B13,P2,P3,P4)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: GpuStatusWidget — 死代码清理 (B14)

**Files:**
- Modify: `app/ui/widgets/gpu_status.py`

- [ ] **Step 1: 删除无效的 closeEvent**

删除 `gpu_status.py:87-90`：

```python
    # 删除以下4行：
    def closeEvent(self, event):
        """关闭时停止定时器"""
        self._timer.stop()
        super().closeEvent(event)
```

- [ ] **Step 2: Commit**

```bash
git add app/ui/widgets/gpu_status.py
git commit -m "chore: remove dead closeEvent from GpuStatusWidget (B14)

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: E2E 验证

**Files:** 无修改，仅验证

- [ ] **Step 1: 运行全部测试**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && source .venv/Scripts/activate && python -m pytest tests/ -v
```
预期：64 tests pass

- [ ] **Step 2: 检查代码一致性**

```bash
cd c:/Users/Panda/OneDrive/panda/tools/PDFOCR && git diff --stat main..HEAD
```

- [ ] **Step 3: 验证关键修复点**

核查以下内容（不执行，code review 确认）：
1. `_extract_elements` 不再包含独立的 JSON 解析逻辑（B5）
2. `FileResult.fields` 的 key 为 `region_id`（B4）
3. `FinanceProcessor.__init__` 从 `cfg["finance"]` 路径读取（B1）
4. `recognize_page` 内部调用 `recognize_page_auto`（P1）
5. `_vram_guard` 和 `_post_inference_cleanup` 被两个方法共用（B8）
