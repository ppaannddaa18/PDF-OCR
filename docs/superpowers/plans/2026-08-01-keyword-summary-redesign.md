# 关键字批量汇总主题化重设计 实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PDF OCR Tool 重设计为"关键字驱动的批量单据关键信息汇总"工具：上传批量发票/报表 → 输入关键字 → GGUF 逐页提取 → 分组折叠汇总树（命中率徽标）→ 内嵌核对（PDF 文本层高亮）→ 手动修正 → 导出 Excel。

**Architecture:** 主题化重组（方案 B）：保留引擎层（GGUF/RapidOCR）、PdfLoader、模板框选模式、批量链路、历史记录；新增独立的关键字汇总子系统（模型/提取器/批量处理器/worker/导出/定位器 + 汇总页 UI）；删除无关组件（导航图/单页视图/双向高亮）。核心均为纯 Python 可无头单测，UI 为薄层。

**Tech Stack:** PyQt6 + qfluentwidgets、PyMuPDF (fitz)、pandas+openpyxl、pytest。测试命令 `venv/Scripts/python.exe -m pytest tests/`。

## Global Constraints

- 所有颜色/字体/间距来自 `ThemeManager`（app/ui/theme_manager.py），禁止硬编码颜色
- 关键字提取**仅 GGUF 路径**（用户决策）；模板框选走 RapidOCR，不受影响
- 高亮坐标**只来自 PDF 文本层**（fitz），绝不来自 VLM
- 工作树脏（git submodule），每次提交只 `git add <本次任务明确路径>`，**严禁 add -A**
- 提交信息结尾带 `Co-Authored-By: Claude <noreply@anthropic.com>`
- UI 组件测试复用 `tests/ui/conftest.py` 的 `qapp`/`reset_theme` fixture
- 复用的现有函数（勿重新实现）：`structured_extractor._SEP/_anchor_pattern/_extract_value`（app/core/structured_extractor.py:28-33, :222-244）、`PdfLoader.render_page/pdf_count`（app/core/pdf_loader.py:166, :225）、`BatchWorker` 模式（app/workers/batch_worker.py:5-48）、`FinanceProcessor.validate_field`（app/core/finance_processor.py:56-65）、`PdfCanvas.load_image/highlight_bbox/clear_highlights`（app/ui/widgets/pdf_canvas.py:520/:880/:902）
- 执行方式：inline（executing-plans），用户此前偏好主会话直接实现

---

### Task 1: 关键字结果模型层

**Files:**
- Create: `app/models/keyword_result.py`
- Test: `tests/test_keyword_result.py`

**Interfaces:**
- Produces: `KeywordCell(keyword, value, status, source, line_text, confidence, manually_edited)`；`PageKeywordResult(page_no, cells: Dict[str, KeywordCell], success, error_msg)`；`FileKeywordResult(source_file, pages: List[PageKeywordResult], success, error_msg)` — 后续所有任务消费这三个模型

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_result.py
from app.models.keyword_result import KeywordCell, PageKeywordResult, FileKeywordResult


def test_cell_defaults():
    c = KeywordCell(keyword="报关单号")
    assert c.value == ""
    assert c.status == "not_found"
    assert c.source == "none"
    assert c.manually_edited is False


def test_page_result_shape():
    pg = PageKeywordResult(page_no=1, cells={"报关单号": KeywordCell(keyword="报关单号")})
    assert pg.success is True
    assert pg.error_msg == ""


def test_file_result_shape():
    fr = FileKeywordResult(source_file="a.pdf")
    assert fr.pages == []
    assert fr.success is True


def test_status_source_enum():
    c = KeywordCell(keyword="价税合计", value="100", status="pending", source="loose")
    assert c.status in ("confirmed", "pending", "not_found")
    assert c.source in ("exact", "loose", "none")
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_result.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现模型**

```python
# app/models/keyword_result.py
"""关键字提取结果模型 — 引擎无关"""
from dataclasses import dataclass, field
from typing import Dict, List


@dataclass
class KeywordCell:
    """单个关键字在本页的提取结果"""
    keyword: str
    value: str = ""
    status: str = "not_found"      # 'confirmed' | 'pending' | 'not_found'
    source: str = "none"           # 'exact' | 'loose' | 'none'
    line_text: str = ""            # 命中行原文（tooltip 供人工核对）
    confidence: float = 1.0
    manually_edited: bool = False  # 人工修正标记（导出/历史用）


@dataclass
class PageKeywordResult:
    """单页提取结果"""
    page_no: int                              # 1-based
    cells: Dict[str, KeywordCell] = field(default_factory=dict)
    success: bool = True
    error_msg: str = ""


@dataclass
class FileKeywordResult:
    """单文件全部页的提取结果"""
    source_file: str
    pages: List[PageKeywordResult] = field(default_factory=list)
    success: bool = True
    error_msg: str = ""
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_result.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
git add app/models/keyword_result.py tests/test_keyword_result.py
git commit -m "feat: 关键字提取结果模型 KeywordCell/PageKeywordResult/FileKeywordResult

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 2: 关键字提取核心（两级匹配）

**Files:**
- Create: `app/core/keyword_extractor.py`
- Test: `tests/test_keyword_extractor.py`

**Interfaces:**
- Consumes: `structured_extractor._SEP/_anchor_pattern/_extract_value`（模块级函数）、`KeywordCell`
- Produces: `normalize_keyword(keyword: str) -> str`；`KeywordExtractor(keywords: List[str], loose=True, max_next_lines=1)`，`extract(text: str, lines: Optional[List[str]] = None) -> Dict[str, KeywordCell]` — Task 4/5/9 消费

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_extractor.py
import pytest

from app.core.keyword_extractor import KeywordExtractor, normalize_keyword


class TestNormalize:
    def test_strip_and_trailing_colon(self):
        assert normalize_keyword(" 价税合计： ") == "价税合计"

    def test_trailing_parenthesis(self):
        assert normalize_keyword("境内收货人（") == "境内收货人"


class TestExactMatch:
    def test_blob_with_colon(self):
        ex = KeywordExtractor(["报关单号"])
        cells = ex.extract("报关单号：090820241000039736 预录入编号：123")
        assert cells["报关单号"].value == "090820241000039736"
        assert cells["报关单号"].status == "confirmed"
        assert cells["报关单号"].source == "exact"

    def test_fullwidth_colon(self):
        ex = KeywordExtractor(["发票号码"])
        cells = ex.extract("发票号码：12345678")
        assert cells["发票号码"].value == "12345678"

    def test_no_separator(self):
        """_SEP 容忍无分隔符：'价税合计100.00' 直接精确命中"""
        ex = KeywordExtractor(["价税合计"])
        cells = ex.extract("价税合计100.00")
        assert cells["价税合计"].value == "100.00"

    def test_value_stops_at_next_anchor(self):
        ex = KeywordExtractor(["报关单号", "申报日期"])
        cells = ex.extract("报关单号 090820241000039736 申报日期 2026-01-01")
        assert cells["报关单号"].value == "090820241000039736"
        assert cells["申报日期"].value == "2026-01-01"

    def test_trailing_punct_cleaned(self):
        ex = KeywordExtractor(["毛重"])
        cells = ex.extract("毛重：1500.00千克。")
        assert cells["毛重"].value == "1500.00千克"

    def test_keyword_with_parenthesis_value(self):
        ex = KeywordExtractor(["境内收货人"])
        cells = ex.extract("境内收货人(91210213959942233Y) 电话：123")
        assert cells["境内收货人"].value == "91210213959942233Y"


class TestLooseMatch:
    def test_loose_cross_line_join(self):
        """精确取到行尾为空 → 宽松 L2 拼接下一行"""
        ex = KeywordExtractor(["价税合计"], loose=True, max_next_lines=1)
        cells = ex.extract("价税合计\n¥1,234.56")
        assert cells["价税合计"].value == "¥1,234.56"
        assert cells["价税合计"].status == "pending"
        assert cells["价税合计"].source == "loose"

    def test_loose_respects_max_next_lines(self):
        ex = KeywordExtractor(["价税合计"], loose=True, max_next_lines=1)
        cells = ex.extract("价税合计\n中间行\n¥1,234.56")
        assert cells["价税合计"].status == "not_found"  # 值在 2 行后超范围

    def test_loose_pure_chinese_line_rejected(self):
        """无数字且全汉字的行不可信（防抓正文）"""
        ex = KeywordExtractor(["备注"])
        cells = ex.extract("备注\n附件一：合同副本")
        assert cells["备注"].status == "not_found"

    def test_loose_blob_fallback(self):
        """单行 blob：宽松退化为止于下一锚点"""
        ex = KeywordExtractor(["价税合计", "备注"])
        cells = ex.extract("价税合计¥1,234.56备注：无")
        assert cells["价税合计"].value == "¥1,234.56"
        assert cells["价税合计"].status == "pending"


class TestStatusMatrix:
    def test_not_found_empty_value(self):
        ex = KeywordExtractor(["不存在的字段"])
        cells = ex.extract("报关单号：123")
        c = cells["不存在的字段"]
        assert c.status == "not_found"
        assert c.value == ""
        assert c.source == "none"

    def test_empty_text_all_not_found(self):
        ex = KeywordExtractor(["a", "b"])
        cells = ex.extract("")
        assert all(c.status == "not_found" for c in cells.values())

    def test_regex_special_chars_safe(self):
        ex = KeywordExtractor(["金额(元)", "$total"])
        cells = ex.extract("金额(元)：100 $total：200")
        assert cells["金额(元)"].value == "100"
        assert cells["$total"].value == "200"

    def test_empty_keyword_skipped(self):
        ex = KeywordExtractor(["", "   "])
        assert ex.keywords == []
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_extractor.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现提取器**

```python
# app/core/keyword_extractor.py
"""关键字提取器 — 两级匹配（精确锚点 → 宽松兜底），纯 Python 可无头单测

精确 pass 复用 structured_extractor 的锚点取值核心（_SEP/_anchor_pattern/
_extract_value，模块级函数 import 复用）；宽松 pass 在精确未命中时启用：
L1 同行剩余 → L2 下一行拼接 → L3 blob 兜底（止于下一锚点）。宽松命中
一律 status=pending 供人工核对（source='loose'）。
"""
import re
from typing import Dict, List, Optional, Pattern, Tuple

from app.models.keyword_result import KeywordCell
from app.core.structured_extractor import _SEP, _anchor_pattern, _extract_value


def normalize_keyword(keyword: str) -> str:
    """关键字归一化：strip + 去尾部冒号/括号（'价税合计：' 与 '价税合计' 等价）"""
    return keyword.strip().rstrip("：:（( ")


