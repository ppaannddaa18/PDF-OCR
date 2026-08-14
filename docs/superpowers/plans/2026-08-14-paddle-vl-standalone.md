# PaddleOCR-VL 独立文档识别程序 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 在现有 PDFOCR 仓库内新增独立入口 `main_ocr.py`，构建专注 PDF/图片文档识别的桌面程序（参考 AI Studio PaddleOCR 文件任务页：文件列表 + 文档解析/JSON 双视图 + 解析配置弹窗 + 导出），并将 paddle_vl 从主程序启动选择中移除。

**Architecture:** 新程序复用 `PaddleOCRVLEngine`（扩展解析配置透传）、`PdfLoader`、`PdfCanvas`、`ThemeManager`、`AppBaseWindowMixin` 基建；新增 `OcrDocProcessor`（文档级编排/批量队列）、`OcrMainWindow`（单页布局：左文件列表 + 右工作区）、`OcrFilePanel`/`OcrResultViews`/`OcrParseConfigDialog`/`OcrExporter` 组件。主程序仅动 `engine_select_dialog.py`/`main.py`/`engine_checker.py`/两处 config.yaml。

**Tech Stack:** Python 3.10+（venv-paddle 环境）、PyQt6 + qfluentwidgets、PyMuPDF(fitz)、PaddleOCR-VL-1.6 官方管线（paddlex native）、pytest（offscreen UI 测试）

## Global Constraints

- 引擎默认行为不变：`use_doc_orientation_classify=False`、`use_doc_unwarping=False`、`use_layout_detection=False`（整页模式），主程序 keyword 路径无回归
- `repetition_penalty` 注入点从 initialize 移到 predict 前（热生效），默认 1.1
- `PageResult.raw_json` 字段已存在（`app/models/page_result.py:27`），只填充不新增字段
- 配置权威源：`app/config.yaml`（config_loader.py:16-27 实际加载），根 config.yaml 同步
- 新程序用 `venv-paddle` 环境（paddle/paddleocr 所在），主程序环境不变
- 测试运行：`./venv/Scripts/python.exe -m pytest tests -q`（主程序环境）
- 参照现有代码风格：dataclass + 显式类型注解 + 中文注释

---

### Task 1: 引擎解析配置读取与 predict 参数透传

**Files:**
- Modify: `app/core/ocr_engine_paddle_vl.py`（`__init__` L99-133、`_predict_once` L579-606、`initialize` L137-167 中 `_patch_repetition_penalty` 调用）
- Test: `tests/test_ocr_engine_paddle_vl.py`

**Interfaces:**
- Consumes: `self._config`（`config["ocr"]["paddle_vl"]`）
- Produces: 实例属性 `self._use_doc_orientation_classify` / `self._use_doc_unwarping` / `self._use_chart_recognition` / `self._use_seal_recognition` / `self._use_ocr_for_image_block` / `self._merge_layout_blocks` / `self._spotting_min_pixels`（Task 2 用）；`_predict_once` 用这些属性构造 predict kwargs

- [ ] **Step 1: 写失败测试**（在 `tests/test_ocr_engine_paddle_vl.py` 末尾追加）

```python
def test_predict_once_passes_parse_config_kwargs():
    """解析配置透传：方向/扭曲矫正等 kwargs 来自配置（不再硬编码 False）"""
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "use_doc_unwarping": True,
        "use_chart_recognition": False,
        "use_seal_recognition": False,
        "use_ocr_for_image_block": False,
        "merge_layout_blocks": False,
        "spotting_min_pixels": 256,
    }}})
    captured = {}
    with _install_fake_env():
        eng._pipe = _FakePipe(captured)
        eng._initialized = True
        eng._predict_once(_FAKE_IMG, "spotting", None)
    assert captured["use_doc_orientation_classify"] is True
    assert captured["use_doc_unwarping"] is True
    assert captured["use_chart_recognition"] is False
    assert captured["use_seal_recognition"] is False
    assert captured["use_ocr_for_image_block"] is False
    assert captured["merge_layout_blocks"] is False


def test_predict_once_injects_repetition_penalty_each_call():
    """重复抑制每次 predict 前注入 generation_config（热生效）"""
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {"repetition_penalty": 1.5}}})
    eng._pipe = _FakePipe({})
    eng._initialized = True
    eng._repetition_penalty = 1.5  # 模拟配置已改
    with _install_fake_env():
        eng._predict_once(_FAKE_IMG, "spotting", None)
    assert eng._pipe.generation_config.repetition_penalty == 1.5
```

（`_FakePipe` 需新增 `generation_config` 属性——见 Step 3；`_FAKE_IMG`/`_install_fake_env` 若文件已有则复用）

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py -q`
Expected: FAIL（predict kwargs 断言不满足 / generation_config 属性不存在）

- [ ] **Step 3: 实现**

`__init__` 中（`self._spotting_max_pixels` 之后）追加：

```python
# 解析配置透传（参考 AI Studio 解析配置弹窗；默认与现状一致，主程序无回归）
self._use_doc_orientation_classify = bool(cfg.get("use_doc_orientation_classify", 0))
self._use_doc_unwarping = bool(cfg.get("use_doc_unwarping", 0))
self._use_chart_recognition = bool(cfg.get("use_chart_recognition", 1))
self._use_seal_recognition = bool(cfg.get("use_seal_recognition", 1))
self._use_ocr_for_image_block = bool(cfg.get("use_ocr_for_image_block", 1))
self._merge_layout_blocks = bool(cfg.get("merge_layout_blocks", 1))
self._spotting_min_pixels = int(cfg.get("spotting_min_pixels", 0) or 0)
# 辅助内容过滤标签（markdown_ignore_labels，Task 2 使用）
self._markdown_ignore_labels = list(cfg.get("markdown_ignore_labels", []) or [])
```

`_predict_once` 的 kwargs 构造改为：

```python
kwargs: dict = {}
if max_new_tokens is not None:
    kwargs["max_new_tokens"] = max_new_tokens
kwargs.update({
    "use_doc_orientation_classify": self._use_doc_orientation_classify,
    "use_doc_unwarping": self._use_doc_unwarping,
    "use_chart_recognition": self._use_chart_recognition,
    "use_seal_recognition": self._use_seal_recognition,
    "use_ocr_for_image_block": self._use_ocr_for_image_block,
    "merge_layout_blocks": self._merge_layout_blocks,
})
results = self._pipe.predict(
    arr,
    use_layout_detection=bool(self._block_spotting),
    prompt_label=prompt_label,
    **kwargs,
)
```

`initialize` 中把 `self._patch_repetition_penalty(paddle)` 调用删除，`_predict_once` 开头（`paddle.disable_static()` 之后）注入：

```python
# 重复抑制热生效：每次 predict 前注入 generation_config（native 后端
# 忽略重复惩罚参数，需直接写 generation_config；0/None → 官方 greedy）
try:
    gen = self._pipe.infer.generation_config
    if getattr(gen, "repetition_penalty", None) != self._repetition_penalty:
        gen.repetition_penalty = self._repetition_penalty
except Exception:
    pass
```

测试文件中的 `_FakePipe` 增加 `generation_config`（简单对象）：

```python
class _FakeGenConfig:
    repetition_penalty = 1.1

class _FakePipe:
    def __init__(self, captured):
        self.captured = captured
        self.infer = type("FakeInfer", (), {"generation_config": _FakeGenConfig()})()
    def predict(self, arr, **kwargs):
        self.captured.update(kwargs)
        return [_FakeResult()]
```

`_patch_repetition_penalty` 方法本身可保留（不再调用）或删除——保留更安全（避免破坏其它引用），加注释"已改为 predict 前注入"。

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py -q`
Expected: 全部 PASS（含既有 23+ 测试）

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_engine_paddle_vl.py tests/test_ocr_engine_paddle_vl.py
git commit -m "feat: 引擎解析配置透传 + 重复抑制每次 predict 注入"
```

---

### Task 2: 辅助内容过滤（markdown_ignore_labels，逐块模式）

**Files:**
- Modify: `app/core/ocr_engine_paddle_vl.py`（`recognize_page_auto` L501-554 与 `_patch_spotting_max_pixels` 内的 collect patch 区域）
- Test: `tests/test_ocr_engine_paddle_vl.py`

**Interfaces:**
- Consumes: `self._markdown_ignore_labels: list[str]`（Task 1）
- Produces: 整页 spotting 模式的 markdown 行过滤；逐块模式的块过滤（同函数内完成）

**实现语义**（与 paddlex `markdown_ignore_labels` 一致）：整页 spotting 输出为无 label 的行级文本，辅助内容过滤在**逐块模式**（`use_layout_detection=True`）下过滤被忽略 label 的布局块；整页模式对 raw 结果过滤（parsing_res_list 的 block_label 命中忽略集则剔除，仅影响 markdown 与 JSON 视图，不影响 spotting 行）。

- [ ] **Step 1: 写失败测试**

```python
def test_markdown_ignore_labels_filters_parsing_blocks():
    """辅助内容过滤：block_label 命中 ignore 集的块从 markdown/raw 剔除"""
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {
        "markdown_ignore_labels": ["header", "footer"]}}})
    res = {
        "parsing_res_list": [
            _FakeBlock("header", "Hindawi Journal"),
            _FakeBlock("paragraph", "Body text here"),
            _FakeBlock("footer", "Copyright 2017"),
        ],
        "spotting_res": {"rec_texts": [], "rec_polys": []},
    }
    filtered = eng._filter_ignored_blocks(res)
    labels = [b.block_label for b in filtered["parsing_res_list"]]
    assert labels == ["paragraph"]


