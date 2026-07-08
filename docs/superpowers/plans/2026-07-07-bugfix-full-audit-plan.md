# Bug 修复 — 全面审计实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 修复 PDFOCR 项目中 70 个功能/UI bug（5 Critical + 6 High + 25 Medium + 34 Low），27 个文件

**策略:** 按严重程度从高到低执行，每任务自包含可独立测试

**Tech Stack:** Python 3.12, PyQt6, PaddleOCR-VL-1.6, RapidOCR

## Global Constraints

- 所有 config 默认值必须以 `app/config.yaml`（实际加载的配置）为准
- `use_layout_detection` 和 `warmup_on_startup` 默认值统一为 `False`
- `precision` 统一为 `fp16`（`app/config.yaml` 当前误写为 `fp32`）
- 涉及历史文件的修改必须向后兼容旧格式
- 所有修改必须通过已有测试集（`pytest tests/ -v`）
- 引擎默认值用于 config 缺失时的保底，不应高于 config 指定值

---

### Task 1: History Manager 修复（Critical — 数据丢失）

**涉及 bug:** C2, C4, C5, M20, L21, L22
**文件:** `app/utils/history_manager.py`（仅此 1 个文件）
**说明:** History 是用户 OCR 结果持久化存储，当前有 6 个严重设计缺陷导致数据丢失和竞态损坏

- [ ] **Step 1: 添加线程锁保护 `_cached_history`**

```python
# 在 history_manager.py 顶部
import threading

# __init__ 中添加:
self._lock = threading.Lock()

# _load_history 用锁保护:
def _load_history(self) -> List[Dict]:
    with self._lock:
        if self._cached_history is not None:
            return self._cached_history
        if not os.path.exists(self._history_file):
            self._cached_history = []
            return self._cached_history
        try:
            with open(self._history_file, "r", encoding="utf-8") as f:
                self._cached_history = json.load(f)
            return self._cached_history
        except Exception as e:
            logger.warning(f"历史文件加载失败 ({e})，备份到 .bak")
            import shutil
            shutil.copy2(self._history_file, self._history_file + ".bak")
            self._cached_history = []
            return self._cached_history

# add_record 用锁保护:
def add_record(self, record: dict) -> None:
    with self._lock:
        history = self._load_history()
        history.append(record)
        self._save_history(history)

# get_history 用锁保护:
def get_history(self) -> List[Dict]:
    with self._lock:
        return list(self._load_history())

# _save_history 用锁保护，失败的 save 不覆盖好文件:
def _save_history(self, history: List[Dict]) -> None:
    tmp = self._history_file + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self._history_file)
    except Exception as e:
        logger.error(f"历史文件保存失败: {e}")
        if os.path.exists(tmp):
            os.remove(tmp)
```

- [ ] **Step 2: 反序列化使用 `.get()` 代替直接索引**

```python
# restore_results 中:
field_result = FieldResult(
    field_name=fn,
    text=fd.get("text", ""),
    confidence=fd.get("confidence", 0.0),
    match_level=fd.get("match_level", 0),
    engine=fd.get("engine", ""),
    region_id=fd.get("region_id", ""),
)
```

- [ ] **Step 3: 序列化时包含 `region_id`**

```python
# add_record 序列化:
fields_dict = {
    rid: {
        "field_name": fr.field_name,
        "text": fr.text,
        "confidence": fr.confidence,
        "match_level": fr.match_level,
        "engine": fr.engine,
        "region_id": fr.region_id,
    }
    for rid, fr in file_result.fields.items()
}
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/ -v -k "history" 2>&1 || echo "no history-specific tests"
# 然后全部测试
python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/utils/history_manager.py
git commit -m "fix: History Manager 数据丢失修复 (C2/C4/C5/M20)

- 添加线程锁保护 _cached_history 并发访问
- 反序列化使用 .get() 避免 KeyError 清空历史
- 失败时备份损坏文件不覆盖
- 序列化包含 region_id 字段
- 原子写入 (tmp + replace) 防写入中断损坏"
```

---

### Task 2: 配置默认值对齐（High — 显存浪费）

**涉及 bug:** H1, H2, H5, M25, L25, L31
**文件:** `app/config.yaml`, `app/core/ocr_engine_paddle.py`, `config.yaml`