class KeywordExtractor:
    """两级匹配提取器：输入全页文本（GGUF markdown），输出每关键字一个 KeywordCell"""

    def __init__(self, keywords: List[str], loose: bool = True, max_next_lines: int = 1):
        self.keywords = [normalize_keyword(k) for k in keywords if normalize_keyword(k)]
        self.loose = loose
        self.max_next_lines = max(1, max_next_lines)
        # 精确锚点：(compiled regex, keyword)，有序
        self._anchors: List[Tuple[Pattern, str]] = [
            (re.compile(_anchor_pattern(kw)), kw) for kw in self.keywords
        ]

    def extract(self, text: str, lines: Optional[List[str]] = None) -> Dict[str, KeywordCell]:
        """两级匹配提取，返回 keyword -> KeywordCell

        Args:
            text: 全页文本（GGUF markdown，可能为无换行 blob）
            lines: 可选行级文本（宽松跨行拼接用；缺省从 text 按换行切分）
        """
        text = text or ""
        line_list = lines if lines is not None else [ln for ln in text.split("\n")]
        exact = self._exact_pass(text)
        loose = self._loose_pass(line_list, text) if self.loose else {}
        cells: Dict[str, KeywordCell] = {}
        for kw in self.keywords:
            if kw in exact:
                cells[kw] = KeywordCell(keyword=kw, value=exact[kw],
                                        status="confirmed", source="exact")
            elif kw in loose:
                cells[kw] = KeywordCell(keyword=kw, value=loose[kw],
                                        status="pending", source="loose",
                                        line_text=self._hit_line(kw, line_list))
            else:
                cells[kw] = KeywordCell(keyword=kw, value="",
                                        status="not_found", source="none")
        return cells

    # ---------- 精确 pass（复用结构化提取取值核心） ----------

    def _exact_pass(self, text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for pat, kw in self._anchors:
            m = pat.search(text)
            if not m:
                continue
            value = _extract_value(text, m.end(), self._anchors)
            if value:
                result[kw] = value
        return result

    # ---------- 宽松 pass ----------

    def _loose_pass(self, lines: List[str], text: str) -> Dict[str, str]:
        result: Dict[str, str] = {}
        for kw in self.keywords:
            value = self._loose_one(kw, lines, text)
            if value:
                result[kw] = value
        return result

    def _loose_one(self, kw: str, lines: List[str], text: str) -> str:
        """L1 同行剩余 → L2 下一行拼接 → L3 blob 兜底"""
        for i, line in enumerate(lines):
            pos = line.find(kw)
            if pos == -1:
                continue
            rest = line[pos + len(kw):].lstrip("：:（( ")
            if self._plausible(rest):
                return self._clean(rest)
            # L2：同行剩余为空/不可信 → 拼接后 1..max_next_lines 行
            joined = rest
            for j in range(1, self.max_next_lines + 1):
                if i + j >= len(lines):
                    break
                joined += lines[i + j].strip()
                if self._plausible(joined):
                    return self._clean(joined)
            break
        # L3：单行 blob 退化 → 复用 _extract_value（止于下一锚点/闭括号/标点）
        if len(lines) <= 1 and kw in text:
            pos = text.find(kw) + len(kw)
            value = _extract_value(text, pos, self._anchors)
            if value:
                return value
        return ""

    @staticmethod
    def _plausible(value: str) -> bool:
        """宽松命中可信度：含数字 → 可信；无数字需含非汉字字符（防抓正文行）"""
        if not value:
            return False
        if any(ch.isdigit() for ch in value):
            return True
        return len(value) >= 2 and any(not ('一' <= ch <= '鿿') for ch in value)

    @staticmethod
    def _clean(value: str) -> str:
        return value.strip().strip("。．，,、；;：:）)")

    def _hit_line(self, kw: str, lines: List[str]) -> str:
        for line in lines:
            if kw in line:
                return line.strip()
        return ""
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_extractor.py -v`
Expected: PASS（全部通过；同时跑 `venv/Scripts/python.exe -m pytest tests/test_structured_extractor.py -v` 确认 import 复用无副作用）

- [ ] **Step 5: 提交**

```bash
git add app/core/keyword_extractor.py tests/test_keyword_extractor.py
git commit -m "feat: 关键字两级匹配提取器（精确锚点复用+宽松L1/L2/L3兜底）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 3: 关键字集管理

**Files:**
- Create: `app/utils/keyword_set_manager.py`
- Test: `tests/test_keyword_set_manager.py`

**Interfaces:**
- Produces: `KeywordSetManager(storage_dir=None)`，方法 `list_sets() -> List[str]` / `load(name) -> Optional[List[str]]` / `save(name, keywords)` / `delete(name) -> bool` — Task 8/9 消费

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_set_manager.py
import json
import pytest

from app.utils.keyword_set_manager import KeywordSetManager


@pytest.fixture
def mgr(tmp_path):
    return KeywordSetManager(storage_dir=str(tmp_path))


def test_save_load_roundtrip(mgr):
    mgr.save("发票集", ["发票号码", "价税合计", "开票日期"])
    assert mgr.load("发票集") == ["发票号码", "价税合计", "开票日期"]


def test_list_sets_sorted(mgr):
    mgr.save("b集", ["x"])
    mgr.save("a集", ["y"])
    assert mgr.list_sets() == ["a集", "b集"]


def test_load_missing_returns_none(mgr):
    assert mgr.load("不存在") is None


def test_delete(mgr):
    mgr.save("集", ["a"])
    assert mgr.delete("集") is True
    assert mgr.load("集") is None
    assert mgr.delete("集") is False


def test_overwrite_same_name(mgr):
    mgr.save("集", ["a"])
    mgr.save("集", ["b", "c"])
    assert mgr.load("集") == ["b", "c"]


def test_corrupted_file_backed_up(mgr, tmp_path):
    store = tmp_path / "keyword_sets.json"
    store.write_text("{not json", encoding="utf-8")
    assert mgr.list_sets() == []
    assert (tmp_path / "keyword_sets.json.bak").exists()


def test_chinese_names_and_keywords(mgr):
    mgr.save("报关单集", ["报关单号", "境内收货人"])
    assert mgr.load("报关单集") == ["报关单号", "境内收货人"]
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_set_manager.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现管理器（镜像 HistoryManager 原子写/损坏备份模式）**

```python
# app/utils/keyword_set_manager.py
"""命名关键字集管理 — JSON 持久化（镜像 HistoryManager 模式）

存储：~/.pdf_ocr_tool/keyword_sets.json（storage_dir 可注入供测试）
结构：{"集合名": ["关键字", ...], ...}；原子写（tmp + os.replace），
损坏时备份 .bak 后返回空。
"""
import json
import logging
import os
import shutil
import threading


class KeywordSetManager:
    STORE_FILE = "keyword_sets.json"

    def __init__(self, storage_dir: str = None):
        if storage_dir is None:
            storage_dir = os.path.expanduser("~/.pdf_ocr_tool")
        self.storage_dir = storage_dir
        self.store_file = os.path.join(storage_dir, self.STORE_FILE)
        self._lock = threading.RLock()
        os.makedirs(self.storage_dir, exist_ok=True)

    def _load_all(self) -> dict:
        if not os.path.exists(self.store_file):
            return {}
        try:
            with open(self.store_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                return data if isinstance(data, dict) else {}
        except Exception as e:
            logging.getLogger("PDFOCR").warning(
                f"KeywordSetManager: 加载失败 ({e})，备份到 .bak")
            try:
                shutil.copy2(self.store_file, self.store_file + ".bak")
            except Exception:
                pass
            return {}

    def _save_all(self, data: dict):
        tmp = self.store_file + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp, self.store_file)

    def list_sets(self) -> list:
        with self._lock:
            return sorted(self._load_all().keys())

    def load(self, name: str):
        with self._lock:
            return self._load_all().get(name)

    def save(self, name: str, keywords: list):
        with self._lock:
            data = self._load_all()
            data[name] = list(keywords)
            self._save_all(data)

    def delete(self, name: str) -> bool:
        with self._lock:
            data = self._load_all()
            if name not in data:
                return False
            del data[name]
            self._save_all(data)
            return True
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_set_manager.py -v`
Expected: PASS (7 passed)

- [ ] **Step 5: 提交**

```bash
git add app/utils/keyword_set_manager.py tests/test_keyword_set_manager.py
git commit -m "feat: 命名关键字集管理（JSON 持久化/原子写/损坏备份）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 4: 关键字批量处理器（逐页扫描）

**Files:**
- Create: `app/core/keyword_batch_processor.py`
- Test: `tests/test_keyword_batch_processor.py`

**Interfaces:**
- Consumes: `KeywordExtractor`（Task 2）、`FileKeywordResult/PageKeywordResult`（Task 1）、`PdfLoader.render_page/page_count`
- Produces: `KeywordBatchProcessor(pdf_loader, ocr_engine, config=None, max_workers=4)`，`process_batch(pdf_paths, keywords, progress_cb=None) -> List[FileKeywordResult]`、`process_one(pdf_path, keywords) -> FileKeywordResult` — Task 5 worker 消费

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_batch_processor.py
from PIL import Image

from app.core.keyword_batch_processor import KeywordBatchProcessor
from app.models.page_result import PageResult


class FakeGGUFEngine:
    """仅 GGUF 路径（用户决策）；recognize_page_auto 返回固定 markdown"""
    engine_name = "gguf"

    def __init__(self, markdown="报关单号：090820241000039736 价税合计：100.00"):
        self.markdown = markdown

    def recognize_page_auto(self, image):
        return PageResult(blocks=[], markdown=self.markdown)


class FakeLoader:
    def __init__(self, page_counts, fail_render=()):
        self.page_counts = page_counts
        self.fail_render = set(fail_render)  # {(path, page_num0)}

    def page_count(self, path):
        return self.page_counts.get(path, 0)

    def render_page(self, path, page_num):
        if (path, page_num) in self.fail_render:
            raise RuntimeError("render fail")
        return Image.new("RGB", (200, 100), "white")


def _proc(loader=None, engine=None):
    return KeywordBatchProcessor(loader or FakeLoader({"a.pdf": 1}),
                                 engine or FakeGGUFEngine(), max_workers=2)


def test_two_files_each_extracted():
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1})
    results = _proc(loader).process_batch(["a.pdf", "b.pdf"], ["报关单号", "价税合计"])
    assert len(results) == 2
    for fr in results:
        assert fr.success is True
        assert len(fr.pages) == 1
        assert fr.pages[0].cells["报关单号"].status == "confirmed"
        assert fr.pages[0].cells["价税合计"].value == "100.00"


def test_multi_page_one_row_per_page():
    loader = FakeLoader({"m.pdf": 3})
    results = _proc(loader).process_batch(["m.pdf"], ["报关单号"])
    fr = results[0]
    assert [p.page_no for p in fr.pages] == [1, 2, 3]


def test_progress_cb_receives_total():
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1, "c.pdf": 1})
    seen = []
    _proc(loader).process_batch(["a.pdf", "b.pdf", "c.pdf"], ["x"],
                                progress_cb=lambda d, t, f: seen.append((d, t)))
    assert len(seen) == 3
    assert seen[-1] == (3, 3)


def test_single_page_render_failure_continues():
    loader = FakeLoader({"a.pdf": 2}, fail_render={("a.pdf", 1)})
    results = _proc(loader).process_batch(["a.pdf"], ["报关单号"])
    fr = results[0]
    assert fr.pages[0].success is False
    assert fr.pages[1].success is True
    assert fr.success is True  # 有成功页


def test_all_pages_fail_marks_file_failed():
    loader = FakeLoader({"bad.pdf": 2},
                        fail_render={("bad.pdf", 0), ("bad.pdf", 1)})
    results = _proc(loader).process_batch(["bad.pdf"], ["报关单号"])
    assert results[0].success is False


def test_unopenable_file_failed():
    loader = FakeLoader({})  # page_count 返回 0
    results = _proc(loader).process_batch(["gone.pdf"], ["x"])
    fr = results[0]
    assert fr.success is False
    assert fr.error_msg


def test_ocr_exception_page_failed_not_crash():
    class BoomEngine:
        engine_name = "gguf"

        def recognize_page_auto(self, image):
            raise RuntimeError("ocr boom")

    results = _proc(engine=BoomEngine()).process_batch(["a.pdf"], ["x"])
    assert results[0].pages[0].success is False
    assert "ocr boom" in results[0].pages[0].error_msg


def test_cancel_raises_interrupted():
    """worker 的 throttled_cb 抛 InterruptedError 应向上传播（与 BatchWorker 同模式）"""
    loader = FakeLoader({"a.pdf": 1, "b.pdf": 1})
    import pytest as _pytest

    def cb(done, total, current):
        raise InterruptedError("用户取消")

    with _pytest.raises(InterruptedError):
        _proc(loader).process_batch(["a.pdf", "b.pdf"], ["x"], progress_cb=cb)
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_batch_processor.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现批量处理器（镜像 batch_processor 并行/取消模式）**

```python
# app/core/keyword_batch_processor.py
"""关键字批量提取 — 逐文件逐页：渲染 → GGUF recognize_page_auto → 提取

仅 GGUF 路径（用户决策：关键字提取用 GGUF，模板框选用 RapidOCR）。
文件级并行（ThreadPoolExecutor）、页级串行；单页失败不中断批次；
progress_cb 内抛 InterruptedError 可取消（与 BatchWorker 同模式）。
"""
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional

from app.core.keyword_extractor import KeywordExtractor
from app.models.keyword_result import FileKeywordResult, PageKeywordResult


class KeywordBatchProcessor:

    def __init__(self, pdf_loader, ocr_engine, config: Optional[dict] = None,
                 max_workers: int = 4):
        self.pdf_loader = pdf_loader
        self.ocr_engine = ocr_engine
        self.config = config or {}
        self.max_workers = max(1, max_workers)

    def process_batch(self, pdf_paths: List[str], keywords: List[str],
                      progress_cb: Optional[Callable[[int, int, str], None]] = None
                      ) -> List[FileKeywordResult]:
        """并行处理全部文件，结果按输入顺序回填；单文件异常不中断批次"""
        results: List[FileKeywordResult] = [None] * len(pdf_paths)
        total = len(pdf_paths)
        completed = 0
        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures = {}
            for idx, path in enumerate(pdf_paths):
                futures[pool.submit(self.process_one, path, keywords)] = idx
            for future in futures:
                idx = futures[future]
                try:
                    results[idx] = future.result()
                except Exception as e:
                    results[idx] = FileKeywordResult(
                        source_file=pdf_paths[idx], success=False, error_msg=str(e))
                completed += 1
                if progress_cb:
                    progress_cb(completed, total, pdf_paths[idx])
        return results

    def process_one(self, pdf_path: str, keywords: List[str]) -> FileKeywordResult:
        extractor = KeywordExtractor(keywords)
        page_count = self.pdf_loader.page_count(pdf_path)
        if page_count <= 0:
            return FileKeywordResult(source_file=pdf_path, success=False,
                                     error_msg="无法打开文件或文件为空")
        pages: List[PageKeywordResult] = []
        for page_no in range(1, page_count + 1):
            pages.append(self._extract_page(pdf_path, page_no, extractor))
        return FileKeywordResult(source_file=pdf_path, pages=pages,
                                 success=any(p.success for p in pages))

    def _extract_page(self, pdf_path: str, page_no: int,
                      extractor: KeywordExtractor) -> PageKeywordResult:
        try:
            image = self.pdf_loader.render_page(pdf_path, page_no - 1)
            result = self.ocr_engine.recognize_page_auto(image)
            markdown = getattr(result, "markdown", "") or ""
            cells = extractor.extract(markdown)
            return PageKeywordResult(page_no=page_no, cells=cells)
        except Exception as e:
            return PageKeywordResult(page_no=page_no, success=False, error_msg=str(e))
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_batch_processor.py -v`
Expected: PASS (9 passed)

- [ ] **Step 5: 提交**

```bash
git add app/core/keyword_batch_processor.py tests/test_keyword_batch_processor.py
git commit -m "feat: 关键字批量处理器（逐页 GGUF 扫描/并行/失败不中断/可取消）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 5: Worker 薄层 + PDF 文本层定位器

**Files:**
- Create: `app/workers/keyword_batch_worker.py`、`app/core/text_layer_locator.py`
- Test: `tests/test_keyword_batch_worker.py`、`tests/test_text_layer_locator.py`

**Interfaces:**
- Consumes: `KeywordBatchProcessor`（Task 4）
- Produces: `KeywordBatchWorker(processor, pdf_files, keywords)`：信号 `progress(int,int,str)` / `finished_all(list)` / `cancelled()`，方法 `cancel()`、属性 `_completed_results` — Task 9/10 消费
- Produces: `locate_words(page, text, scale=1.0, first_only=True) -> List[List[float]]`（pt→像素缩放后的矩形 [x0,y0,x1,y1]）— Task 9 核对面板消费

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_batch_worker.py
"""KeywordBatchWorker 薄层：信号转发与取消传播（QThread，需 qapp）"""
import pytest

from app.workers.keyword_batch_worker import KeywordBatchWorker
from app.core.keyword_batch_processor import KeywordBatchProcessor


class FakeProcessor:
    def __init__(self):
        self.calls = []

    def process_batch(self, pdf_files, keywords, progress_cb=None):
        self.calls.append(("process_batch", keywords))
        progress_cb(1, 1, "a.pdf")
        return []


def _make_worker(processor=None):
    proc = processor or FakeProcessor()
    return KeywordBatchWorker(proc, ["a.pdf"], ["报关单号"]), proc


def test_worker_signals_finished(qapp):
    worker, proc = _make_worker()
    finished = []
    worker.finished_all.connect(finished.append)
    worker.run()
    assert finished == [[]]
    assert proc.calls[0][1] == ["报关单号"]


def test_worker_progress_forwarded(qapp):
    worker, _ = _make_worker()
    seen = []
    worker.progress.connect(lambda d, t, f: seen.append((d, t, f)))
    worker.run()
    assert seen == [(1, 1, "a.pdf")]


def test_worker_cancel_emits_cancelled(qapp):
    class ThrowingProcessor:
        def process_batch(self, pdf_files, keywords, progress_cb=None):
            raise InterruptedError("用户取消")

    worker = KeywordBatchWorker(ThrowingProcessor(), ["a.pdf"], ["x"])
    cancelled = []
    worker.cancelled.connect(lambda: cancelled.append(True))
    worker.run()
    assert cancelled == [True]


def test_worker_completed_results_accumulate(qapp):
    class CollectingProcessor:
        def process_batch(self, pdf_files, keywords, progress_cb=None):
            progress_cb(1, 2, "a.pdf")
            return [1]  # 部分结果

    worker = KeywordBatchWorker(CollectingProcessor(), ["a.pdf", "b.pdf"], ["x"])
    worker.run()
    assert worker._completed_results == [1]
```

```python
# tests/test_text_layer_locator.py
"""PDF 文本层定位：fitz 词级坐标 → 矩形（合成内存 PDF）"""
import fitz
import pytest

from app.core.text_layer_locator import locate_words


@pytest.fixture
def page():
    doc = fitz.open()
    pg = doc.new_page()
    # 中文 insert_text 需字体，测试用英文（定位逻辑与语言无关）
    pg.insert_text((72, 72), "Invoice No: 12345678")
    pg.insert_text((72, 100), "Total: 99.50")
    return pg


def test_locate_existing_text(page):
    rects = locate_words(page, "12345678")
    assert len(rects) == 1
    x0, y0, x1, y1 = rects[0]
    assert x0 < x1 and y0 < y1


def test_scale_applied(page):
    rects = locate_words(page, "12345678", scale=2.0)
    rects_1x = locate_words(page, "12345678", scale=1.0)
    assert rects[0][0] == pytest.approx(rects_1x[0][0] * 2)
    assert rects[0][3] == pytest.approx(rects_1x[0][3] * 2)


def test_locate_missing_returns_empty(page):
    assert locate_words(page, "99999999") == []


def test_locate_multi_word_value(page):
    rects = locate_words(page, "99.50")
    assert len(rects) == 1


def test_empty_text_returns_empty(page):
    assert locate_words(page, "") == []


def test_first_only_returns_one(page):
    pg2 = page  # 同页重复文本
    doc = fitz.open()
    pg3 = doc.new_page()
    pg3.insert_text((72, 72), "X 111")
    pg3.insert_text((72, 120), "X 111")
    assert len(locate_words(pg3, "111", first_only=True)) == 1
    assert len(locate_words(pg3, "111", first_only=False)) >= 2
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_batch_worker.py tests/test_text_layer_locator.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现 Worker 与定位器**

```python
# app/workers/keyword_batch_worker.py
"""关键字批量 worker — QThread 薄层（镜像 BatchWorker）"""
import time

from PyQt6.QtCore import QThread, pyqtSignal as Signal


class KeywordBatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileKeywordResult]
    cancelled = Signal()

    PROGRESS_THROTTLE_MS = 100

    def __init__(self, processor, pdf_files, keywords):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.keywords = keywords
        self._is_cancelled = False
        self._last_progress_time = 0
        self._completed_results = []

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        self._completed_results.clear()

        def throttled_cb(done, total, current):
            if self._is_cancelled:
                raise InterruptedError("用户取消")
            now = time.time() * 1000
            if done == 1 or done == total or \
               now - self._last_progress_time >= self.PROGRESS_THROTTLE_MS:
                self.progress.emit(done, total, current)
                self._last_progress_time = now

        try:
            results = self.processor.process_batch(
                self.pdf_files, self.keywords, throttled_cb
            )
            self.finished_all.emit(results)
        except InterruptedError:
            self.cancelled.emit()
```

```python
# app/core/text_layer_locator.py
"""PDF 文本层定位 — fitz 词级坐标匹配（核对高亮的唯一坐标源）

PDF 文本层坐标为 pt（72dpi 基准）；画布场景坐标是渲染 DPI 的图像像素。
调用方传 scale = render_dpi / 72 换算，与 PdfCanvas 场景一致。
无文本层 / 未找到 → 返回 []（调用方只渲染不高亮）。
"""
from typing import List, Optional


def locate_words(page, text: str, scale: float = 1.0,
                 first_only: bool = True) -> List[List[float]]:
    """在 PDF 页文本层定位 text（跨词匹配，忽略空白差异）。

    Args:
        page: fitz.Page 对象
        text: 要定位的文本（关键字或提取值）
        scale: pt → 像素换算系数（render_dpi / 72）
        first_only: True 只返回首现矩形；False 返回全部

    Returns:
        矩形列表 [x0, y0, x1, y1]（像素坐标）；未找到 → []
    """
    if not text:
        return []
    try:
        words = page.get_text("words")  # (x0,y0,x1,y1,word,block,line,no)
    except Exception:
        return []
    if not words:
        return []
    needle = text.replace(" ", "")
    rects = [(w[0], w[1], w[2], w[3]) for w in words]
    seq = [w[4].replace(" ", "") for w in words]
    n = len(words)
    found: List[List[float]] = []
    for i in range(n):
        if found and first_only:
            break
        joined = ""
        for j in range(i, min(n, i + 64)):
            joined += seq[j]
            if needle in joined:
                xs = [rects[k][0] for k in range(i, j + 1)]
                ys = [rects[k][1] for k in range(i, j + 1)]
                xe = [rects[k][2] for k in range(i, j + 1)]
                ye = [rects[k][3] for k in range(i, j + 1)]
                found.append([min(xs) * scale, min(ys) * scale,
                              max(xe) * scale, max(ye) * scale])
                break
    return found
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_batch_worker.py tests/test_text_layer_locator.py -v`
Expected: PASS（worker 4 + locator 6）

- [ ] **Step 5: 提交**

```bash
git add app/workers/keyword_batch_worker.py app/core/text_layer_locator.py \
       tests/test_keyword_batch_worker.py tests/test_text_layer_locator.py
git commit -m "feat: 关键字批量 worker 薄层 + PDF 文本层定位器（核对高亮坐标源）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 6: 关键字汇总导出

**Files:**
- Create: `app/core/keyword_exporter.py`
- Test: `tests/test_keyword_exporter.py`

**Interfaces:**
- Consumes: `FileKeywordResult/PageKeywordResult/KeywordCell`（Task 1）
- Produces: `KeywordExporter._build_rows(results, include_status=True) -> List[Dict]`、`to_excel(results, output_path, include_status=True)`、`to_csv(results, output_path, include_status=True)` — Task 9/10 消费

- [ ] **Step 1: 写失败测试**

```python
# tests/test_keyword_exporter.py
import pandas as pd
import pytest

from app.core.keyword_exporter import KeywordExporter
from app.models.keyword_result import (FileKeywordResult, PageKeywordResult,
                                       KeywordCell)


def _make_results():
    fr1 = FileKeywordResult(source_file="a.pdf")
    fr1.pages.append(PageKeywordResult(page_no=1, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="", status="not_found"),
    }))
    fr2 = FileKeywordResult(source_file="b.pdf", success=False,
                            error_msg="无法打开文件")
    return [fr1, fr2]