def test_ignore_labels_default_empty():
    eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {}}})
    assert eng._markdown_ignore_labels == []
```

（`_FakeBlock` 实现 `block_label`/`content` 属性；`_filter_ignored_blocks` 是新私有方法）

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py -q`
Expected: FAIL（`_filter_ignored_blocks` 不存在）

- [ ] **Step 3: 实现**

新增私有方法：

```python
def _filter_ignored_blocks(self, res: dict) -> dict:
    """辅助内容过滤：parsing_res_list 中 block_label 命中忽略集的块剔除
    （等价 paddlex markdown_ignore_labels 语义；整页 spotting 行不受影响）"""
    ignore = set(self._markdown_ignore_labels)
    if not ignore:
        return res
    res = dict(res)
    blocks = res.get("parsing_res_list") or []
    kept = [b for b in blocks
            if not (getattr(b, "block_label", None) in ignore)]
    res["parsing_res_list"] = kept
    return res
```

`recognize_page_auto` 中 `res = self._predict_one(...)` 之后插入 `res = self._filter_ignored_blocks(res)`（逐块与整页统一生效；整页 spotting 的 spotting_res 无 label 不受影响）。

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_engine_paddle_vl.py tests/test_ocr_engine_paddle_vl.py
git commit -m "feat: 辅助内容过滤（markdown_ignore_labels）"
```

---

### Task 3: PageResult.raw_json 填充（JSON 视图/导出数据源）

**Files:**
- Modify: `app/core/ocr_engine_paddle_vl.py`（`recognize_page_auto` 返回值 L546-554）
- Test: `tests/test_ocr_engine_paddle_vl.py`

**Interfaces:**
- Consumes: `res`（predict 返回的 dict 风格 Result）
- Produces: `PageResult.raw_json: dict` 填充为可 JSON 序列化的 prunedResult 结构

- [ ] **Step 1: 写失败测试**

```python
def test_recognize_page_auto_fills_raw_json():
    """raw_json 填充：包含 parsing_res_list 且可 JSON 序列化"""
    eng = PaddleOCRVLEngine({})
    with _install_fake_env():
        eng._pipe = _FakePipe({})
        eng._initialized = True
        eng._pipe.results = [{"parsing_res_list": [_FakeBlock("paragraph", "hi")],
                              "spotting_res": {"rec_texts": ["hi"], "rec_polys": [[[0, 0], [1, 0], [1, 1], [0, 1]]]}}]
        page = eng.recognize_page_auto(_FAKE_IMG)
    import json
    json.dumps(page.raw_json)  # 必须可序列化
    assert page.raw_json["spotting_res"]["rec_texts"] == ["hi"]
```

（`_FakePipe` 增加 `results` 属性；`_FakeBlock` 需可被 `_json_safe` 处理——见实现）

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py::test_recognize_page_auto_fills_raw_json -q`
Expected: FAIL（`raw_json` 为空 dict）

- [ ] **Step 3: 实现**

新增模块级函数（放在 `_blocks_to_elements` 附近）：

```python
def _json_safe(obj):
    """递归转 JSON 可序列化：numpy/paddle Tensor/DataFrame → 原生/字符串"""
    import numpy as np
    if isinstance(obj, dict):
        return {str(k): _json_safe(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_json_safe(v) for v in obj]
    if isinstance(obj, (str, int, float, bool)) or obj is None:
        return obj
    if isinstance(obj, np.ndarray):
        return obj.tolist()
    if hasattr(obj, "tolist"):
        try:
            return obj.tolist()
        except Exception:
            pass
    if hasattr(obj, "block_label"):  # paddlex Block
        return _json_safe({"block_label": obj.block_label,
                           "block_content": getattr(obj, "content", ""),
                           "block_bbox": getattr(obj, "bbox", [])})
    return str(obj)
```

`recognize_page_auto` 返回值改为：

```python
return PageResult(
    blocks=blocks,
    markdown=markdown,
    tables=[],
    raw_json=_json_safe(dict(res)) if isinstance(res, dict) else {},
    image_size=(W, H),
    inference_time_ms=elapsed,
    line_boxes=blocks,
)
```

（注意 `del res` 在返回值之前——保持现有清理顺序：先构造 raw_json 副本再 del）

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_engine_paddle_vl.py -q`
Expected: PASS（既有测试不受影响——raw_json 此前为空，无测试断言其内容）

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_engine_paddle_vl.py tests/test_ocr_engine_paddle_vl.py
git commit -m "feat: PageResult.raw_json 填充 paddlex 原始结果（JSON 可序列化）"
```

---

### Task 4: OcrDocProcessor — 文档级编排与批量队列

**Files:**
- Create: `app/core/ocr_doc_processor.py`
- Test: `tests/test_ocr_doc_processor.py`（新文件）

**Interfaces:**
- Consumes: `PdfLoader`（render_page/page_count）、`OCREngineBase.recognize_page_auto(image) -> PageResult`
- Produces:
  - `class OcrDocProcessor(QObject)`（PyQt6.QtCore，信号经 moveToThread 或直接 QThread 子类运行）
  - 信号：`file_started(int, int)`（file_idx, total）、`page_progress(str, int, int, float)`（path, page, total_pages, elapsed_ms）、`file_done(str, List[PageResult])`、`file_failed(str, str)`、`all_done()`、`cancelled()`
  - `add_files(paths: List[str]) -> None`、`start() -> None`、`cancel() -> None`、`is_running() -> bool`
  - 缓存：`get_cache(path) -> Optional[List[PageResult]]`、`clear_cache()`
  - 模块级 `is_image_file(path) -> bool`（后缀 .png/.jpg/.jpeg/.bmp/.tif/.tiff）

- [ ] **Step 1: 写失败测试**

```python
"""OcrDocProcessor 批量处理（fake 引擎，PyQt6 QThread 信号测试）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtCore import QCoreApplication, QEventLoop, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core.ocr_doc_processor import OcrDocProcessor, is_image_file
from app.models.page_result import PageResult


class _FakeEngine:
    def __init__(self, results):
        self.results = results  # path -> List[PageResult]
        self.calls = []

    def recognize_page_auto(self, image):
        self.calls.append(image.size)
        return self.results.pop(0)


@pytest.fixture
def qapp():
    return QCoreApplication.instance() or QCoreApplication([])


def _run_until_done(proc, timeout_ms=3000):
    loop = QEventLoop()
    done = []
    proc.all_done.connect(lambda: (done.append(1), loop.quit()))
    proc.file_failed.connect(lambda p, e: (done.append(("err", p, e)), loop.quit()))
    QTimer.singleShot(timeout_ms, loop.quit)
    proc.start()
    loop.exec()
    return done


def test_is_image_file():
    assert is_image_file("a.png") and is_image_file("b.JPG")
    assert not is_image_file("a.pdf")


def test_process_pdf_in_order(qapp, tmp_path):
    from app.core.pdf_loader import PdfLoader
    from PyQt6.QtGui import QImage, QPixmap  # noqa
    pdf = tmp_path / "doc.pdf"
    import fitz
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "Hello")
    doc.save(str(pdf))
    doc.close()

    engine = _FakeEngine([PageResult(blocks=[], markdown="p1"),
                          PageResult(blocks=[], markdown="p2")])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    results = {}
    proc.file_done.connect(lambda p, r: results.update({p: r}))
    proc.add_files([str(pdf)])
    _run_until_done(proc)
    assert len(results[str(pdf)]) == 2
    assert results[str(pdf)][0].markdown == "p1"
    loader.shutdown()


def test_cancel_stops_queue(qapp):
    engine = _FakeEngine([])
    loader = PdfLoader(dpi=100)
    proc = OcrDocProcessor(loader, engine, {})
    cancelled = []
    proc.cancelled.connect(lambda: cancelled.append(1))
    proc.add_files(["x.pdf"])
    proc.cancel()  # 未开始即取消
    assert proc.is_running() is False
    loader.shutdown()
```

（实现采用 `QThread` 子类 `_ProcessThread` 持有引擎调用；`OcrDocProcessor` 为门面对象管理队列与缓存）

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_doc_processor.py -q`
Expected: FAIL（ImportError: 模块不存在）

- [ ] **Step 3: 实现**

`app/core/ocr_doc_processor.py`：

```python
"""文档级 OCR 编排：PDF/图片 → 逐页渲染 → 引擎识别 → PageResult 列表
（新程序专用：顺序批量队列，GPU 单任务避免并发 OOM）"""
import os
import threading
from typing import List, Optional, Dict
from PIL import Image
from PyQt6.QtCore import QObject, QThread, pyqtSignal