- [ ] **Step 1: 修复 `app/config.yaml` precision 错误**

```yaml
# app/config.yaml:29 改为
    precision: fp16
```

- [ ] **Step 2: 修复引擎默认值覆盖配置**

```python
# ocr_engine_paddle.py:86-87, 108-109
self._use_layout_detection = vl_cfg.get("use_layout_detection", False)
self._warmup_on_startup = vl_cfg.get("warmup_on_startup", False)
self._max_vram_gb = vl_cfg.get("max_vram_gb", 7.8)
self._min_free_vram_gb = vl_cfg.get("min_free_vram_gb", 0.1)
```

- [ ] **Step 3: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add app/config.yaml app/core/ocr_engine_paddle.py
git commit -m "fix: 配置默认值对齐 config (H1/H2/H5)

- app/config.yaml precision: fp16（原为 fp32，翻倍显存）
- use_layout_detection 默认 False（匹配 config）
- warmup_on_startup 默认 False（匹配 config）
- max_vram_gb 默认 7.8（匹配 config）
- min_free_vram_gb 默认 0.1（匹配 config）"
```

---

### Task 3: MainWindow 线程安全与窗口生命周期（Critical — 崩溃）

**涉及 bug:** C3, H3, M14, M15
**文件:** `app/ui/main_window.py`（仅此 1 个文件）

- [ ] **Step 1: 修复窗口关闭后 use-after-free（C3）**

```python
# __init__ 中初始化:
self._destroyed = False

# closeEvent 中:
def closeEvent(self, event):
    self._destroyed = True
    self._init_gen += 1  # 使所有待处理回调失效
    # ... 现有逻辑 ...
    self._save_current_pdf_config()

# _on_ocr_ready 中添加:
def _on_ocr_ready(self):
    if self._destroyed:
        return
    # ... 现有逻辑 ...
```

- [ ] **Step 2: 修复 PIL Image 线程竞态（H3）**

```python
# _on_parse_current_page 中:
def _on_parse_current_page(self):
    page_image = self._current_page_image.copy()  # 主线程复制，线程安全
    threading.Thread(target=self._do_parse, args=(page_image,), daemon=True).start()
```

- [ ] **Step 3: 修复 TOCTOU 竞态和 stale processor（M14, M15）**

```python
# _on_engine_switched 中添加:
self.processor = None  # 立即清空过期 processor

# 重初始化完成后重建:
def _on_ocr_ready(self):
    if self._destroyed or self._init_gen != self._ready_gen:
        return
    self.processor = BatchProcessor(
        self.pdf_loader, self.ocr_engine, self.config,
        max_workers=self.config.get("batch", {}).get("max_workers", 4)
    )
    self.gpu_status.set_engine(self.ocr_engine)
```

- [ ] **Step 4: closeEvent 保存当前配置（M18）**

```python
def closeEvent(self, event):
    self._save_current_pdf_config()
    self._destroyed = True
    self._init_gen += 1
    # ... 后续 ...
```

- [ ] **Step 5: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add app/ui/main_window.py
git commit -m "fix: MainWindow 线程安全与窗口生命周期 (C3/H3/M14/M15/M18)

- _destroyed 标志防止 use-after-free
- _current_page_image 副本传递到后台线程
- 引擎切换时立即清空过期 processor
- closeEvent 保存当前 PDF 配置"
```

---

### Task 4: UI Widget 状态修复

**涉及 bug:** H4, M16, M17, M19, L18, L17, L19, L20
**文件:** `app/ui/widgets/history_panel.py`, `app/ui/widgets/field_panel.py`, `app/ui/main_window.py`

- [ ] **Step 1: History Panel — detail_widget 清除后永久隐藏（H4）**

```python
# history_panel.py _on_item_clicked 开头:
def _on_item_clicked(self, index):
    self.detail_widget.setVisible(True)
    # ... 现有逻辑 ...
```

- [ ] **Step 2: Field Panel — 字段类型修改持久化（M17）**

```python
# field_panel.py _on_field_type_changed 中发射信号:
def _on_field_type_changed(self, region_id, field_type):
    if region_id in self.regions:
        self.regions[region_id].field_type = field_type
        self.region_changed.emit(region_id)  # 已有信号

# main_window.py 连接:
self.field_panel.region_changed.connect(self._on_region_changed)
# _on_region_changed 中:
def _on_region_changed(self, region_id):
    self._schedule_save_config()
```