def test_build_rows_one_row_per_page():
    rows = KeywordExporter()._build_rows(_make_results())
    assert len(rows) == 2  # a.pdf 1页 + b.pdf 无页（占位行）
    assert rows[0]["源文件"] == "a.pdf"
    assert rows[0]["页号"] == 1
    assert rows[0]["报关单号"] == "0908"
    assert rows[0]["报关单号_状态"] == "已确认"
    assert rows[0]["价税合计"] == ""
    assert rows[0]["价税合计_状态"] == "未找到"
    assert rows[1]["文件状态"].startswith("失败")


def test_include_status_off(tmp_path):
    rows = KeywordExporter()._build_rows(_make_results(), include_status=False)
    assert "报关单号_状态" not in rows[0]


def test_to_excel_roundtrip(tmp_path):
    out = tmp_path / "kw.xlsx"
    KeywordExporter().to_excel(_make_results(), str(out))
    df = pd.read_excel(out)
    assert "源文件" in df.columns
    assert "报关单号" in df.columns
    assert len(df) == 2


def test_to_csv_has_bom(tmp_path):
    out = tmp_path / "kw.csv"
    KeywordExporter().to_csv(_make_results(), str(out))
    raw = out.read_bytes()
    assert raw.startswith(b"\xef\xbb\xbf")  # utf-8-sig BOM
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_exporter.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现导出器（镜像 exporter.py 模式）**