from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine_base import OCREngineBase
from app.models.page_result import PageResult

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff"}


def is_image_file(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in _IMAGE_EXTS


class _ProcessThread(QThread):
    """后台处理线程：顺序执行文件队列，信号转发"""
    file_started = pyqtSignal(int, int)
    page_progress = pyqtSignal(str, int, int, float)
    file_done = pyqtSignal(str, list)
    file_failed = pyqtSignal(str, str)
    all_done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, loader, engine, queue, dpi, cancel_flag):
        super().__init__()
        self._loader = loader
        self._engine = engine
        self._queue = queue
        self._dpi = dpi
        self._cancel_flag = cancel_flag

    def run(self):
        total = len(self._queue)
        for idx, path in enumerate(self._queue):
            if self._cancel_flag.is_set():
                self.cancelled.emit()
                return
            self.file_started.emit(idx, total)
            try:
                pages = self._process_file(path)
                if self._cancel_flag.is_set():
                    self.cancelled.emit()
                    return
                self.file_done.emit(path, pages)
            except Exception as e:
                self.file_failed.emit(path, str(e))
        self.all_done.emit()

    def _process_file(self, path: str) -> List[PageResult]:
        if is_image_file(path):
            with Image.open(path) as im:
                page = self._engine.recognize_page_auto(im.convert("RGB"))
            return [page]
        count = self._loader.page_count(path)
        pages: List[PageResult] = []
        for i in range(count):
            if self._cancel_flag.is_set():
                return pages
            img = self._loader.render_page(path, i)  # dpi 为 PdfLoader 构造参数
            t0 = ...  # time.monotonic
            try:
                page = self._engine.recognize_page_auto(img)
            except Exception:
                # 单页失败不中断文件：构造失败占位（markdown 空）
                page = PageResult(blocks=[], markdown="", image_size=img.size)
                self.page_progress.emit(path, i + 1, count, 0.0)
                continue
            self.page_progress.emit(path, i + 1, count,
                                    (time.monotonic() - t0) * 1000)
            pages.append(page)
        return pages


class OcrDocProcessor(QObject):
    """文档识别编排门面：队列管理 + 线程生命周期 + 结果缓存"""
    file_started = pyqtSignal(int, int)
    page_progress = pyqtSignal(str, int, int, float)
    file_done = pyqtSignal(str, list)
    file_failed = pyqtSignal(str, str)
    all_done = pyqtSignal()
    cancelled = pyqtSignal()

    def __init__(self, loader: PdfLoader, engine: OCREngineBase, config: dict):
        super().__init__()
        self._loader = loader
        self._engine = engine
        self._dpi = int(config.get("pdf", {}).get("render_dpi", 200))
        self._queue: List[str] = []
        self._thread: Optional[_ProcessThread] = None
        self._cancel_flag = threading.Event()
        self._cache: Dict[str, List[PageResult]] = {}

    def add_files(self, paths: List[str]) -> None:
        self._queue.extend(p for p in paths if p not in self._queue)

    def get_cache(self, path: str) -> Optional[List[PageResult]]:
        return self._cache.get(path)

    def clear_cache(self) -> None:
        self._cache.clear()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.isRunning()

    def start(self) -> None:
        if self.is_running() or not self._queue:
            return
        self._cancel_flag.clear()
        self._thread = _ProcessThread(self._loader, self._engine,
                                      list(self._queue), self._dpi,
                                      self._cancel_flag)
        self._thread.file_started.connect(self.file_started)
        self._thread.page_progress.connect(self.page_progress)
        self._thread.file_done.connect(self._on_file_done)
        self._thread.file_failed.connect(self.file_failed)
        self._thread.all_done.connect(self._on_all_done)
        self._thread.cancelled.connect(self.cancelled)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_flag.set()

    def _on_file_done(self, path: str, pages: List[PageResult]) -> None:
        self._cache[path] = pages
        self.file_done.emit(path, pages)

    def _on_all_done(self) -> None:
        self._queue.clear()
        self._thread = None
        self.all_done.emit()
```

注意：`PdfLoader.render_page(pdf_path, page_num=0)` 的 dpi 是构造参数（`PdfLoader(dpi=...)`），调用不需传 dpi。

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_doc_processor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_doc_processor.py tests/test_ocr_doc_processor.py
git commit -m "feat: OcrDocProcessor 文档编排与顺序批量队列"
```

---

### Task 5: OcrFilePanel — 左侧文件列表组件

**Files:**
- Create: `app/ui/widgets/ocr_file_panel.py`
- Test: `tests/ui/widgets/test_ocr_file_panel.py`（新文件）

**Interfaces:**
- Consumes: 无（独立组件）
- Produces:
  - `class OcrFilePanel(QWidget)`：`add_file(path: str) -> str`（返回 file_id）、`set_status(file_id, status: str, detail: str = "")`（status ∈ {"queued","processing","done","failed","cancelled"}）、`remove_file(file_id)`、`clear()`、`paths() -> List[str]`、`selected_path() -> Optional[str]`
  - 信号：`file_selected(str)`（path）、`file_remove_requested(str)`（path）、`clear_requested()`

- [ ] **Step 1: 写失败测试**

```python
"""OcrFilePanel 组件测试（offscreen）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ui.widgets.ocr_file_panel import OcrFilePanel


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_add_and_select(qapp):
    panel = OcrFilePanel()
    fid = panel.add_file("C:/docs/a.pdf")
    selected = []
    panel.file_selected.connect(lambda p: selected.append(p))
    panel.select_file(fid)
    assert selected == ["C:/docs/a.pdf"]
    assert panel.paths() == ["C:/docs/a.pdf"]


def test_status_badge_text(qapp):
    panel = OcrFilePanel()
    fid = panel.add_file("C:/docs/a.pdf")
    panel.set_status(fid, "processing", "页 2/10")
    assert panel.status_text(fid) == "识别中 · 页 2/10"
    panel.set_status(fid, "done", "12.3s")
    assert panel.status_text(fid) == "完成 · 12.3s"
    panel.set_status(fid, "failed", "OOM")
    assert "失败" in panel.status_text(fid)


def test_remove_and_clear(qapp):
    panel = OcrFilePanel()
    a = panel.add_file("C:/a.pdf")
    panel.add_file("C:/b.pdf")
    removed = []
    panel.file_remove_requested.connect(lambda p: removed.append(p))
    panel.remove_file(a)
    assert "C:/a.pdf" not in panel.paths()
    panel.clear()
    assert panel.paths() == []
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_file_panel.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`app/ui/widgets/ocr_file_panel.py`：QListWidget 子类化或 QListWidget + 自定义 item widget。

```python
"""左侧文件列表：文件名 + 状态徽章 + 耗时 + 时间（参考 AI Studio 最近上传）"""
import os
import uuid
from datetime import datetime
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QListWidget,
                             QListWidgetItem, QLabel, QPushButton)
from app.ui.theme_manager import ThemeManager

_STATUS_TEXT = {
    "queued": "等待",
    "processing": "识别中",
    "done": "完成",
    "failed": "失败",
    "cancelled": "已取消",
}
_STATUS_COLOR = {
    "queued": "text_secondary",
    "processing": "primary",
    "done": "success",
    "failed": "danger",
    "cancelled": "text_secondary",
}


class OcrFilePanel(QWidget):
    file_selected = pyqtSignal(str)          # path
    file_remove_requested = pyqtSignal(str)  # path
    clear_requested = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._items = {}  # file_id -> (item, meta)
        self._status = {}  # file_id -> (status, detail)
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 8, 8, 8)
        head = QHBoxLayout()
        title = QLabel("解析队列")
        title.setStyleSheet(f"color: {ThemeManager.get_color('text_secondary')};"
                            f"font-size: 13px; font-weight: 600;")
        head.addWidget(title)
        head.addStretch(1)
        clear_btn = QPushButton("清空")
        clear_btn.setFixedHeight(24)
        clear_btn.clicked.connect(self.clear_requested)
        head.addWidget(clear_btn)
        layout.addLayout(head)
        self.list = QListWidget()
        self.list.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list, 1)

    def add_file(self, path: str) -> str:
        fid = uuid.uuid4().hex
        item = QListWidgetItem(os.path.basename(path))
        item.setData(Qt.ItemDataRole.UserRole, path)
        item.setToolTip(path)
        self.list.addItem(item)
        self._items[fid] = (item, {"path": path, "time": datetime.now()})
        self._status[fid] = ("queued", "")
        return fid

    def select_file(self, fid: str) -> None:
        item, _ = self._items[fid]
        self.list.setCurrentItem(item)
        self._on_item_clicked(item)

    def set_status(self, fid: str, status: str, detail: str = "") -> None:
        self._status[fid] = (status, detail)
        item, meta = self._items[fid]
        item.setText(f"{os.path.basename(meta['path'])}\n{self.status_text(fid)}")

    def status_text(self, fid: str) -> str:
        status, detail = self._status.get(fid, ("queued", ""))
        text = _STATUS_TEXT.get(status, status)
        return f"{text}" + (f" · {detail}" if detail else "")

    def remove_file(self, fid: str) -> None:
        item, meta = self._items.pop(fid)
        self._status.pop(fid, None)
        self.list.takeItem(self.list.row(item))
        self.file_remove_requested.emit(meta["path"])

    def clear(self) -> None:
        self.list.clear()
        self._items.clear()
        self._status.clear()

    def paths(self) -> List[str]:
        return [m["path"] for _, m in self._items.values()]

    def selected_path(self):
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _on_item_clicked(self, item):
        self.file_selected.emit(item.data(Qt.ItemDataRole.UserRole))