- [ ] **Step 3: 引擎热切换写入 config.yaml（M19）**

```python
# _on_engine_switched 热切换成功后:
if "restart" not in new_engine_type:
    import yaml
    with open(self._config_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(self.config, f, allow_unicode=True)
```

- [ ] **Step 4: 滚动同步防振荡（M16, L18）**

```python
# main_window.py 滚动同步:
self._syncing_scroll = False

# 画布滚动 → 视觉器同步:
self.canvas.verticalScrollBar().valueChanged.connect(
    lambda v: self._sync_scroll_to_visualizer(v)
)

def _sync_scroll_to_visualizer(self, value):
    if self._syncing_scroll:
        return
    self._syncing_scroll = True
    if self.layout_view.scene() and self.layout_view.scene().sceneRect().height() > 0:
        self.layout_view.verticalScrollBar().setValue(value)
    self._syncing_scroll = False

# 视觉器滚动 → 画布同步同理
```

- [ ] **Step 5: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add app/ui/widgets/history_panel.py app/ui/widgets/field_panel.py app/ui/main_window.py
git commit -m "fix: UI Widget 状态修复 (H4/M16/M17/M19)

- history_panel detail_widget 清除后恢复可见
- field_panel 字段类型修改持久化
- 引擎热切换写入 config.yaml
- 滚动同步防振荡保护"
```

---

### Task 5: Batch Worker/Processor 修复

**涉及 bug:** H6, M4, M5, M23, L2, L3, L11, L16
**文件:** `app/workers/batch_worker.py`, `app/core/batch_processor.py`

- [ ] **Step 1: 取消时只 emit cancelled 信号（H6）**

```python
# batch_worker.py run() 取消路径:
except InterruptedError:
    self.cancelled.emit()
    # 移除 self.finished_all.emit(self._completed_results)
    return
```

- [ ] **Step 2: 清空 `_completed_results` 防止跨批次累积（M23）**

```python
# batch_worker.py run() 开头:
def run(self):
    self._completed_results.clear()
    # ... 现有 ...
```

- [ ] **Step 3: `process_batch_with_templates` 异常保护（M5）**

```python
# batch_processor.py 中:
for future in as_completed(futures):
    try:
        idx, result = future.result()
    except Exception as e:
        idx = futures[future]
        result = FileResult(
            source_file=pdf_paths[idx] if idx < len(pdf_paths) else "",
            fields={}, success=False, error_msg=str(e)
        )
    with lock:
        results[idx] = result
        completed_count += 1
```

- [ ] **Step 4: BatchProcessor RapidOCR 路径统一调用 `recognize_page`（M4）**

```python
# batch_processor.py: 移除 RapidOCR 分支的裁剪逻辑，改用:
if not use_vl:
    page_results = self.ocr.recognize_page(
        rendered_image, regions, page_dpi=...
    )
    for region in regions:
        text, conf, match_level, _ = page_results.get(
            region.id, ("", 0.0, 0, None)
        )
        # 统一使用匹配逻辑（与 Paddle 路径一致）
```

此修改同时修复 match_level 始终为 0 的问题，因为 `RapidOCREngine.recognize_page` 内部会做匹配。

- [ ] **Step 5: 空 field_name 保护 + FieldResult.field_name 修正**

```python
# batch_processor.py 处理 region 时:
if not region.field_name:
    continue  # 跳过无名区域
```

FieldResult.field_name 保持为 region.field_name（原始名称），docstring 注明 dict key 可能包含 `_1`/`_2` 后缀。

- [ ] **Step 6: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add app/workers/batch_worker.py app/core/batch_processor.py
git commit -m "fix: Batch Worker/Processor 修复 (H6/M4/M5/M23/L2/L3)

- 取消时只 emit cancelled，不双信号
- 批次开始时清空 _completed_results
- future.result() 异常保护，不产生 None 条目
- RapidOCR 路径统一调用 recognize_page
- 空 field_name 保护"
```

---

### Task 6: PaddleOCR 引擎修复

**涉及 bug:** C1, M1, M2, L1, L12
**文件:** `app/core/ocr_engine_paddle.py`