```python
# app/core/keyword_exporter.py
"""关键字汇总导出 — Excel/CSV：每页一行（文件名|页号|kw|kw_状态|…|文件状态）"""
import pandas as pd
from typing import Dict, List

from app.models.keyword_result import FileKeywordResult

_STATUS_WORDS = {"confirmed": "已确认", "pending": "待确认",
                 "not_found": "未找到", "error": "失败"}


class KeywordExporter:

    def _build_rows(self, results: List[FileKeywordResult],
                    include_status: bool = True) -> List[Dict]:
        keywords: List[str] = []
        for fr in results:
            for pg in fr.pages:
                for kw in pg.cells:
                    if kw not in keywords:
                        keywords.append(kw)
        rows = []
        for fr in results:
            if fr.pages:
                for pg in fr.pages:
                    row = {"源文件": fr.source_file, "页号": pg.page_no,
                           "文件状态": "成功" if fr.success else f"失败：{fr.error_msg}"}
                    for kw in keywords:
                        cell = pg.cells.get(kw)
                        row[kw] = cell.value if cell and cell.status != "not_found" else ""
                        if include_status:
                            row[f"{kw}_状态"] = (
                                _STATUS_WORDS.get(cell.status, "") if cell else "未找到")
                    rows.append(row)
            else:
                rows.append({"源文件": fr.source_file, "页号": "",
                             "文件状态": f"失败：{fr.error_msg}"})
        return rows

    def to_excel(self, results: List[FileKeywordResult], output_path: str,
                 include_status: bool = True):
        pd.DataFrame(self._build_rows(results, include_status)).to_excel(
            output_path, index=False, engine="openpyxl")

    def to_csv(self, results: List[FileKeywordResult], output_path: str,
               include_status: bool = True):
        pd.DataFrame(self._build_rows(results, include_status)).to_csv(
            output_path, index=False, encoding="utf-8-sig")
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/test_keyword_exporter.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: 提交**

```bash
git add app/core/keyword_exporter.py tests/test_keyword_exporter.py
git commit -m "feat: 关键字汇总 Excel/CSV 导出（每页一行+状态列）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 7: 主题角色（状态底色）

**Files:**
- Modify: `app/ui/theme_manager.py:23-58`（COLORS 两主题）
- Test: `tests/ui/test_theme_manager.py`（追加断言）

**Interfaces:**
- Produces: 新角色 `success_bg`/`warning_bg`/`error_bg`（明暗两主题）— Task 8/9 汇总树与核对面板消费

- [ ] **Step 1: 写失败测试（追加到 tests/ui/test_theme_manager.py）**

```python
    def test_status_bg_roles_both_themes(self):
        """Task 7: 单元格状态底色角色（明暗两主题均存在且不同主题值不同）"""
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('success_bg') == '#E7F5E9'
        assert ThemeManager.get_color('warning_bg') == '#FFF8E1'
        assert ThemeManager.get_color('error_bg') == '#FDE8E8'
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('success_bg') == '#12301B'
        assert ThemeManager.get_color('warning_bg') == '#3A2F14'
        assert ThemeManager.get_color('error_bg') == '#3A1518'
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_theme_manager.py -k status_bg -v`
Expected: FAIL（KeyError: 'success_bg'）

- [ ] **Step 3: 实现 — 在 COLORS 两个主题 dict 各加三行**

`app/ui/theme_manager.py` light 主题（`'white': '#ffffff',` 之后）：
```python
            'success_bg': '#E7F5E9',
            'warning_bg': '#FFF8E1',
            'error_bg': '#FDE8E8',
```
dark 主题（`'white': '#ffffff',` 之后）：
```python
            'success_bg': '#12301B',
            'warning_bg': '#3A2F14',
            'error_bg': '#3A1518',
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_theme_manager.py -v`
Expected: PASS（含新断言）

- [ ] **Step 5: 提交**

```bash
git add app/ui/theme_manager.py tests/ui/test_theme_manager.py
git commit -m "feat: ThemeManager 状态底色角色 success_bg/warning_bg/error_bg

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 8: 汇总树 widget

**Files:**
- Create: `app/ui/widgets/keyword_summary_tree.py`
- Test: `tests/ui/test_keyword_summary_tree.py`

**Interfaces:**
- Consumes: `FileKeywordResult/PageKeywordResult/KeywordCell`（Task 1）、ThemeManager 新角色（Task 7）
- Produces: `KeywordSummaryTree(QTreeWidget)`：`load_results(results: List[FileKeywordResult])`、信号 `cell_inspect_requested(int file_index, int page_no, str keyword)`、`apply_theme()` — Task 9/10 消费

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_keyword_summary_tree.py
"""汇总树：分组折叠/状态底色/命中率徽标/编辑修正/核对信号"""
from PyQt6.QtCore import Qt

from app.models.keyword_result import (FileKeywordResult, PageKeywordResult,
                                       KeywordCell)
from app.ui.widgets.keyword_summary_tree import KeywordSummaryTree
from app.ui.theme_manager import ThemeManager


def _make_results():
    fr = FileKeywordResult(source_file="a.pdf")
    fr.pages.append(PageKeywordResult(page_no=1, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="100", status="pending"),
    }))
    # 页2：报关单号未找到（1/2=50% 低命中 ⚠）；价税合计命中（2/2=100% 无 ⚠）
    fr.pages.append(PageKeywordResult(page_no=2, cells={
        "报关单号": KeywordCell(keyword="报关单号", value="", status="not_found"),
        "价税合计": KeywordCell(keyword="价税合计", value="200", status="confirmed"),
    }))
    return [fr]


def test_group_and_page_rows(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    assert tree.topLevelItemCount() == 1
    group = tree.topLevelItem(0)
    assert "a.pdf" in group.text(0)
    assert group.childCount() == 2
    assert "第 1 页" == group.child(0).text(0)
    assert group.isExpanded() is False  # 默认折叠


def test_cell_values_and_status_bg(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    row = tree.topLevelItem(0).child(0)
    assert row.text(2) == "0908"
    assert row.text(3) == "100"
    # confirmed → success_bg；pending → warning_bg
    assert row.background(2).color().name() == \
        ThemeManager.get_color('success_bg').lower()
    assert row.background(3).color().name() == \
        ThemeManager.get_color('warning_bg').lower()
    # not_found → 无底色、占位符 '—'
    row2 = tree.topLevelItem(0).child(1)
    assert row2.text(2) == "—"
    assert not row2.background(2).style()


def test_header_has_keyword_and_hit_ratio(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    h = tree.headerItem()
    assert "报关单号" in h.text(2)
    assert "%" in h.text(2)   # 命中率徽标
    assert "50%" in h.text(2)  # 报关单号命中 1/2 页
    assert "⚠" in h.text(2)    # 50% < 60% → 低命中警示
    assert "价税合计" in h.text(3)
    assert "100%" in h.text(3)  # 价税合计命中 2/2
    assert "⚠" not in h.text(3)


def test_double_click_emits_inspect(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    emitted = []
    tree.cell_inspect_requested.connect(lambda *a: emitted.append(a))
    row = tree.topLevelItem(0).child(0)
    tree._on_item_double_clicked(row, 2)
    assert emitted == [(0, 1, "报关单号")]


def test_edit_marks_manually_edited(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    row = tree.topLevelItem(0).child(0)
    col = 2
    cell = tree._results[0].pages[0].cells["报关单号"]
    row.setText(col, "9999")
    tree._on_item_changed(row, col)
    assert cell.value == "9999"
    assert cell.manually_edited is True
    assert row.background(col).color().name() == \
        ThemeManager.get_color('bg_selected').lower()


def test_theme_refresh_recolors(qapp):
    tree = KeywordSummaryTree()
    tree.load_results(_make_results())
    ThemeManager.set_theme('dark')
    row = tree.topLevelItem(0).child(0)
    assert row.background(2).color().name() == \
        ThemeManager.get_color('success_bg').lower()
```