```

（`status_text` 按 `_STATUS_TEXT` 文案："等待/识别中/完成/失败/已取消"；测试断言"识别中 · 页 2/10"等）

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_file_panel.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets/ocr_file_panel.py tests/ui/widgets/test_ocr_file_panel.py
git commit -m "feat: OcrFilePanel 文件列表组件"
```

---

### Task 6: OcrResultViews — 文档解析视图 + JSON 树视图

**Files:**
- Create: `app/ui/widgets/ocr_result_views.py`
- Test: `tests/ui/widgets/test_ocr_result_views.py`（新文件）

**Interfaces:**
- Consumes: `PdfCanvas`（load_image/highlight_bbox/clear_highlights/fit_to_width/set_drawing_enabled）、`PageResult`（blocks/markdown/raw_json/image_size）
- Produces:
  - `class OcrDocView(QWidget)`：`show_page(result: PageResult, image: Image.Image, show_boxes: bool)`、`set_boxes_visible(bool)`；信号 `boxes_toggled(bool)`
  - `class OcrJsonView(QTreeWidget)`：`show_result(raw_json: dict)`（递归构建可折叠树）

- [ ] **Step 1: 写失败测试**

```python
"""OcrResultViews 组件测试（offscreen）"""
import sys
from pathlib import Path
import pytest
from PIL import Image
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.models.page_result import PageResult, Block
from app.ui.widgets.ocr_result_views import OcrDocView, OcrJsonView


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def _page():
    return PageResult(
        blocks=[Block("text", "Hello", [0, 0, 10, 10]),
                Block("table", "| a | b |", [0, 0, 10, 10])],
        markdown="# Title\n\nHello\n\n| a | b |",
        raw_json={"parsing_res_list": [{"block_label": "paragraph",
                                        "block_content": "Hello"}]},
        image_size=(100, 100))


def test_doc_view_renders_text(qapp):
    view = OcrDocView()
    view.show_page(_page(), Image.new("RGB", (100, 100)), show_boxes=True)
    assert "Title" in view.text()
    assert "Hello" in view.text()


def test_json_view_tree(qapp):
    view = OcrJsonView()
    view.show_result({"parsing_res_list": [
        {"block_label": "paragraph", "block_content": "Hello"}]})
    # 树中应包含键与值文本
    all_text = "\n".join(view.topLevelItem(i).text(0)
                         for i in range(view.topLevelItemCount()))
    assert "parsing_res_list" in all_text
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_result_views.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`app/ui/widgets/ocr_result_views.py`：

```python
"""结果视图：文档解析（左图右文 + 检测框高亮）与 JSON 树"""
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QSplitter, QVBoxLayout, QHBoxLayout,
                             QTextBrowser, QTreeWidget, QTreeWidgetItem,
                             QCheckBox, QLabel)
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.theme_manager import ThemeManager


class OcrDocView(QWidget):
    """文档解析视图：PDF 页渲染 + 结构化文本 + 检测框高亮开关"""
    boxes_toggled = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._show_boxes = True
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.canvas = PdfCanvas()
        self.canvas.set_drawing_enabled(False)  # 只读浏览
        self.text_browser = QTextBrowser()
        self.text_browser.setStyleSheet("font-size: 14px;")
        self.splitter.addWidget(self.canvas)
        self.splitter.addWidget(self.text_browser)
        self.splitter.setSizes([480, 480])
        layout.addWidget(self.splitter, 1)
        toolbar = QHBoxLayout()
        self.boxes_check = QCheckBox("显示检测框")
        self.boxes_check.setChecked(True)
        self.boxes_check.toggled.connect(self._on_boxes_toggled)
        toolbar.addWidget(self.boxes_check)
        toolbar.addStretch(1)
        layout.addLayout(toolbar)

    def _on_boxes_toggled(self, on):
        self._show_boxes = on
        self.boxes_toggled.emit(on)
        if not on:
            self.canvas.clear_highlights()

    def show_page(self, result, image, show_boxes: bool = True):
        """渲染一页：原图 + 结构化文本 + 检测框"""
        self.canvas.load_image(image)
        self._show_boxes = show_boxes
        self.text_browser.setHtml(self._blocks_to_html(result))
        if show_boxes and result.blocks:
            self.canvas.clear_highlights()
            for b in result.blocks:
                if b.bbox and len(b.bbox) == 4:
                    self.canvas.highlight_bbox(b.bbox)

    def text(self) -> str:
        return self.text_browser.toPlainText()

    @staticmethod
    def _blocks_to_html(result: PageResult) -> str:
        """blocks → HTML：text 段落、table 等宽、行内 <br>"""
        parts = []
        for b in result.blocks:
            content = str(b.content).replace("\n", "<br>")
            if b.block_type == "table":
                parts.append(f"<pre>{content}</pre>")
            else:
                parts.append(f"<p>{content}</p>")
        return "<html><body style='font-family:sans-serif'>" \
               + "".join(parts) + "</body></html>"


class OcrJsonView(QTreeWidget):
    """JSON 树视图：递归构建可折叠树（基于 PageResult.raw_json）"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setHeaderLabel("原始解析结果（JSON）")
        self.setColumnCount(2)
        self.setHeaderLabels(["键 / 值", "类型"])

    def show_result(self, raw_json: dict):
        self.clear()
        if not raw_json:
            return
        root = QTreeWidgetItem(["root", "object"])
        self.addTopLevelItem(root)
        self._fill(root, raw_json)
        root.setExpanded(True)

    def _fill(self, parent: QTreeWidgetItem, obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                item = QTreeWidgetItem([str(k), "object" if isinstance(v, (dict, list)) else type(v).__name__])
                parent.addChild(item)
                self._fill(item, v)
        elif isinstance(obj, (list, tuple)):
            for i, v in enumerate(obj):
                item = QTreeWidgetItem([f"[{i}]", "object" if isinstance(v, (dict, list)) else type(v).__name__])
                parent.addChild(item)
                self._fill(item, v)
        else:
            parent.setText(0, str(obj))
            parent.setText(1, type(obj).__name__)
```

（`PdfCanvas.set_drawing_enabled` 为现有方法 L484；`highlight_bbox` 现有方法 L880）

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_result_views.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets/ocr_result_views.py tests/ui/widgets/test_ocr_result_views.py
git commit -m "feat: 文档解析视图 + JSON 树视图"
```

---

### Task 7: OcrParseConfigDialog — 解析配置弹窗

**Files:**
- Create: `app/ui/widgets/ocr_parse_config_dialog.py`
- Test: `tests/ui/widgets/test_ocr_parse_config_dialog.py`（新文件）

**Interfaces:**
- Consumes: `config["ocr"]["paddle_vl"]`（现有 + Task 1 新键）
- Produces:
  - `class OcrParseConfigDialog(QDialog)`：`get_config_patch() -> dict`（只含改动键，格式 `{"ocr": {"paddle_vl": {...}}}`）、`static defaults() -> dict`、信号 `apply_requested(dict)`

字段清单（与参考页面解析配置弹窗一致）：
- 辅助内容（勾选=恢复解析，反选=过滤）：页眉/页眉图片/页脚/页脚图片/页码/脚注/旁注文本 → `markdown_ignore_labels`（未勾选标签集合）
- 模型参数：图片方向矫正 `use_doc_orientation_classify`、图片扭曲矫正 `use_doc_unwarping`、版面分析 `use_layout_detection`（=block_spotting）、图表识别 `use_chart_recognition`、印章识别 `use_seal_recognition`、图片文字识别 `use_ocr_for_image_block`、跨页表格合并 `merge_layout_blocks`
- 文本检测与识别：重复抑制强度 `repetition_penalty`（QDoubleSpinBox 0-2 步长 0.1）、图像最小总像素数 `spotting_min_pixels`、图像最大总像素数 `spotting_max_pixels`（QSpinBox）

- [ ] **Step 1: 写失败测试**

```python
"""OcrParseConfigDialog 测试（offscreen）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ui.widgets.ocr_parse_config_dialog import OcrParseConfigDialog


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_defaults_patch(qapp):
    dlg = OcrParseConfigDialog({})
    patch = dlg.get_config_patch()
    pv = patch["ocr"]["paddle_vl"]
    # 默认：方向/扭曲/版面分析关，图表/印章/图片文字/跨页合并开
    assert pv["use_doc_orientation_classify"] is False
    assert pv["use_doc_unwarping"] is False
    assert pv["use_layout_detection"] is False
    assert pv["use_chart_recognition"] is True
    assert pv["use_seal_recognition"] is True
    assert pv["use_ocr_for_image_block"] is True
    assert pv["merge_layout_blocks"] is True
    assert pv["repetition_penalty"] == 1.1
    assert pv["spotting_max_pixels"] == 1048576