- [ ] **Step 1: 修复 `_build_paddlex_config` 硬编码（C1）**

```python
# ocr_engine_paddle.py 顶部:
_MODEL_TO_PIPELINE = {
    "PaddleOCR-VL-1.6-0.9B": "PaddleOCR-VL-1.6",
    "PaddleOCR-VL-1.6-7B": "PaddleOCR-VL-1.6",
    "PaddleOCR-VL-1.5": "PaddleOCR-VL-1.5",
    "PaddleOCR-VL-1.0": "PaddleOCR-VL",
}

# _build_paddlex_config 中:
pipeline_name = _MODEL_TO_PIPELINE.get(self._model_name, "PaddleOCR-VL-1.6")
config = load_pipeline_config(pipeline_name)
```

- [ ] **Step 2: VRAM 耗尽返回可区分错误（M1）**

```python
# PageResult 添加 error 字段（page_result.py）
@dataclass
class PageResult:
    ...
    error: str = ""

# recognize_page_auto:
if max_px < 0:
    return PageResult(blocks=[], markdown="", image_size=(W, H),
                      error=f"VRAM不足 ({free_vram:.1f}GB < {self._min_free_vram_gb}GB)")

# recognize_page: 检查 error 并传播
if page_result.error:
    logger.warning(f"PaddleOCR 推理跳过: {page_result.error}")
```

- [ ] **Step 3: `empty_cache` 移到 idle unload 路径（M2）**

```python
# 从 recognize_page_auto 末尾移除 _post_inference_cleanup()
# 改为只在 _check_idle_unload 中调用:
def _check_idle_unload(self) -> None:
    if self._idle_unload_seconds <= 0:
        return
    with self._pipeline_lock:
        if not self._initialized:
            return
        elapsed = time.monotonic() - self._last_used_time
        if elapsed > self._idle_unload_seconds:
            self._post_inference_cleanup()  # unload 前清理
            self.unload()
```

- [ ] **Step 4: 清理死代码（L1）**

```python
# recognize_page_auto 中:
arr = np.array(image)  # 移除 isinstance 检查
```

- [ ] **Step 5: _calc_max_pixels 使用实际 VRAM（L12）**

```python
def _calc_max_pixels(self, image_size):
    w, h = image_size
    # 根据实际 VRAM 预算计算: 每 GB 约 1M 像素
    budget = max(self._max_vram_gb * 1_000_000, 512_000)
    return max(min(w * h, int(budget)), 512 * 1024)
```

- [ ] **Step 6: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add app/core/ocr_engine_paddle.py app/models/page_result.py
git commit -m "fix: PaddleOCR 引擎修复 (C1/M1/M2/L1/L12)

- _build_paddlex_config 支持多模型名映射
- VRAM 耗尽返回 error 信息可区分
- empty_cache 移到 idle unload 路径
- 清理死代码，_calc_max_pixels 使用实际 VRAM 预算"
```

---

### Task 7: OCR 引擎工厂修复

**涉及 bug:** M3, L29, L30
**文件:** `app/core/ocr_engine.py`, `main.py`

- [ ] **Step 1: 不突变调用者的 config（M3）**

```python
# ocr_engine.py get_ocr_engine:
vl_cfg = dict(config.get("ocr", {}).get("paddleocr_vl", {}))
if engine_type == "paddleocr_vl_cpu":
    vl_cfg["device"] = "cpu"
    vl_cfg["precision"] = "fp32"
else:
    vl_cfg["device"] = "gpu:0"
    vl_cfg["precision"] = "fp16"
```

- [ ] **Step 2: 统一 engine 默认值（L29）**

```python
# main.py:48:
engine_type = config.get("ocr", {}).get("engine", "paddleocr_vl")

# main_window.py:93:
engine_type = config.get("ocr", {}).get("engine", "paddleocr_vl")
```

- [ ] **Step 3: 环境变量覆盖补全 device（L30）**

```python
# config_loader.py:
if env_engine == "paddleocr_vl_cpu":
    config.setdefault("ocr", {}).setdefault("paddleocr_vl", {})["device"] = "cpu"
    config.setdefault("ocr", {}).setdefault("paddleocr_vl", {})["precision"] = "fp32"
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_engine.py main.py app/utils/config_loader.py
git commit -m "fix: OCR 引擎工厂修复 (M3/L29/L30)