注意：测试 `test_header_has_keyword_and_hit_ratio` 中"价税合计"命中 1/2=50% < 60% 也会带 ⚠——两者都是 50%，两个列头都该有 ⚠。调整断言：两列都含 ⚠（都 50%）。修正：`assert "⚠" in h.text(3)` 也一样。为区分，加第三页让价税合计命中率高？简单：构造结果时 报关单号命中 1/2、价税合计命中 2/2（页2 价税合计 confirmed）→ 报关单号 ⚠、价税合计无。修改 _make_results：页2 价税合计 value="200" status="confirmed"。同时页2 报关单号 not_found 保持。

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_keyword_summary_tree.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现汇总树**

```python
# app/ui/widgets/keyword_summary_tree.py
"""关键字汇总树 — 按文件分组折叠、每页一行、列头命中率徽标

视觉（frontend-design 确认）：档案夹文件组头（默认折叠）、值单元格按状态
着色（ThemeManager 状态底色角色）、not_found 显示 '—'、双击编辑 + 人工
修正标记（bg_selected 蓝底）、双击值单元格发射核对信号。
"""
from typing import List

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import QTreeWidget, QTreeWidgetItem

from app.models.keyword_result import FileKeywordResult, KeywordCell
from app.ui.theme_manager import ThemeManager

_STATUS_BG = {"confirmed": "success_bg", "pending": "warning_bg", "error": "error_bg"}
_STATUS_TEXT = {"confirmed": "已确认", "pending": "待确认",
                "not_found": "未找到", "error": "失败"}
_SOURCE_TEXT = {"exact": "精确", "loose": "宽松", "none": "未匹配"}

LOW_HIT_RATIO = 0.6  # 命中率低于此值的列头加 ⚠ 警示


class KeywordSummaryTree(QTreeWidget):
    """分组折叠汇总树"""

    cell_inspect_requested = pyqtSignal(int, int, str)  # file_index, page_no, keyword

    def __init__(self, parent=None):
        super().__init__(parent)
        self._results: List[FileKeywordResult] = []
        self._loading = False
        self.setColumnCount(2)
        self.setHeaderLabels(["单据", "状态"])
        self.setAlternatingRowColors(True)
        self.setEditTriggers(QTreeWidget.EditTrigger.DoubleClicked)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)
        self.itemChanged.connect(self._on_item_changed)
        ThemeManager.register_refresh_callback(self.apply_theme)

    # ---------- 数据 ----------

    def load_results(self, results: List[FileKeywordResult]):
        self._results = results
        keywords = self._collect_keywords(results)
        self.setColumnCount(2 + len(keywords))
        self._loading = True
        try:
            self._rebuild_headers(keywords)
            self.clear()
            for idx, fr in enumerate(results):
                group = self._make_group_item(idx, fr)
                self.addTopLevelItem(group)
                for page in fr.pages:
                    group.addChild(self._make_page_item(idx, page, keywords))
                group.setExpanded(False)  # 默认折叠
        finally:
            self._loading = False
        self.resizeColumnToContents(0)

    def _collect_keywords(self, results: List[FileKeywordResult]) -> List[str]:
        kws: List[str] = []
        for fr in results:
            for page in fr.pages:
                for kw in page.cells:
                    if kw not in kws:
                        kws.append(kw)
        return kws

    def _rebuild_headers(self, keywords: List[str]):
        total_pages = sum(len(fr.pages) for fr in self._results)
        headers = ["单据", "状态"]
        for kw in keywords:
            hit = sum(1 for fr in self._results for pg in fr.pages
                      if pg.cells.get(kw) and pg.cells[kw].status != "not_found")
            ratio = (hit / total_pages) if total_pages else 0.0
            mark = "⚠ " if ratio < LOW_HIT_RATIO else ""
            headers.append(f"{kw} ({mark}{int(round(ratio * 100))}%)")
        self.setHeaderLabels(headers)

    def _make_group_item(self, idx: int, fr: FileKeywordResult) -> QTreeWidgetItem:
        pending = sum(1 for pg in fr.pages
                      for c in pg.cells.values() if c.status == "pending")
        text = f"{fr.source_file}  ·  {len(fr.pages)}页"
        if pending:
            text += f"  ·  {pending}待确认"
        item = QTreeWidgetItem([text, "成功" if fr.success else "失败"])
        item.setFlags(Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable)
        if not fr.success:
            item.setToolTip(1, fr.error_msg)
        return item

    def _make_page_item(self, idx: int, page, keywords: List[str]) -> QTreeWidgetItem:
        row = [f"第 {page.page_no} 页", "成功" if page.success else "失败"]
        item = QTreeWidgetItem(row)
        if not page.success:
            item.setToolTip(1, page.error_msg)
            for col in range(self.columnCount()):
                item.setBackground(col, QColor(ThemeManager.get_color("error_bg")))
            return item
        for k, kw in enumerate(keywords):
            col = 2 + k
            cell = page.cells.get(kw)
            if cell is None:
                continue
            if cell.status == "not_found":
                item.setText(col, "—")
                item.setForeground(col, QColor(ThemeManager.get_color("text_disabled")))
            else:
                item.setText(col, cell.value)
                if cell.status == "pending":
                    item.setForeground(col, QColor(ThemeManager.get_color("warning_text")))
                bg = _STATUS_BG.get(cell.status)
                if bg:
                    item.setBackground(col, QColor(ThemeManager.get_color(bg)))
            if cell.manually_edited:
                item.setBackground(col, QColor(ThemeManager.get_color("bg_selected")))
            tip = self._cell_tooltip(cell)
            if tip:
                item.setToolTip(col, tip)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsEditable)
            item.setData(col, Qt.ItemDataRole.UserRole, (idx, page.page_no, kw))
        return item

    @staticmethod
    def _cell_tooltip(cell: KeywordCell) -> str:
        parts = [f"状态: {_STATUS_TEXT.get(cell.status, cell.status)}",
                 f"匹配: {_SOURCE_TEXT.get(cell.source, cell.source)}"]
        if cell.line_text:
            parts.append(f"原文: {cell.line_text}")
        if cell.manually_edited:
            parts.append("已人工修正")
        return "\n".join(parts)

    # ---------- 交互 ----------

    def _on_item_double_clicked(self, item: QTreeWidgetItem, column: int):
        if column < 2:
            return
        data = item.data(column, Qt.ItemDataRole.UserRole)
        if data:
            idx, page_no, kw = data
            self.cell_inspect_requested.emit(idx, page_no, kw)

    def _on_item_changed(self, item: QTreeWidgetItem, column: int):
        if self._loading or column < 2:
            return
        data = item.data(column, Qt.ItemDataRole.UserRole)
        if not data:
            return
        idx, page_no, kw = data
        fr = self._results[idx]
        if page_no < 1 or page_no > len(fr.pages):
            return
        cell = fr.pages[page_no - 1].cells.get(kw)
        if cell is None:
            return
        new_value = item.text(column)
        if new_value == cell.value and cell.manually_edited:
            return
        cell.value = new_value
        cell.manually_edited = True
        item.setBackground(column, QColor(ThemeManager.get_color("bg_selected")))

    # ---------- 主题 ----------

    def apply_theme(self):
        self.setStyleSheet(f"""
            QTreeWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                alternate-background-color: {ThemeManager.get_color('bg_hover')};
                border: none;
                outline: none;
                color: {ThemeManager.get_color('text_primary')};
            }}
            QTreeWidget::item {{
                padding: {ThemeManager.get_spacing('xs')}px;
            }}
            QTreeWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_primary')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('xs')}px;
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        for i in range(self.topLevelItemCount()):
            self._refresh_subtree(self.topLevelItem(i))

    def _refresh_subtree(self, item: QTreeWidgetItem):
        for col in range(self.columnCount()):
            item.setBackground(col, QColor())  # 清空再重刷
            item.setForeground(col, QColor())
        for i in range(item.childCount()):
            self._refresh_subtree(item.child(i))
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_keyword_summary_tree.py -v`
Expected: PASS（6 passed）

- [ ] **Step 5: 提交**