def test_roundtrip(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "repetition_penalty": 1.3,
        "markdown_ignore_labels": ["header"],
    }}})
    patch = dlg.get_config_patch()
    assert patch["ocr"]["paddle_vl"]["use_doc_orientation_classify"] is True
    assert patch["ocr"]["paddle_vl"]["repetition_penalty"] == 1.3


def test_reset_restores_defaults(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    dlg.reset_to_defaults()
    patch = dlg.get_config_patch()
    assert patch["ocr"]["paddle_vl"]["use_doc_orientation_classify"] is False
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_parse_config_dialog.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`app/ui/widgets/ocr_parse_config_dialog.py`：QDialog + 分组（qfluentwidgets `SwitchButton` 或 QCheckBox 二选一——项目已有 SwitchButton 用法可参考 gguf_settings_page.py），字段读写 helper。

```python
"""解析配置弹窗（参考 AI Studio 解析配置：辅助内容过滤 + 模型参数 + 采样参数）"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QGroupBox,
                             QFormLayout, QCheckBox, QDoubleSpinBox, QSpinBox,
                             QPushButton, QLabel)
from app.ui.theme_manager import ThemeManager

# 辅助内容标签 → (显示名, 默认恢复解析?)
_AUX_ITEMS = [
    ("header", "页眉", False),
    ("header_image", "页眉图片", False),
    ("footer", "页脚", False),
    ("footer_image", "页脚图片", False),
    ("page number", "页码", True),
    ("footnote", "脚注", False),
    ("aside_text", "旁注文本", False),
]


class OcrParseConfigDialog(QDialog):
    """解析配置弹窗：应用 → apply_requested(patch)；重置 → 恢复默认"""

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解析配置")
        self.setMinimumWidth(520)
        pv = config.get("ocr", {}).get("paddle_vl", {})
        self._build_ui(pv)

    # —— 构建 ——
    def _build_ui(self, pv: dict):
        # 辅助内容过滤组：check = 恢复解析（不忽略）
        ignore = set(pv.get("markdown_ignore_labels", []))
        self._aux_checks = {}
        aux_group = QGroupBox("辅助内容解析")
        form = QFormLayout(aux_group)
        for label, name, default in _AUX_ITEMS:
            chk = QCheckBox(name)
            chk.setChecked(label not in ignore)
            self._aux_checks[label] = chk
            form.addRow(chk)
        # 模型参数组（开关）
        self._model_switches = {}
        model_group = QGroupBox("模型参数设置")
        mform = QFormLayout(model_group)
        for key, name, default in [
            ("use_doc_orientation_classify", "图片方向矫正", False),
            ("use_doc_unwarping", "图片扭曲矫正", False),
            ("use_layout_detection", "版面分析", False),
            ("use_chart_recognition", "图表识别", True),
            ("use_seal_recognition", "印章识别", True),
            ("use_ocr_for_image_block", "图片文字识别", True),
            ("merge_layout_blocks", "跨页表格合并", True),
        ]:
            chk = QCheckBox(name)
            chk.setChecked(bool(pv.get(key, default)))
            self._model_switches[key] = chk
            mform.addRow(chk)
        # 采样参数组
        self._rep_spin = QDoubleSpinBox()
        self._rep_spin.setRange(0.0, 2.0)
        self._rep_spin.setSingleStep(0.1)
        self._rep_spin.setValue(float(pv.get("repetition_penalty", 1.1) or 0))
        self._min_px = QSpinBox()
        self._min_px.setRange(0, 100_000_000)
        self._min_px.setValue(int(pv.get("spotting_min_pixels", 0) or 0))
        self._max_px = QSpinBox()
        self._max_px.setRange(0, 100_000_000)
        self._max_px.setValue(int(pv.get("spotting_max_pixels", 1048576) or 1048576))
        sample_group = QGroupBox("文本检测与识别")
        sform = QFormLayout(sample_group)
        sform.addRow("重复抑制强度", self._rep_spin)
        sform.addRow("图像最小总像素数", self._min_px)
        sform.addRow("图像最大总像素数", self._max_px)
        # 按钮
        apply_btn = QPushButton("应用")
        reset_btn = QPushButton("重置")
        apply_btn.clicked.connect(self._on_apply)
        reset_btn.clicked.connect(self.reset_to_defaults)
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(apply_btn)
        # 组装
        layout = QVBoxLayout(self)
        layout.addWidget(aux_group)
        layout.addWidget(model_group)
        layout.addWidget(sample_group)
        layout.addLayout(btn_row)

    # —— 读取 ——
    def get_config_patch(self) -> dict:
        """收集当前表单值 → 只含改动键的完整 paddle_vl 补丁"""
        pv = {}
        ignore = [label for label, _, _ in _AUX_ITEMS
                  if not self._aux_checks[label].isChecked()]
        pv["markdown_ignore_labels"] = ignore
        for key, chk in self._model_switches.items():
            pv[key] = chk.isChecked()
        pv["repetition_penalty"] = self._rep_spin.value()
        pv["spotting_min_pixels"] = self._min_px.value()
        pv["spotting_max_pixels"] = self._max_px.value()
        return {"ocr": {"paddle_vl": pv}}

    def reset_to_defaults(self):
        for label, _, default in _AUX_ITEMS:
            self._aux_checks[label].setChecked(default)
        for key, default in [
            ("use_doc_orientation_classify", False),
            ("use_doc_unwarping", False),
            ("use_layout_detection", False),
            ("use_chart_recognition", True),
            ("use_seal_recognition", True),
            ("use_ocr_for_image_block", True),
            ("merge_layout_blocks", True),
        ]:
            self._model_switches[key].setChecked(default)
        self._rep_spin.setValue(1.1)
        self._min_px.setValue(0)
        self._max_px.setValue(1048576)

    def _on_apply(self):
        self.apply_requested.emit(self.get_config_patch())
        self.accept()
```

注意：`apply_requested` 需要定义为类属性信号 `apply_requested = pyqtSignal(dict)`（PyQt6.QtCore）。

（默认忽略集 = 未勾选恢复的标签：header/header_image/footer/footer_image/footnote/aside_text；页码默认勾选恢复。`use_layout_detection` 与现有 `block_spotting` 键并存：`get_config_patch` 同时输出 `use_layout_detection`，引擎 Task 1 读取前者——若引擎仍读 `block_spotting`，则 patch 同时写两个键：`pv["block_spotting"] = pv["use_layout_detection"]`）

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/widgets/test_ocr_parse_config_dialog.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/widgets/ocr_parse_config_dialog.py tests/ui/widgets/test_ocr_parse_config_dialog.py
git commit -m "feat: 解析配置弹窗（辅助内容/模型参数/采样参数）"
```

---

### Task 8: OcrExporter — 结果导出

**Files:**
- Create: `app/core/ocr_exporter.py`
- Test: `tests/test_ocr_exporter.py`（新文件）

**Interfaces:**
- Consumes: `List[PageResult]`（按文件）
- Produces:
  - `export_txt(pages: List[PageResult], out_dir: str, base_name: str) -> List[str]`（返回写出的文件路径列表）
  - `export_markdown(pages, out_dir, base_name) -> List[str]`
  - `export_json(pages, out_dir, base_name) -> List[str]`
  - 命名：`{base_name}_p{页码}.txt|md|json`；整文件合并 `{base_name}.txt|md|json`（TXT/MD 合并，JSON 按页）

- [ ] **Step 1: 写失败测试**

```python
"""OcrExporter 导出测试"""
import json
from pathlib import Path
import pytest
from app.core.ocr_exporter import (export_txt, export_markdown, export_json)
from app.models.page_result import PageResult, Block


def _pages():
    return [
        PageResult(blocks=[Block("text", "Hello", [0, 0, 1, 1])],
                   markdown="# Title\n\nHello", raw_json={"k": "v"},
                   image_size=(100, 100)),
        PageResult(blocks=[], markdown="Second", raw_json={"k2": 2}),
    ]


def test_export_txt(tmp_path):
    files = export_txt(_pages(), str(tmp_path), "doc")
    assert len(files) == 2
    assert (tmp_path / "doc_p1.txt").read_text(encoding="utf-8") == "Hello"
    assert (tmp_path / "doc_p2.txt").read_text(encoding="utf-8") == "Second"


def test_export_markdown_merged(tmp_path):
    files = export_markdown(_pages(), str(tmp_path), "doc")
    text = (tmp_path / "doc.md").read_text(encoding="utf-8")
    assert "# Title" in text and "Second" in text


def test_export_json(tmp_path):
    files = export_json(_pages(), str(tmp_path), "doc")
    data = json.loads((tmp_path / "doc_p1.json").read_text(encoding="utf-8"))
    assert data["k"] == "v"
    data2 = json.loads((tmp_path / "doc_p2.json").read_text(encoding="utf-8"))
    assert data2["k2"] == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_exporter.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`app/core/ocr_exporter.py`：

```python
"""OCR 结果导出：TXT / Markdown / JSON（含块坐标结构）"""
import json
import re
from pathlib import Path
from typing import List
from app.models.page_result import PageResult


def _page_text(result: PageResult) -> str:
    """markdown 去标记 → 纯文本"""
    text = result.markdown or ""
    text = re.sub(r"[#>*`~-]", "", text)
    return text.strip()