- get_ocr_engine 不突变调用者 config
- 统一 engine 默认值为 paddleocr_vl
- PDFOCR_ENGINE=paddleocr_vl_cpu 同时设置 device=cpu"
```

---

### Task 8: FieldMatcher 修复

**涉及 bug:** M6, M7, L7
**文件:** `app/core/field_matcher.py`

- [ ] **Step 1: Y 轴容差随图片尺寸缩放（M6）**

```python
# field_matcher.py 中:
# 将硬编码 20px 改为比例值:
if abs(ey_mid - by_mid) < max(20, page_height * 0.01):
```
需要将 `page_height` 作为参数传入或从 bbox 范围估算。

- [ ] **Step 2: 关键词置信度反映匹配质量（M7）**

```python
# field_matcher.py _keyword_match 返回置信度:
matched_text = m.group(1).strip()
# 置信度基于匹配文本长度/关键词长度的比例
kw_len = len(kw)
text_len = len(matched_text)
confidence = min(0.5 + text_len / max(100, kw_len * 2), 0.95) if text_len > 0 else 0.5
```

- [ ] **Step 3: 空关键词跳过（L7）**

```python
# field_matcher.py _keyword_match:
for kw in region.match_keywords:
    if not kw or not kw.strip():
        continue
    # ... 匹配逻辑
```

- [ ] **Step 4: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add app/core/field_matcher.py
git commit -m "fix: FieldMatcher 修复 (M6/M7/L7)

- Y 轴容差按图片高度比例计算
- 关键词置信度反映匹配质量
- 空关键词跳过"
```

---

### Task 9: Layout/Table/Finance 修复

**涉及 bug:** M8, M9, M12, L8, L9, L14, L15
**文件:** `app/core/layout_extractor.py`, `app/core/table_extractor.py`, `app/core/finance_processor.py`

- [ ] **Step 1: 多边形坐标转 bbox（M8, L8, L14）**

```python
# layout_extractor.py:
elif all(isinstance(v, (int, float)) for v in coord):
    if len(coord) > 4:
        # 多边形坐标 [x1,y1,x2,y2,...] → bbox [x1,y1,x4,y4]
        xs = [coord[i] for i in range(0, len(coord), 2)]
        ys = [coord[i] for i in range(1, len(coord), 2)]
        bbox = [min(xs), min(ys), max(xs), max(ys)]
    else:
        bbox = list(coord)

# rec_score float() 转换异常保护:
try:
    confidence = float(rec_scores[i]) if i < len(rec_scores) else 0.0
except (TypeError, ValueError):
    confidence = 0.0
```

- [ ] **Step 2: 管道表列结构保护（M9, L15）**

```python
# table_extractor.py:
df = pd.read_csv(StringIO(cleaned), sep='|', engine='python')
# 仅删除首尾空列（管道表的产物），保持中间所有列
if df.shape[1] >= 2:
    df = df.iloc[:, 1:-1]
```

- [ ] **Step 3: FinanceProcessor 关键词保护（M12）**

```python
# finance_processor.py _find_neighbor:
# 使用词边界匹配:
import re
for b in blocks:
    if re.search(r'(?<!\w)' + re.escape(kw) + r'(?!\w)', b.content):
        anchor = b
        break
```

- [ ] **Step 4: 中位数计算用 statistics.median（L9）**

```python
# finance_processor.py:
import statistics
median_h = statistics.median(heights) if heights else 0
```

- [ ] **Step 5: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add app/core/layout_extractor.py app/core/table_extractor.py app/core/finance_processor.py
git commit -m "fix: Layout/Table/Finance 修复 (M8/M9/M12/L8/L9)

- 多边形坐标正确转 bbox
- float() 转换异常保护
- 管道表只删首尾空列
- Finance 关键词词边界匹配
- statistics.median 替代排序"
```

---

### Task 10: PDF Loader 修复

**涉及 bug:** M10, M11, L4, L5, L6
**文件:** `app/core/pdf_loader.py`

- [ ] **Step 1: 文件 I/O 移出锁外（M10）**

```python
# _get_document:
# 先查缓存（无锁快速判断）
with self._lock:
    if pdf_path in self._doc_cache:
        doc, _, size = self._doc_cache[pdf_path]
        self._doc_cache.move_to_end(pdf_path)
        return doc