```bash
git add app/ui/widgets/keyword_summary_tree.py tests/ui/test_keyword_summary_tree.py
git commit -m "feat: 关键字汇总树（分组折叠/状态底色/命中率徽标/编辑修正/核对信号）

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 9: 汇总页 + 核对面板 + 关键字集对话框

**Files:**
- Create: `app/ui/widgets/keyword_inspection_panel.py`、`app/ui/widgets/keyword_summary_page.py`、`app/ui/widgets/keyword_set_dialog.py`
- Test: `tests/ui/test_keyword_inspection_panel.py`、`tests/ui/test_keyword_summary_page.py`

**Interfaces:**
- Consumes: `KeywordSummaryTree`（Task 8）、`KeywordSetManager`（Task 3）、`locate_words`（Task 5）、`KeywordExporter`（Task 6）、`PdfCanvas.load_image/highlight_bbox/clear_highlights`（现有）、ThemeManager 新角色（Task 7）
- Produces: `KeywordInspectionPanel`：`show_inspection(file_path, page_no, loader, dpi, cells: Dict[str, KeywordCell], focus_keyword=None)`、信号 `value_edited(int file_index, int page_no, str keyword, str new_value)`
- Produces: `KeywordSummaryPage(set_manager)`：信号 `extract_requested(list keywords)` / `export_requested()` / `save_set_requested(str, list)` / `manage_sets_requested()` / `cancel_requested()`；方法 `load_results(results)` / `set_progress(done, total, current)` / `set_running(bool)` / `enable_export(bool)` / `apply_theme()`
- Produces: `KeywordSetDialog(set_manager)`：返回 `(name, keywords)` 或 None；`load_requested` 由外部处理（见 Step 3 交互约定）

- [ ] **Step 1: 写失败测试**

```python
# tests/ui/test_keyword_inspection_panel.py
"""核对面板：渲染+文本层高亮+单元格表回写"""
from PIL import Image

from app.models.keyword_result import PageKeywordResult, KeywordCell
from app.ui.widgets.keyword_inspection_panel import KeywordInspectionPanel


class FakeLoader:
    def render_page(self, path, page_num):
        return Image.new("RGB", (200, 100), "white")


def _cells():
    return {
        "报关单号": KeywordCell(keyword="报关单号", value="0908", status="confirmed"),
        "价税合计": KeywordCell(keyword="价税合计", value="", status="not_found"),
    }


def test_show_inspection_fills_table_and_title(qapp):
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells(), "报关单号")
    assert "a.pdf" in panel.title_label.text()
    assert panel.cell_table.rowCount() == 2
    assert panel.cell_table.item(0, 0).text() == "报关单号"
    assert panel.cell_table.item(0, 1).text() == "0908"


def test_no_text_layer_renders_without_highlight(qapp):
    """无文本层的图（fake）→ 只渲染不高亮，不崩溃"""
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells())
    assert panel.canvas.pixmap_item is not None


def test_edit_cell_emits_value_edited(qapp):
    panel = KeywordInspectionPanel()
    panel.show_inspection("a.pdf", 1, FakeLoader(), 200, _cells())
    emitted = []
    panel.value_edited.connect(lambda *a: emitted.append(a))
    panel.cell_table.item(0, 1).setText("9999")  # 触发 itemChanged → value_edited
    assert emitted == [(0, 1, "报关单号", "9999")]
```

```python
# tests/ui/test_keyword_summary_page.py
"""汇总页：守卫/集合下拉/统计/进度"""
from app.ui.widgets.keyword_summary_page import KeywordSummaryPage
from app.utils.keyword_set_manager import KeywordSetManager


def _make_page(tmp_path):
    mgr = KeywordSetManager(storage_dir=str(tmp_path))
    page = KeywordSummaryPage(mgr)
    return page, mgr


def test_construct(qapp, tmp_path):
    page, _ = _make_page(tmp_path)
    assert page.tree is not None


def test_extract_guard_empty_keywords(qapp, tmp_path):
    """关键字为空 → 不发提取信号"""
    page, _ = _make_page(tmp_path)
    emitted = []
    page.extract_requested.connect(lambda k: emitted.append(k))
    page.keyword_input.setText("   ")
    page._on_extract_clicked()
    assert emitted == []


def test_extract_emits_parsed_keywords(qapp, tmp_path):
    page, _ = _make_page(tmp_path)
    emitted = []
    page.extract_requested.connect(lambda k: emitted.append(k))
    page.keyword_input.setText("报关单号,价税合计；发票号码")
    page._on_extract_clicked()
    assert emitted == [["报关单号", "价税合计", "发票号码"]]


def test_set_combo_filled_from_manager(qapp, tmp_path):
    page, mgr = _make_page(tmp_path)
    mgr.save("发票集", ["发票号码"])
    page.refresh_sets()
    assert page.set_combo.count() == 1
    assert page.set_combo.itemText(0) == "发票集"


def test_set_combo_load_fills_input(qapp, tmp_path):
    page, mgr = _make_page(tmp_path)
    mgr.save("报关单集", ["报关单号", "境内收货人"])
    page.refresh_sets()
    page.set_combo.setCurrentText("报关单集")  # 触发 currentIndexChanged → 填输入框
    assert "报关单号" in page.keyword_input.text()


def test_running_state_controls_progress(qapp, tmp_path):
    page, _ = _make_page(tmp_path)
    page.set_running(True)
    assert page.progress_bar.isVisible()
    assert page.btn_cancel.isVisible()
    page.set_running(False)
    assert not page.progress_bar.isVisible()
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_keyword_inspection_panel.py tests/ui/test_keyword_summary_page.py -v`
Expected: FAIL（ModuleNotFoundError）

- [ ] **Step 3: 实现三个 widget**

```python
# app/ui/widgets/keyword_inspection_panel.py
"""内嵌核对面板 — 渲染该页 + PDF 文本层高亮 + 该页单元格表（可改值回写）

坐标只来自 PDF 文本层（text_layer_locator），绝不来自 VLM。
"""
import fitz

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QLabel, QTableWidget,
                             QTableWidgetItem, QHeaderView)

from app.core.text_layer_locator import locate_words
from app.models.keyword_result import KeywordCell
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.theme_manager import ThemeManager

_STATUS_TEXT = {"confirmed": "✓ 已确认", "pending": "⚠ 待确认",
                "not_found": "— 未找到"}
_STATUS_COLOR = {"confirmed": "success", "pending": "warning_text",
                 "not_found": "text_disabled"}


class KeywordInspectionPanel(QWidget):
    """右侧核对面板（汇总页内嵌，初始隐藏）"""

    value_edited = pyqtSignal(int, int, str, str)  # file_index, page_no, keyword, new_value

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedWidth(430)
        self._file_index = 0
        self._page_no = 1
        self._cells = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ThemeManager.get_spacing('sm'), 0, 0, 0)
        self.title_label = QLabel("")
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        layout.addWidget(self.title_label)
        self.canvas = PdfCanvas()
        layout.addWidget(self.canvas, stretch=3)
        self.cell_table = QTableWidget(0, 3)
        self.cell_table.setHorizontalHeaderLabels(["关键字", "值", "状态"])
        self.cell_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self.cell_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch)
        self.cell_table.itemChanged.connect(self._on_cell_changed)
        layout.addWidget(self.cell_table, stretch=2)
        ThemeManager.register_refresh_callback(self.apply_theme)

    def show_inspection(self, file_path: str, page_no: int, loader, dpi: int,
                        cells: dict, focus_keyword: str = None):
        """渲染该页、高亮焦点单元格（值优先，值未找到退而定位关键字）、填表"""
        self._page_no = page_no
        self._cells = cells
        self.title_label.setText(f"{file_path}  ·  第 {page_no} 页")
        image = loader.render_page(file_path, page_no - 1)
        self.canvas.load_image(image)
        self.canvas.clear_highlights()
        focus = None
        if focus_keyword and focus_keyword in cells and cells[focus_keyword].status != "not_found":
            focus = cells[focus_keyword].value or focus_keyword
        elif focus_keyword:
            focus = focus_keyword
        if focus:
            self._highlight_on_text_layer(file_path, page_no, focus, dpi)
        self._fill_table()

    def _highlight_on_text_layer(self, file_path: str, page_no: int, text: str, dpi: int):
        """fitz 文本层定位 → 画布高亮（pt→像素 scale = dpi/72）"""
        try:
            doc = fitz.open(file_path)
            try:
                page = doc[page_no - 1]
                rects = locate_words(page, text, scale=dpi / 72.0)
            finally:
                doc.close()
        except Exception:
            rects = []
        for r in rects:
            self.canvas.highlight_bbox(r)

    def _fill_table(self):
        self.cell_table.blockSignals(True)
        self.cell_table.setRowCount(len(self._cells))
        for row, (kw, cell) in enumerate(self._cells.items()):
            self.cell_table.setItem(row, 0, QTableWidgetItem(kw))
            value_item = QTableWidgetItem(cell.value if cell.status != "not_found" else "")
            value_item.setFlags(value_item.flags() | Qt.ItemFlag.ItemIsEditable)
            self.cell_table.setItem(row, 1, value_item)
            status_item = QTableWidgetItem(_STATUS_TEXT.get(cell.status, cell.status))
            color_role = _STATUS_COLOR.get(cell.status)
            if color_role:
                status_item.setForeground(QColor(ThemeManager.get_color(color_role)))
            self.cell_table.setItem(row, 2, status_item)
        self.cell_table.blockSignals(False)

    def _on_cell_changed(self, item):
        if item.column() != 1:
            return
        row = item.row()
        kw = self.cell_table.item(row, 0).text() if self.cell_table.item(row, 0) else ""
        self.value_edited.emit(self._file_index, self._page_no, kw, item.text())

    def apply_theme(self):
        self.cell_table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
                gridline-color: {ThemeManager.get_color('border')};
                alternate-background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
            QTableWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_primary')};
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
```

```python
# app/ui/widgets/keyword_summary_page.py
"""关键字汇总页 — 操作带 / 汇总树 / 核对面板 / 统计与进度

布局（frontend-design 确认）：操作带（关键字输入+提取+导出 | 集合+保存+管理）
→ 左汇总树 + 右核对面板（初始隐藏）→ 底部统计条 + 进度条 + 取消。
"""
import re

from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                             QPushButton, QLabel, QComboBox, QProgressBar,
                             QSplitter, QMessageBox)

from app.ui.widgets.keyword_summary_tree import KeywordSummaryTree
from app.ui.widgets.keyword_inspection_panel import KeywordInspectionPanel
from app.ui.widgets.keyword_set_dialog import KeywordSetDialog
from app.ui.widgets.button_style import primary_qss
from app.ui.theme_manager import ThemeManager

_KW_SPLIT_RE = re.compile(r"[,，、;\n]+")