def export_txt(pages: List[PageResult], out_dir: str, base_name: str) -> List[str]:
    written = []
    for i, page in enumerate(pages, start=1):
        path = Path(out_dir) / f"{base_name}_p{i}.txt"
        path.write_text(_page_text(page), encoding="utf-8")
        written.append(str(path))
    return written


def export_markdown(pages: List[PageResult], out_dir: str,
                    base_name: str) -> List[str]:
    parts = [f"<!-- {base_name} -->"]
    for i, page in enumerate(pages, start=1):
        parts.append(f"\n## 第 {i} 页\n\n{page.markdown or ''}")
    path = Path(out_dir) / f"{base_name}.md"
    path.write_text("\n".join(parts), encoding="utf-8")
    return [str(path)]


def export_json(pages: List[PageResult], out_dir: str,
                base_name: str) -> List[str]:
    written = []
    for i, page in enumerate(pages, start=1):
        path = Path(out_dir) / f"{base_name}_p{i}.json"
        path.write_text(json.dumps(page.raw_json, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        written.append(str(path))
    return written
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/test_ocr_exporter.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/core/ocr_exporter.py tests/test_ocr_exporter.py
git commit -m "feat: OcrExporter 导出 TXT/Markdown/JSON"
```

---

### Task 9: OcrMainWindow + main_ocr.py 入口

**Files:**
- Create: `app/ui/windows/ocr_main_window.py`、`main_ocr.py`（根目录）
- Test: `tests/ui/test_ocr_main_window.py`（新文件）

**Interfaces:**
- Consumes: Task 4-8 全部组件、`AppBaseWindowMixin`（`_init_app_base` pre-super / `_post_init_base` post-super）、`PaddleOCRVLEngine`（经 `get_ocr_engine`）、`PdfLoader`
- Produces:
  - `class OcrMainWindow(AppBaseWindowMixin, FluentWindow)`：覆写 `DESIGN='paddle_vl'`、`ACCENT_COLOR`（沿用现有 `#1E7B5C`）、`FLUENT_THEME=Theme.LIGHT`、`WINDOW_TITLE`
  - 构造：`_init_app_base(config)` → `super().__init__()` → `_post_init_base()`
  - 方法：`add_files(paths)`、`_on_file_selected(path)`、`_on_config_apply(patch)`、`_on_export()`、`_on_copy()`、`_on_retry()`；`_register_sub_interfaces` 覆写为注册单一"文档解析"子界面
  - 历史：轻量持久化 `~/.pdf_ocr_tool/ocr_doc_history.json`（文件路径+时间列表，读/写/恢复）

- [ ] **Step 1: 写失败测试**

```python
"""OcrMainWindow 测试（offscreen，fake 引擎）"""
import sys
from pathlib import Path
import pytest
from PyQt6.QtWidgets import QApplication

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from app.ui.windows.ocr_main_window import OcrMainWindow
from app.models.page_result import PageResult


class _FakeEngine:
    def __init__(self):
        self.results = [PageResult(blocks=[], markdown="Page1"),
                        PageResult(blocks=[], markdown="Page2")]

    def recognize_page_auto(self, image):
        return self.results.pop(0)

    def initialize(self):
        pass

    @property
    def is_ready(self):
        return True

    @property
    def engine_name(self):
        return "paddle_vl"

    @property
    def init_error(self):
        return ""


@pytest.fixture
def qapp():
    return QApplication.instance() or QApplication([])


def test_window_constructs(qapp, tmp_path, monkeypatch):
    import app.ui.windows.ocr_main_window as mod
    monkeypatch.setattr(mod, "get_ocr_engine", lambda cfg: _FakeEngine())
    win = OcrMainWindow({"app": {"name": "OCR 识别", "window_size": [1200, 800]},
                         "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                         "pdf": {"render_dpi": 100}})
    win.show()
    assert win.windowTitle() == "OCR 识别"


def test_add_file_and_parse(qapp, tmp_path, monkeypatch):
    import fitz
    import app.ui.windows.ocr_main_window as mod
    monkeypatch.setattr(mod, "get_ocr_engine", lambda cfg: _FakeEngine())
    pdf = tmp_path / "doc.pdf"
    doc = fitz.open()
    pg = doc.new_page()
    pg.insert_text((72, 72), "Hello")
    doc.save(str(pdf))
    doc.close()
    win = OcrMainWindow({"app": {"name": "OCR", "window_size": [1200, 800]},
                         "ocr": {"engine": "paddle_vl", "paddle_vl": {}},
                         "pdf": {"render_dpi": 100}})
    win.add_files([str(pdf)])
    # 等待处理完成（QEventLoop + all_done）
    from PyQt6.QtCore import QEventLoop, QTimer
    loop = QEventLoop()
    win.processor.all_done.connect(loop.quit)
    QTimer.singleShot(5000, loop.quit)
    loop.exec()
    assert win.processor.get_cache(str(pdf)) is not None
    assert len(win.processor.get_cache(str(pdf))) == 2
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_ocr_main_window.py -q`
Expected: FAIL（ImportError）

- [ ] **Step 3: 实现**

`app/ui/windows/ocr_main_window.py`（结构骨架，UI 细节可自由组织）：

```python
"""PaddleOCR-VL 独立识别主窗口（参考 AI Studio 文件任务页形态）"""
import json
import os
import logging
from datetime import datetime
from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QSpinBox, QFileDialog, QSplitter,
                             QFrame)
from qfluentwidgets import (FluentWindow, InfoBar, InfoBarPosition,
                            setTheme, Theme, PushButton, BodyLabel)

from app.ui.windows.base_window import AppBaseWindowMixin, _icon
from app.ui.theme_manager import ThemeManager
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import get_ocr_engine
from app.core.ocr_doc_processor import OcrDocProcessor, is_image_file
from app.core.ocr_exporter import export_txt, export_markdown, export_json
from app.ui.widgets.ocr_file_panel import OcrFilePanel
from app.ui.widgets.ocr_result_views import OcrDocView, OcrJsonView
from app.ui.widgets.ocr_parse_config_dialog import OcrParseConfigDialog

logger = logging.getLogger("PDFOCR")

_HISTORY_FILE = "ocr_doc_history.json"


class OcrMainWindow(AppBaseWindowMixin, FluentWindow):
    """文档识别主窗口：左文件列表 + 右工作区（源文件面板/双视图/工具按钮）"""

    WINDOW_TITLE = "PaddleOCR 文档识别"
    DESIGN = 'paddle_vl'
    ACCENT_COLOR = '#1E7B5C'
    FLUENT_THEME = Theme.LIGHT

    def __init__(self, config):
        self._init_app_base(config)   # 必须在 super().__init__() 之前
        super().__init__()
        self._post_init_base()

    # ── 页面构建覆写 ──────────────────────────────
    def _register_sub_interfaces(self):
        """单页面布局：左侧文件面板 + 右侧工作区"""
        self.workspace_page.setObjectName('workspace')
        self.addSubInterface(self.workspace_page, _icon('fa5s.file'), '文档解析')
        self.switchTo(self.workspace_page)

    def _create_workspace_page(self) -> QWidget:
        """工作区：文件面板 + 源文件面板 + 视图区"""
        page = QWidget()
        root = QHBoxLayout(page)
        root.setContentsMargins(8, 8, 8, 8)

        # 左侧文件面板
        self.file_panel = OcrFilePanel()
        self.file_panel.setFixedWidth(240)
        self.file_panel.file_selected.connect(self._on_file_selected)
        self.file_panel.clear_requested.connect(self._on_files_cleared)
        root.addWidget(self.file_panel)

        # 右侧：源文件面板 + 视图
        right = QVBoxLayout()
        right.setContentsMargins(8, 0, 0, 0)
        right.addWidget(self._create_source_bar())
        right.addWidget(self._create_view_area(), 1)
        root.addLayout(right, 1)
        return page

    def _create_source_bar(self) -> QWidget:
        """源文件面板：文件名/大小/页码导航/加文件 + 视图切换 + 工具按钮"""
        bar = QFrame()
        bar.setStyleSheet(f"background: {ThemeManager.get_color('card')};"
                          f"border-radius: 8px;")
        layout = QHBoxLayout(bar)
        self.file_label = BodyLabel("未选择文件")
        layout.addWidget(self.file_label, 1)
        # 页码导航
        self.page_spin = QSpinBox()
        self.page_spin.setRange(1, 1)
        self.page_spin.setFixedWidth(70)
        self.total_label = BodyLabel("/ 1")
        prev_btn = PushButton("◀")
        next_btn = PushButton("▶")
        prev_btn.clicked.connect(lambda: self.page_spin.setValue(
            self.page_spin.value() - 1))
        next_btn.clicked.connect(lambda: self.page_spin.setValue(
            self.page_spin.value() + 1))
        self.page_spin.valueChanged.connect(self._on_page_changed)
        layout.addWidget(prev_btn)
        layout.addWidget(self.page_spin)
        layout.addWidget(self.total_label)
        layout.addWidget(next_btn)
        layout.addSpacing(8)
        # 视图切换（文档解析 / JSON）
        self.view_doc_btn = PushButton("文档解析")
        self.view_json_btn = PushButton("JSON")
        self.view_doc_btn.setCheckable(True)
        self.view_json_btn.setCheckable(True)
        self.view_doc_btn.setChecked(True)
        self.view_doc_btn.clicked.connect(lambda: self._switch_view("doc"))
        self.view_json_btn.clicked.connect(lambda: self._switch_view("json"))
        layout.addWidget(self.view_doc_btn)
        layout.addWidget(self.view_json_btn)
        layout.addSpacing(8)
        # 工具按钮：配置 / 重新解析 / 复制 / 导出 / 添加文件
        for text, slot in [("≡ 配置", self._open_config_dialog),
                           ("↻", self._on_retry),
                           ("⧉", self._on_copy),
                           ("⇩", self._on_export)]:
            btn = PushButton(text)
            btn.clicked.connect(slot)
            layout.addWidget(btn)
        add_btn = PushButton("+ 加文件")
        add_btn.clicked.connect(self._on_add_files)
        layout.addWidget(add_btn)
        return bar

    def _create_view_area(self) -> QWidget:
        wrap = QWidget()
        layout = QVBoxLayout(wrap)
        layout.setContentsMargins(0, 8, 0, 0)
        self.doc_view = OcrDocView()
        self.json_view = OcrJsonView()
        self.json_view.setVisible(False)
        layout.addWidget(self.doc_view, 1)
        layout.addWidget(self.json_view, 1)
        return wrap

    # ── 文件与处理 ──────────────────────────────
    def add_files(self, paths):
        for p in paths:
            self.file_panel.add_file(p)
            self._add_history(p)
        self.processor.add_files(paths)
        self.processor.start()

    def _on_add_files(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self, "选择文件", "",
            "文档/图片 (*.pdf *.png *.jpg *.jpeg *.bmp *.tif *.tiff)")
        if paths:
            self.add_files(paths)

    def _on_file_selected(self, path):
        pages = self.processor.get_cache(path)
        if pages:
            self._show_file(path, pages)
        else:
            # 未缓存 → 自动入队解析
            self.file_label.setText(os.path.basename(path))
            if not self.processor.is_running():
                self.processor.add_files([path])
                self.processor.start()

    def _on_files_cleared(self):
        self.processor.cancel()
        self.file_panel.clear()

    # ── 视图 ────────────────────────────────────
    def _switch_view(self, name):
        self.view_doc_btn.setChecked(name == "doc")
        self.view_json_btn.setChecked(name == "json")
        self.doc_view.setVisible(name == "doc")
        self.json_view.setVisible(name == "json")

    def _on_page_changed(self, page_no):
        # 当前文件缓存页 → 重新渲染
        path = self.file_panel.selected_path()
        if not path:
            return
        pages = self.processor.get_cache(path)
        if pages and 1 <= page_no <= len(pages):
            self._render_page(path, pages[page_no - 1], page_no)

    def _show_file(self, path, pages):
        self.file_label.setText(f"{os.path.basename(path)}"
                                f" · {len(pages)} 页")
        self.total_label.setText(f"/ {len(pages)}")
        self.page_spin.setRange(1, len(pages))
        self.page_spin.setValue(1)
        self._render_page(path, pages[0], 1)

    def _render_page(self, path, page_result, page_no):
        """渲染一页：PDF 渲染/图片 + 视图更新"""
        if is_image_file(path):
            from PIL import Image
            image = Image.open(path).convert("RGB")
        else:
            image = self.pdf_loader.render_page(path, page_no - 1)
        self.doc_view.show_page(page_result, image)
        self.json_view.show_result(page_result.raw_json)

    # ── 工具按钮 ────────────────────────────────
    def _open_config_dialog(self):
        dlg = OcrParseConfigDialog(self.config, self)
        dlg.apply_requested.connect(self._on_config_apply)
        dlg.exec()

    def _on_config_apply(self, patch):
        """保存配置 + 热生效（引擎 predict 参数即时读取；无需重启管线）"""
        self._merge_config_patch(patch)
        from app.utils.config_loader import save_config
        try:
            save_config(self.config)
        except Exception as e:
            logger.warning(f"配置保存失败: {e}")
        InfoBar.success(title="配置已应用", content="解析参数已更新",
                        parent=self, duration=2000)

    def _on_retry(self):
        path = self.file_panel.selected_path()
        if not path:
            return
        self.processor.cancel()
        self.processor.add_files([path])
        self.processor.start()

    def _on_copy(self):
        text = self.doc_view.text()
        if text:
            from PyQt6.QtWidgets import QApplication
            QApplication.clipboard().setText(text)
            InfoBar.success(title="已复制", content="当前页文本已复制到剪贴板",
                            parent=self, duration=2000)

    def _on_export(self):
        path = self.file_panel.selected_path()
        pages = self.processor.get_cache(path) if path else None
        if not pages:
            InfoBar.error(title="无可导出内容", content="请先解析文件",
                          parent=self, duration=2000)
            return
        out_dir = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if not out_dir:
            return
        base = os.path.splitext(os.path.basename(path))[0]
        files = export_txt(pages, out_dir, base)
        files += export_markdown(pages, out_dir, base)
        files += export_json(pages, out_dir, base)
        InfoBar.success(title="导出完成", content=f"{len(files)} 个文件",
                        parent=self, duration=3000)

    # ── 历史（轻量：路径+时间列表） ──────────────
    def _history_path(self):
        return os.path.join(os.path.expanduser("~/.pdf_ocr_tool"),
                            _HISTORY_FILE)

    def _add_history(self, path):
        try:
            data = self._load_history()
            data = [p for p in data if p["path"] != path]
            data.insert(0, {"path": path,
                            "time": datetime.now().isoformat(timespec="seconds")})
            with open(self._history_path(), "w", encoding="utf-8") as f:
                json.dump(data[:50], f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.warning(f"历史写入失败: {e}")

    def _load_history(self):
        try:
            with open(self._history_path(), encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []

    def _restore_history(self):
        for entry in self._load_history():
            if os.path.exists(entry["path"]):
                self.file_panel.add_file(entry["path"])

    # ── 引擎/处理接线（post-init） ───────────────
    def _create_processor(self):
        self.processor = OcrDocProcessor(self.pdf_loader, self.ocr_engine,
                                         self.config)
        self.processor.file_started.connect(
            lambda idx, total: self.statusBar().showMessage(
                f"解析中 {idx + 1}/{total}"))
        self.processor.page_progress.connect(
            lambda path, page, total, ms: self.statusBar().showMessage(
                f"{os.path.basename(path)} 第 {page}/{total} 页 "
                f"({ms / 1000:.1f}s)"))
        self.processor.file_done.connect(self._on_processor_file_done)
        self.processor.file_failed.connect(
            lambda path, err: InfoBar.error(
                title="解析失败", content=f"{os.path.basename(path)}: {err}",
                parent=self, duration=3000))
        self.processor.all_done.connect(
            lambda: self.statusBar().showMessage("解析完成"))

    def _on_processor_file_done(self, path, pages):
        fid = next((f for f in self.file_panel._items
                    if self.file_panel._items[f][1]["path"] == path), None)
        if fid:
            total = sum(1 for p in pages if p.markdown or p.blocks)
            self.file_panel.set_status(fid, "done",
                                       f"{len(pages)} 页 · 成功 {total}")
        if self.file_panel.selected_path() == path:
            self._show_file(path, pages)
```

接线说明（关键：在 `_post_init_base` 之后追加 `_create_processor()` 与 `_restore_history()`；`_post_init_base` 默认调用 `_start_ocr_init`（后台 initialize）与 `QTimer.singleShot(500, self._check_pending_task)`——后者在 OcrMainWindow 中覆写为空或忽略（不适用于本窗口）：

```python
    def _post_init_base(self):
        super()._post_init_base()
        self._create_processor()
        self._restore_history()

    def _check_pending_task(self):
        pass  # 文档识别程序无待恢复任务
```

（`_merge_config_patch` 为 AppBaseWindowMixin 现有方法 L613；`statusBar()` 为 FluentWindow 现有状态栏；`save_config` 需确认 config_loader.py 是否暴露——若无则省略保存或写回 yaml 用 config_loader 内部函数）

`main_ocr.py`（根目录）：

```python
"""PaddleOCR-VL 独立文档识别程序入口（venv-paddle 环境运行）"""
import sys


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtCore import Qt
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)

    from app.utils.logger import setup_logger
    from app.utils.config_loader import load_config
    setup_logger()
    config = load_config()
    config.setdefault("ocr", {})["engine"] = "paddle_vl"  # 固定引擎

    from app.ui.windows.ocr_main_window import OcrMainWindow
    window = OcrMainWindow(config)
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_ocr_main_window.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/windows/ocr_main_window.py main_ocr.py tests/ui/test_ocr_main_window.py
git commit -m "feat: OcrMainWindow 文档识别主窗口 + main_ocr.py 入口"
```

---

### Task 10: 主程序改动 — 移除 paddle_vl 卡片

**Files:**
- Modify: `app/ui/engine_select_dialog.py`（`_CARD_SPECS`）、`main.py`（`_normalize_engine`/`choose_engine`/分派）、`app/utils/engine_checker.py`（`check_engine_availability`）、`app/config.yaml` + 根 `config.yaml`
- Test: `tests/ui/test_engine_select_dialog.py`、`tests/test_engine_checker.py`

- [ ] **Step 1: 写失败测试**（更新既有测试）

`tests/ui/test_engine_select_dialog.py` 追加：

```python
def test_cards_only_gguf_rapid(qapp):
    """paddle_vl 卡片已移除，只剩 gguf/rapid"""
    dialog = EngineSelectDialog({"ocr": {"gguf": {}, "rapidocr": {}}})
    keys = [card.engine_key for card in dialog._cards]
    assert keys == ["gguf", "rapid"]
```

`tests/test_engine_checker.py` 追加：

```python
def test_availability_no_paddle_vl():
    from app.utils.engine_checker import check_engine_availability
    result = check_engine_availability({"ocr": {"gguf": {}, "paddle_vl": {}}})
    assert "paddle_vl" not in result
    assert set(result.keys()) == {"gguf", "rapidocr"}
```

- [ ] **Step 2: 运行确认失败**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_engine_select_dialog.py tests/test_engine_checker.py -q`
Expected: FAIL（`_cards` 属性不存在或 paddle_vl 仍在返回中——先检查现有测试的实际断言方式并适配）

- [ ] **Step 3: 实现**

1. `engine_select_dialog.py`：`_CARD_SPECS` 删除 `"paddle_vl"` 条目（保留 `"gguf"`/`"rapid"`）。`_EngineCard` 与 `EngineSelectDialog` 代码不动（基于字典通用渲染）。
2. `main.py`：
   - `_normalize_engine` 注释更新（只接受 'gguf'|'rapid'）
   - `choose_engine`：`if env_engine in ("gguf", "rapidocr"):`（删除 "paddle_vl"）
   - 分派：`if engine == "gguf":` → GgufMainWindow；else → RapidMainWindow（删除 `("gguf", "paddle_vl")` 分支）
3. `engine_checker.py`：`check_engine_availability` 返回 dict 删除 `"paddle_vl"` 键（保留 `_check_paddle_vl` 函数供新程序测试引用）
4. 两处 config.yaml：
   - `ocr.engine` 默认值 `paddle_vl` → `rapidocr`
   - `ocr.paddle_vl` 段追加 Task 1 新键（与引擎默认值一致）：

```yaml
  paddle_vl:
    max_new_tokens: 4096
    repetition_penalty: 1.1
    vision_sdpa: 1
    spotting_max_pixels: 1048576
    block_spotting: false
    use_doc_orientation_classify: false
    use_doc_unwarping: false
    use_chart_recognition: true
    use_seal_recognition: true
    use_ocr_for_image_block: true
    merge_layout_blocks: true
    spotting_min_pixels: 0
    markdown_ignore_labels: ["header", "header_image", "footer", "footer_image", "footnote", "aside_text"]
```

- [ ] **Step 4: 运行确认通过**

Run: `./venv/Scripts/python.exe -m pytest tests/ui/test_engine_select_dialog.py tests/test_engine_checker.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/ui/engine_select_dialog.py main.py app/utils/engine_checker.py app/config.yaml config.yaml tests/ui/test_engine_select_dialog.py tests/test_engine_checker.py
git commit -m "refactor: 主程序移除 paddle_vl 卡片与分派（独立识别程序接管）"
```

---

### Task 11: 启动脚本与打包配置

**Files:**
- Create: `run_ocr.bat`、`PDF-OCR-VL.spec`
- Modify: `README.md`（新程序使用说明段）

- [ ] **Step 1: 写文件**

`run_ocr.bat`：

```bat
@echo off
REM PaddleOCR-VL 独立文档识别程序（venv-paddle 环境）
cd /d %~dp0
venv-paddle\Scripts\python.exe main_ocr.py
```

`PDF-OCR-VL.spec`：参照 `PDF-OCR.spec` 结构（复制后改入口为 `main_ocr.py`、name 为 `PDF-OCR-VL`；paddle/paddlex 数据文件在 venv-paddle 中，`pathex` 指向 `venv-paddle\Lib\site-packages`）。spec 仅作参考，第一版以脚本运行验证为主。

`README.md` 追加段落：新程序用途、启动方式（`run_ocr.bat`）、与主程序的关系（paddle_vl 引擎归独立程序）。

- [ ] **Step 2: 语法验证**

Run: `./venv-paddle/Scripts/python.exe -m py_compile main_ocr.py app/ui/windows/ocr_main_window.py app/core/ocr_doc_processor.py app/core/ocr_exporter.py app/ui/widgets/ocr_result_views.py app/ui/widgets/ocr_parse_config_dialog.py`
Expected: 无输出（编译通过）

- [ ] **Step 3: Commit**

```bash
git add run_ocr.bat PDF-OCR-VL.spec README.md
git commit -m "docs: run_ocr.bat / PDF-OCR-VL.spec / README 新程序说明"
```

---

### Task 12: 全量回归与端到端验证

**Files:**
- 无新增

- [ ] **Step 1: 全量 pytest 回归（主程序环境）**

Run: `./venv/Scripts/python.exe -m pytest tests -q`
Expected: 全部 PASS（既有 615+ + 新增 ~30+）

- [ ] **Step 2: 主程序冒烟（无 paddle_vl 卡片）**

Run: `./venv/Scripts/python.exe -c "from app.ui.engine_select_dialog import EngineSelectDialog; from app.utils.engine_checker import check_engine_availability; d = check_engine_availability({'ocr': {'gguf': {}, 'rapidocr': {}}}); print(d)"`
Expected: `{'gguf': ..., 'rapidocr': ...}`（无 paddle_vl）

- [ ] **Step 3: 新程序端到端（真实引擎，用户执行）**

Run: `venv-paddle\Scripts\python.exe main_ocr.py`
验证清单（用户在 GUI 中执行）：
1. 添加一份 PDF（≤10 页）→ 列表徽章从"等待"→"识别中"→"完成"（每页 ~40s）
2. 文档解析视图：左图右文 + 检测框高亮开关
3. 切换 JSON 视图：折叠树含 parsing_res_list/block_bbox
4. ≡ 配置：修改重复抑制强度 → 应用 → 新页解析生效（无需重启）
5. ⇩ 导出：TXT/Markdown/JSON 三份文件生成，JSON 可被 json.loads 解析
6. 添加图片（PNG/JPG）→ 单页识别正常
7. 关闭程序时有任务 → 确认弹窗

- [ ] **Step 4: Commit（如有验证中发现的小修）**

```bash
git add -A
git commit -m "fix: 端到端验证修复"
```

---

## Self-Review 记录

**Spec 覆盖核对：**
- 上传+文件列表+批量 → Task 4/5/9 ✓
- 解析配置弹窗 → Task 7（+Task 1 引擎侧）✓
- 文档解析+JSON 双视图 → Task 6 ✓
- 结果导出 → Task 8 ✓
- 主程序移除卡片/分派/config → Task 10 ✓
- run_ocr.bat/spec/README → Task 11 ✓
- 测试计划 → Task 1-10 内嵌 TDD + Task 12 回归 ✓
- PageResult.raw_json（既有字段）→ Task 3 ✓（修正：不新增字段，填充既有字段）
- 历史记录 → Task 9 `_add_history`/`_load_history`/`_restore_history`（轻量 JSON，不依赖发票版 HistoryManager）✓

**风险备注：**
- `_patch_repetition_penalty` 删除调用前确认无其它引用（保留方法体 + 注释）
- PdfLoader.render_page 签名以实际代码为准（Task 4 备注）
- `save_config` 是否存在需在 Task 9 实现时确认（config_loader.py），不存在则仅内存合并
- EngineSelectDialog 既有测试的断言方式需在 Task 10 Step 2 实测后适配