# 锁外打开文件
doc = fitz.open(pdf_path)
size = self._estimate_doc_size(doc)

# 加锁后缓存
with self._lock:
    # 双重检查
    if pdf_path in self._doc_cache:
        doc.close()
        doc, _, size = self._doc_cache[pdf_path]
        self._doc_cache.move_to_end(pdf_path)
        return doc
    self._cache_evict_if_needed()
    self._doc_cache[pdf_path] = (doc, time.time(), size)
    return doc
```

- [ ] **Step 2: shutdown 资源泄漏修复（M11）**

```python
# shutdown:
def shutdown(self):
    self.clear_cache()
    self._async_executor.shutdown(wait=True)

# clear_cache 在 shutdown 后不重建 executor:
def clear_cache(self):
    with self._lock:
        for doc, _, _ in self._doc_cache.values():
            doc.close()
        self._doc_cache.clear()
    if not hasattr(self, '_shutdown') or not self._shutdown:
        self._async_executor.shutdown(wait=False)
        self._async_executor = ThreadPoolExecutor(max_workers=2)
```

- [ ] **Step 3: 页面大小估算改进（L4）**

```python
def _estimate_page_size(self, page) -> float:
    """估算单页渲染内存 (MB)"""
    rect = page.rect
    pixels = rect.width * rect.height * (self.dpi / 72) ** 2
    return pixels * 3 / (1024 * 1024)  # 3 bytes per pixel (RGB)
```

- [ ] **Step 4: 类型修复 + 时间更新（L5, L6）**

```python
# L5: from typing import Callable; 替换 callable → Callable
# L6: 缓存时更新 access_time
self._doc_cache[pdf_path] = (doc, time.time(), size)
```

- [ ] **Step 5: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add app/core/pdf_loader.py
git commit -m "fix: PDF Loader 修复 (M10/M11/L4/L5/L6)

- 文件 I/O 移出锁外，减少锁竞争
- shutdown 不再重建 executor
- 页面大小按实际像素估算
- 类型修正 + access_time 实时更新"
```

---

### Task 11: Utils 修复

**涉及 bug:** M21, M22, M24, L23, L24, L28
**文件:** `app/utils/lru_cache.py`, `app/utils/validators.py`, `app/utils/command_history.py`, `app/utils/image_utils.py`, `app/utils/config_loader.py`

- [ ] **Step 1: LRUCache TTL 过期条目清理（M21, M22）**

```python
# lru_cache.py contains():
def contains(self, key) -> bool:
    with self._lock:
        if key not in self._cache:
            return False
        if self._ttl is not None:
            access_time = self._timestamps.get(key, 0)
            if time.time() - access_time > self._ttl:
                self._remove_internal(key)
                return False
        return True

# keys/values/items/size 中加入 TTL 过滤：
def keys(self):
    with self._lock:
        self._evict_expired()
        return list(self._cache.keys())

def _evict_expired(self):
    if self._ttl is None:
        return
    now = time.time()
    expired = [k for k, t in self._timestamps.items() if now - t > self._ttl]
    for k in expired:
        self._remove_internal(k)
```

- [ ] **Step 2: 日期归一化保护（M24）**

```python
# validators.py:
# 先尝试原格式解析，再尝试归一化后解析
for fmt in DATE_FORMATS:
    try:
        return datetime.strptime(text, fmt)
    except ValueError:
        continue
# 归一化后再试
normalized = text.replace("年", "-").replace("月", "-").replace("日", "").replace("/", "-")
for fmt in DATE_FORMATS:
    try:
        return datetime.strptime(normalized, fmt)
    except ValueError:
        continue
```

- [ ] **Step 3: CommandHistory max_size 校验（L23）**

```python
# command_history.py __init__:
if max_size < 1:
    raise ValueError("max_size must be >= 1")
```

- [ ] **Step 4: image_utils 缓存 maxsize（L24）**

```python
@lru_cache(maxsize=128)
```

- [ ] **Step 5: config_loader 嵌套校验增强（L28）**

```python
# _validate_config 中:
if not isinstance(config.get("ocr", {}), dict):
    raise ValueError("config.ocr must be a dict")
if "paddleocr_vl" not in config.get("ocr", {}):
    config.setdefault("ocr", {}).setdefault("paddleocr_vl", {})
```