class KeywordSummaryPage(QWidget):
    """关键字批量汇总页（主题核心）"""

    extract_requested = pyqtSignal(list)         # keywords
    export_requested = pyqtSignal()
    save_set_requested = pyqtSignal(str, list)   # name, keywords
    manage_sets_requested = pyqtSignal()
    cancel_requested = pyqtSignal()

    def __init__(self, set_manager, parent=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self._build_ui()
        self._refresh_sets()
        ThemeManager.register_refresh_callback(self.apply_theme)

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(ThemeManager.get_spacing('lg'),
                                  ThemeManager.get_spacing('md'),
                                  ThemeManager.get_spacing('lg'),
                                  ThemeManager.get_spacing('sm'))
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # Row1：关键字输入 + 提取 + 导出
        row1 = QHBoxLayout()
        self.keyword_input = QLineEdit()
        self.keyword_input.setPlaceholderText(
            "逗号/顿号分隔，如：报关单号,价税合计,发票号码")
        row1.addWidget(self.keyword_input, stretch=1)
        self.btn_extract = QPushButton("提取")
        self.btn_extract.setStyleSheet(primary_qss())
        self.btn_extract.clicked.connect(self._on_extract_clicked)
        row1.addWidget(self.btn_extract)
        self.btn_export = QPushButton("导出 Excel")
        self.btn_export.setStyleSheet(primary_qss())
        self.btn_export.setEnabled(False)
        self.btn_export.clicked.connect(self.export_requested.emit)
        row1.addWidget(self.btn_export)
        layout.addLayout(row1)

        # Row2：关键字集
        row2 = QHBoxLayout()
        row2.addWidget(QLabel("集合:"))
        self.set_combo = QComboBox()
        self.set_combo.currentIndexChanged.connect(
            lambda _i: self._on_set_selected())
        row2.addWidget(self.set_combo)
        self.btn_save_set = QPushButton("保存为集合")
        self.btn_save_set.clicked.connect(self._on_save_set)
        row2.addWidget(self.btn_save_set)
        self.btn_manage_sets = QPushButton("管理集合")
        self.btn_manage_sets.clicked.connect(self.manage_sets_requested.emit)
        row2.addWidget(self.btn_manage_sets)
        row2.addStretch()
        layout.addLayout(row2)

        # 主体：汇总树 + 核对面板（初始隐藏）
        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        self.tree = KeywordSummaryTree()
        self.splitter.addWidget(self.tree)
        self.inspection = KeywordInspectionPanel()
        self.inspection.setVisible(False)
        self.splitter.addWidget(self.inspection)
        self.splitter.setStretchFactor(0, 3)
        self.splitter.setStretchFactor(1, 1)
        layout.addWidget(self.splitter, stretch=1)

        # Row3：统计 + 进度 + 取消
        self.stats_label = QLabel("尚未提取")
        self.stats_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        layout.addWidget(self.stats_label)
        progress_row = QHBoxLayout()
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        progress_row.addWidget(self.progress_bar, stretch=1)
        self.btn_cancel = QPushButton("取消")
        self.btn_cancel.setVisible(False)
        self.btn_cancel.clicked.connect(self.cancel_requested.emit)
        progress_row.addWidget(self.btn_cancel)
        layout.addLayout(progress_row)

        self._last_results = []

    # ---------- 对外接口 ----------

    def load_results(self, results):
        self._last_results = results
        self.tree.load_results(results)
        self._update_stats(results)

    def set_progress(self, done: int, total: int, current: str):
        self.progress_bar.setRange(0, max(1, total))
        self.progress_bar.setValue(done)
        self.stats_label.setText(f"正在提取 {done}/{total}: {current}")

    def set_running(self, running: bool):
        self.progress_bar.setVisible(running)
        self.btn_cancel.setVisible(running)
        self.btn_extract.setEnabled(not running)

    def enable_export(self, enabled: bool):
        self.btn_export.setEnabled(enabled)

    def refresh_sets(self):
        self._refresh_sets()

    def current_results(self):
        return self._last_results

    # ---------- 内部 ----------

    def _refresh_sets(self):
        current = self.set_combo.currentText()
        self.set_combo.blockSignals(True)
        self.set_combo.clear()
        self.set_combo.addItems(self.set_manager.list_sets())
        if current:
            idx = self.set_combo.findText(current)
            self.set_combo.setCurrentIndex(max(0, idx))
        self.set_combo.blockSignals(False)

    def _on_set_selected(self):
        name = self.set_combo.currentText()
        if not name:
            return
        kws = self.set_manager.load(name)
        if kws:
            self.keyword_input.setText("，".join(kws))

    def _on_extract_clicked(self):
        keywords = [k.strip() for k in _KW_SPLIT_RE.split(self.keyword_input.text())
                    if k.strip()]
        if not keywords:
            return
        self.extract_requested.emit(keywords)

    def _on_save_set(self):
        keywords = [k.strip() for k in _KW_SPLIT_RE.split(self.keyword_input.text())
                    if k.strip()]
        if not keywords:
            QMessageBox.warning(self, "提示", "请先输入关键字")
            return
        name, ok = KeywordSetDialog.ask_name(self, self.set_manager.list_sets())
        if ok and name:
            self.save_set_requested.emit(name, keywords)

    def _update_stats(self, results):
        files = len(results)
        pages = sum(len(fr.pages) for fr in results)
        pending = sum(1 for fr in results for pg in fr.pages
                      for c in pg.cells.values() if c.status == "pending")
        failed = sum(1 for fr in results if not fr.success)
        self.stats_label.setText(
            f"共 {files} 个文件 | {pages} 页 | 待确认 {pending} | 失败 {failed}")

    def apply_theme(self):
        self.stats_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};")
        self.btn_extract.setStyleSheet(primary_qss())
        self.btn_export.setStyleSheet(primary_qss())
        self.inspection.apply_theme()
```

```python
# app/ui/widgets/keyword_set_dialog.py
"""关键字集管理对话框 — 列出/保存/删除命名集合"""
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QListWidget,
                             QLineEdit, QPushButton, QMessageBox, QLabel)

from app.ui.theme_manager import ThemeManager


class KeywordSetDialog(QDialog):
    """管理对话框：左列表 + 右操作。静态 ask_name() 用于快速命名保存。"""

    def __init__(self, set_manager, parent=None):
        super().__init__(parent)
        self.set_manager = set_manager
        self.setWindowTitle("管理关键字集")
        self.setMinimumSize(420, 320)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("已保存的集合:"))
        self.list_widget = QListWidget()
        self._refresh_list()
        layout.addWidget(self.list_widget)
        btns = QHBoxLayout()
        self.btn_load = QPushButton("加载")
        self.btn_load.clicked.connect(self._on_load)
        self.btn_delete = QPushButton("删除")
        self.btn_delete.clicked.connect(self._on_delete)
        self.btn_close = QPushButton("关闭")
        self.btn_close.clicked.connect(self.accept)
        for b in (self.btn_load, self.btn_delete, self.btn_close):
            btns.addWidget(b)
        layout.addLayout(btns)

    def _refresh_list(self):
        self.list_widget.clear()
        self.list_widget.addItems(self.set_manager.list_sets())

    def _on_load(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        kws = self.set_manager.load(item.text())
        if kws:
            self.accept()
            self._loaded = (item.text(), kws)
        else:
            self._loaded = None

    def _on_delete(self):
        item = self.list_widget.currentItem()
        if not item:
            return
        if QMessageBox.question(self, "确认", f"删除集合「{item.text()}」？") \
                == QMessageBox.StandardButton.Yes:
            self.set_manager.delete(item.text())
            self._refresh_list()

    def result_value(self):
        return getattr(self, "_loaded", None)

    @staticmethod
    def ask_name(parent, existing: list):
        """快速命名保存对话框：返回 (name, ok)"""
        from PyQt6.QtWidgets import QInputDialog
        name, ok = QInputDialog.getText(
            parent, "保存为集合", "集合名称：", text="")
        if not ok or not name.strip():
            return None, False
        return name.strip(), True
```

- [ ] **Step 4: 运行确认通过**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_keyword_inspection_panel.py tests/ui/test_keyword_summary_page.py -v`
Expected: PASS（inspection 3 + summary 6；若 PdfCanvas 构造报缺省参数错误，按其签名调整 `KeywordInspectionPanel` 里 `PdfCanvas()` 的构造参数）

- [ ] **Step 5: 提交**

```bash
git add app/ui/widgets/keyword_inspection_panel.py app/ui/widgets/keyword_summary_page.py \
       app/ui/widgets/keyword_set_dialog.py \
       tests/ui/test_keyword_inspection_panel.py tests/ui/test_keyword_summary_page.py
git commit -m "feat: 关键字汇总页/核对面板（文本层高亮+回写）/关键字集对话框

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 10: 主窗口三页导航重组 + 删除无关组件

**Files:**
- Modify: `app/ui/main_window.py`（导航注册 `_init_navigation` :592-616、引擎就绪 `_on_ocr_ready` :469-486、互斥守卫 `on_batch_run` :1618、删除 auto 单页解析链路与双向高亮、新建关键字接线方法）
- Delete: `app/ui/widgets/layout_visualizer.py`、`app/ui/widgets/result_panel.py`、`app/workers/ocr_worker.py`
- Delete tests: `tests/ui/widgets/test_layout_visualizer.py`、`tests/ui/widgets/test_result_panel.py`、`tests/ui/test_two_way_highlight.py`
- Modify tests: `tests/ui/test_theme_refresh.py`（删 right_panel 断言）、`tests/ui/integration_test.py`（若引用已删组件）

**Interfaces:**
- Consumes: `KeywordSummaryPage`/`KeywordInspectionPanel`（Task 9）、`KeywordBatchProcessor`（Task 4）、`KeywordBatchWorker`（Task 5）、`KeywordSetManager`（Task 3）、`KeywordExporter`（Task 6）
- Produces: 主窗口新方法 `_create_keyword_summary_page` / `_on_keyword_extract` / `_on_keyword_done` / `_on_keyword_cancelled` / `_on_keyword_save_set` / `_on_keyword_manage_sets` / `_on_keyword_cancel` / `on_keyword_export` / `_on_cell_inspect` / `_on_inspection_value_edited`

- [ ] **Step 1: 写失败测试（追加到 tests/ui/test_theme_refresh.py）**

```python
    def test_keyword_page_present_in_main_window(self, qapp, monkeypatch):
        """Task 10: 主窗口含关键字汇总页（导航第 3 项）"""
        w = _construct_main_window(monkeypatch, _make_config(theme='light'))
        try:
            assert hasattr(w, "keyword_page")
            assert w.keyword_page is not None
        finally:
            w.gpu_status.cleanup()
```

- [ ] **Step 2: 运行确认失败**

Run: `venv/Scripts/python.exe -m pytest tests/ui/test_theme_refresh.py -k keyword_page -v`
Expected: FAIL（AttributeError: keyword_page）

- [ ] **Step 3: 接线与删除**

3a. `_init_navigation`（:592-616）在 history 项后追加：

```python
        self.navigationInterface.addItem(
            routeKey='keyword',
            icon=_icon('fa5s.magic'),
            text='关键字汇总',
            onClick=lambda: self.switchTo(self.keyword_page)
        )
```

3b. `_on_ocr_ready` 中创建处理器与页面（`self._keyword_processor = ...` 与 `self.keyword_page = ...` 在同一处，页面创建在导航注册之前完成，保证 `_init_navigation` 引用存在）。`__init__` 里 `_init_navigation` 之前先调用 `self.keyword_page = self._create_keyword_summary_page()`（页面不依赖引擎，可提前创建；处理器依赖引擎，放 `_on_ocr_ready`）。

```python
    def _create_keyword_summary_page(self) -> QWidget:
        from app.ui.widgets.keyword_summary_page import KeywordSummaryPage
        page = KeywordSummaryPage(self.keyword_set_manager)
        page.extract_requested.connect(self._on_keyword_extract)
        page.export_requested.connect(self.on_keyword_export)
        page.save_set_requested.connect(self._on_keyword_save_set)
        page.manage_sets_requested.connect(self._on_keyword_manage_sets)
        page.cancel_requested.connect(self._on_keyword_cancel)
        page.tree.cell_inspect_requested.connect(self._on_cell_inspect)
        page.inspection.value_edited.connect(self._on_inspection_value_edited)
        return page
```

`__init__` 中（`_init_navigation` 调用前）加：

```python
        from app.utils.keyword_set_manager import KeywordSetManager
        self.keyword_set_manager = KeywordSetManager()
        self.keyword_page = self._create_keyword_summary_page()
        self._keyword_worker = None
        self._keyword_results = []
        self._keyword_processor = None  # _on_ocr_ready 时创建
```

`_on_ocr_ready` 中（BatchProcessor 创建后）加：

```python
        from app.core.keyword_batch_processor import KeywordBatchProcessor
        self._keyword_processor = KeywordBatchProcessor(
            self.pdf_loader, self.ocr_engine, self.config,
            max_workers=self.config.get("batch", {}).get("max_workers", 4))
```

3c. 新方法（追加在 `on_batch_run` 相关方法之后）：

```python
    def _on_keyword_extract(self, keywords: list):
        if self._keyword_worker and self._keyword_worker.isRunning():
            InfoBar.warning(title="提示", content="关键字提取正在进行中",
                            parent=self, duration=2000)
            return
        if getattr(self, "worker", None) and self.worker.isRunning():
            InfoBar.warning(title="提示", content="模板批量识别进行中，请等待完成",
                            parent=self, duration=2000)
            return
        if self._keyword_processor is None:
            InfoBar.error(title="引擎未就绪", content="请等待 OCR 引擎初始化完成",
                          parent=self, duration=3000)
            return
        files = self.file_panel.all_files()
        if not files:
            InfoBar.warning(title="提示", content="请先在文件列表上传 PDF",
                            parent=self, duration=2000)
            return
        self.keyword_page.set_running(True)
        self._keyword_worker = KeywordBatchWorker(self._keyword_processor, files, keywords)
        self._keyword_worker.progress.connect(self.keyword_page.set_progress)
        self._keyword_worker.finished_all.connect(self._on_keyword_done)
        self._keyword_worker.cancelled.connect(self._on_keyword_cancelled)
        self._keyword_worker.start()

    def _on_keyword_done(self, results):
        self._keyword_results = results
        self.keyword_page.set_running(False)
        self.keyword_page.load_results(results)
        self.keyword_page.enable_export(True)
        self.status_label.setText(f"关键字提取完成：{len(results)} 个文件")

    def _on_keyword_cancelled(self):
        self.keyword_page.set_running(False)
        partial = list(getattr(self._keyword_worker, "_completed_results", []) or [])
        if partial:
            self.keyword_page.load_results(partial)
            self.keyword_page.enable_export(True)
        self.status_label.setText("关键字提取已取消")

    def _on_keyword_cancel(self):
        if self._keyword_worker and self._keyword_worker.isRunning():
            self._keyword_worker.cancel()

    def _on_keyword_save_set(self, name: str, keywords: list):
        self.keyword_set_manager.save(name, keywords)
        self.keyword_page.refresh_sets()
        InfoBar.success(title="已保存", content=f"关键字集「{name}」",
                        parent=self, duration=2000)

    def _on_keyword_manage_sets(self):
        from app.ui.widgets.keyword_set_dialog import KeywordSetDialog
        dlg = KeywordSetDialog(self.keyword_set_manager, self)
        dlg.exec()
        if dlg.result_value():
            name, kws = dlg.result_value()
            self.keyword_page.set_combo.setCurrentText(name)
            self.keyword_page.keyword_input.setText("，".join(kws))
        self.keyword_page.refresh_sets()

    def on_keyword_export(self):
        results = self.keyword_page.current_results()
        if not results:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出关键字汇总", "keyword_summary.xlsx", "Excel (*.xlsx)")
        if not path:
            return
        try:
            KeywordExporter().to_excel(results, path)
        except Exception as e:
            InfoBar.error(title="导出失败", content=str(e), parent=self, duration=3000)
            return
        InfoBar.success(title="已导出", content=path, parent=self, duration=3000)

    def _on_cell_inspect(self, file_index: int, page_no: int, keyword: str):
        if file_index < 0 or file_index >= len(self._keyword_results):
            return
        fr = self._keyword_results[file_index]
        if page_no < 1 or page_no > len(fr.pages):
            return
        dpi = int(self.config.get("pdf", {}).get("render_dpi", 200))
        self.keyword_page.inspection._file_index = file_index
        self.keyword_page.inspection.show_inspection(
            fr.source_file, page_no, self.pdf_loader, dpi,
            fr.pages[page_no - 1].cells, keyword)
        self.keyword_page.inspection.setVisible(True)

    def _on_inspection_value_edited(self, file_index, page_no, keyword, new_value):
        if file_index < 0 or file_index >= len(self._keyword_results):
            return
        fr = self._keyword_results[file_index]
        if page_no < 1 or page_no > len(fr.pages):
            return
        cell = fr.pages[page_no - 1].cells.get(keyword)
        if cell is not None:
            cell.value = new_value
            cell.manually_edited = True
        self.keyword_page.tree.load_results(self._keyword_results)  # 刷新树
```

顶部 import 追加：`from app.workers.keyword_batch_worker import KeywordBatchWorker`、`from app.core.keyword_exporter import KeywordExporter`（或方法内 import，与文件既有风格一致——该文件大量方法内 import）。

3d. 互斥守卫：`on_batch_run`（:1618 防重复检查处）追加：

```python
        if self._keyword_worker and self._keyword_worker.isRunning():
            InfoBar.warning(title="提示", content="关键字提取进行中，请等待完成",
                            parent=self, duration=2000)
            return
```

3e. 删除清单（逐项删除后跑测试确认）：

```bash
git rm app/ui/widgets/layout_visualizer.py app/ui/widgets/result_panel.py \
       app/workers/ocr_worker.py
git rm tests/ui/widgets/test_layout_visualizer.py tests/ui/widgets/test_result_panel.py \
       tests/ui/test_two_way_highlight.py
```

main_window.py 内删除（grep 定位后删除代码块，勿动其余）：
- `_layout_view`（LayoutVisualizer 实例）创建与全部接线：`viewport_rect_changed`、`navigate`、`nav_toggle_clicked`、`_on_minimap_navigate`、`_switch_ui_mode` 中 nav_toggle 显隐逻辑
- `self._result_panel` 创建与全部引用（`_result_panel.load_result` 等）
- auto 单页解析：`_on_parse_current_page`、`_on_parse_worker_finished`、`_on_parse_worker_cleanup`、`_on_page_parsed`、`_get_detection_fn`、`ParseWorker`/`StructuredExtractor` 引用、`_on_result_field_selected`、`_on_canvas_bbox_clicked`、`self._current_page_result`、`self._current_page_image`（若仅 auto 用）、`_invalidate_current_result`（若仅 auto 用）
- `_on_toolbar_engine_changed` 中若引用 ResultPanel/auto 逻辑则同步裁剪
- `tests/ui/test_theme_refresh.py`：删除 `assert '#1f2937' in w.right_panel.styleSheet()` 断言（right_panel 已删）；`pdf_canvas`/`field_panel`/`status_bar`/`toolbar` 断言保留
- `tests/ui/integration_test.py`：grep `result_panel|_layout_view|parse_current|ParseWorker` 相关用例，删除或替换为模板模式等价断言

- [ ] **Step 4: 运行确认**

Run:
```bash
venv/Scripts/python.exe -m pytest tests/ui/test_theme_refresh.py tests/ui/test_main_window_new_template.py tests/ui/integration_test.py -q
venv/Scripts/python.exe -m pytest tests/ -q
```
Expected: 全绿（全量 393 - 已删测试数 + 新增）

- [ ] **Step 5: 提交**

```bash
git add -u app/ui/main_window.py tests/ui/test_theme_refresh.py tests/ui/integration_test.py
git commit -m "feat: 主窗口三页导航重组 + 关键字提取/核对/导出接线 + 删除无关组件

删除：layout_visualizer（导航图）/ result_panel（单页视图）/ ocr_worker（ParseWorker）
/ 双向高亮接线。保留：模板模式/批量/历史。

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

### Task 11: 收尾 — 全量回归 + 真实引擎冒烟 + 文档

**Files:**
- Modify: `docs/superpowers/specs/2026-08-01-keyword-summary-redesign.md`（若实现与 spec 有偏差，更新之）

**Interfaces:**
- 无新接口；验证全部已实现组件

- [ ] **Step 1: 全量回归**

Run: `venv/Scripts/python.exe -m pytest tests/ -q`
Expected: 全绿（无失败；跳过数允许 1）

- [ ] **Step 2: 真实引擎冒烟（需要 llama-server，用户环境已具备）**

```bash
cd C:\Users\Panda\OneDrive\panda\tools\PDFOCR
venv/Scripts/python.exe main.py
```
人工验证（对照计划验证手册）：
1. 侧边导航三页：单据处理 | 关键字汇总 | 历史记录；模板框选/批量识别工作正常（RapidOCR）
2. 关键字汇总页：上传 2-3 张真实发票/报关单 PDF → 输入"报关单号,价税合计,发票号码" → 提取 → 汇总树按文件分组折叠、列头命中率徽标（含 ⚠ 低命中列）
3. 双击待确认单元格 → 核对面板滑出：渲染该页、提取区域高亮（PDF 文本层）、该页单元格表
4. 双击值修改 → 蓝底人工修正标记；导出 Excel → 打开验证每页一行
5. 关键字集：保存/加载/管理对话框；明暗主题切换 → 状态底色跟随
6. 无文本层 PDF → 核对只渲染不高亮不崩溃

- [ ] **Step 3: 更新文档**

若冒烟发现 spec/计划与实际实现的偏差（如 PdfCanvas 构造签名、InfoBar 参数），修正对应文档并记录偏差。

- [ ] **Step 4: 最终提交（若有文档/代码修正）**

```bash
git add <本次修正的明确路径>
git commit -m "fix: 冒烟修正 — <说明>

Co-Authored-By: Claude <noreply@anthropic.com>"
```

- [ ] **Step 5: 更新 HANDOFF.md**

在 HANDOFF.md 顶部追加完成摘要（本主题化重设计已完成的说明 + 冒烟结果 + deferred 项：关键字结果进历史记录、校验委托 FinanceProcessor 接入汇总表、关键字集导入/导出文件）。

```