- [ ] **Step 6: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 7: Commit**

```bash
git add app/utils/lru_cache.py app/utils/validators.py app/utils/command_history.py \
       app/utils/image_utils.py app/utils/config_loader.py
git commit -m "fix: Utils 修复 (M21/M22/M24/L23/L24/L28)

- LRUCache TTL 过期条目主动清理
- 日期解析先试原格式再归一化
- CommandHistory max_size 校验
- image_utils 缓存 maxsize 提升
- config_loader 嵌套键校验"
```

---

### Task 12: 剩余零散修复

**涉及 bug:** M13, L10, L13, L17, L19, L20, L26, L27, L32, L33, L34
**文件:** 11 个文件，每项小改动

- [ ] **Step 1: Template 加载异常处理（M13）**

```python
# template_manager.py load():
def load(self, filepath: str) -> Optional[Template]:
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Template.from_dict(data)
    except (json.JSONDecodeError, TypeError, ValueError, KeyError) as e:
        logger.error(f"加载模板失败 {filepath}: {e}")
        return None
```

- [ ] **Step 2: Exporter 行构建去重（L10）**

```python
# exporter.py 新增 _build_rows:
def _build_rows(self, results: List[FileResult], include_confidence: bool = False) -> List[dict]:
    rows = []
    all_field_names = self._collect_field_names(results)
    for r in results:
        row = {"source_file": os.path.basename(r.source_file)}
        for fn in all_field_names:
            fr = r.fields.get(fn)
            row[fn] = fr.text if fr else ""
            if include_confidence:
                row[f"{fn}_conf"] = fr.confidence if fr else ""
        rows.append(row)
    return rows

# to_excel 和 to_csv 都调 _build_rows
```

- [ ] **Step 3: OCR引擎双检锁简化（L13）**

```python
# ocr_engine_rapid.py __init__:
# 移除外层 hasattr 检查（内层锁足够）
def __init__(self, lang="ch", use_gpu=False, use_angle_cls=True):
    with self.__class__._lock:
        if hasattr(self, "_initialized_flag"):
            return
        # ... 初始化 ...
        self._initialized_flag = True
```

- [ ] **Step 4: Region docstring 修复（L32）**

```python
# region.py:
@dataclass
class Region:
    """框选区域数据模型（坐标使用归一化 0~1 比例）"""
    id: str
    # ...
```

- [ ] **Step 5: config.yaml 缺失段补充（L26, L27）**

```yaml
# config.yaml 添加:
export:
  default_format: xlsx
  include_confidence: true
  include_source_file: true

finance:
  enabled: false
  invoice:
    keywords: ["发票号码", "开票日期", "价税合计"]
  validation:
    amount_tolerance: 0.01
    tax_rate: 0.13

layout_visualization:
  enabled: true
  colors:
    text: "#4A90D9"
    table: "#27AE60"
    formula: "#E67E22"
    chart: "#8E44AD"
    seal: "#E74C3C"
```

- [ ] **Step 6: result_table.py region_id 保留（L34）**

```python
# result_table.py 编辑结果时:
existing = row_data.get(original_name)
if existing:
    new_fr = FieldResult(
        field_name=existing.field_name,
        text=new_text,
        confidence=existing.confidence,
        region_id=existing.region_id,
        match_level=existing.match_level,
        engine=existing.engine,
    )
```

- [ ] **Step 7: 运行测试**

```bash
python -m pytest tests/ -v
```

- [ ] **Step 8: Commit**

```bash
git add app/core/template_manager.py app/core/exporter.py app/core/ocr_engine_rapid.py \
       app/models/region.py config.yaml app/ui/widgets/result_table.py
git commit -m "fix: 剩余零散修复 (M13/L10/L13/L26/L27/L32/L34)

- Template 加载异常处理返回 None
- Exporter 行构建逻辑去重
- OCR引擎双检锁简化
- Region docstring 恢复
- config.yaml 补全 finance/layout_visualization 段
- result_table 编辑保留 region_id"
```

---

## 验证

```bash
# 全部测试
python -m pytest tests/ -v
# 预期: 64 passed

# GUI 启动
python main.py
# 检查: GPU 状态、引擎切换、历史功能、批量取消均正常
```
