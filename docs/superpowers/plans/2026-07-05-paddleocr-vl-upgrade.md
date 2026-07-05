# PaddleOCR-VL 1.6 升级实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 将 PDFOCR 从单一 RapidOCR 引擎升级为以 PaddleOCR-VL-1.6 GPU 为中心的双引擎架构，支持全局切换。

**Architecture:** 抽象基类 OCREngineBase → RapidOCREngine / PaddleOCREngine 双实现 → 工厂函数 get_ocr_engine()。PaddleOCR-VL 模式走整页识别 + FieldMatcher 三级匹配；RapidOCR 模式保持逐区域裁剪。双 venv 隔离（GPU 主环境 + CPU 备用）。

**Tech Stack:** Python 3.12.7, PyQt6, qfluentwidgets, PaddleOCR-VL-1.6-0.9B (PaddlePaddle GPU 3.2.1), RapidOCR (ONNX Runtime)

**Hardware:** NVIDIA GeForce RTX 5060 Laptop GPU (8151 MiB, ~7123 MiB free)

## Global Constraints

- 现有 RapidOCR 功能完整保留，识别行为不变
- 配置文件 `config.yaml` 向后兼容（新增字段有默认值）
- 旧模板（无 `match_keywords`）正常使用 Level 1+2 匹配
- Python 3.12.7，所有依赖兼容该版本
- PaddlePaddle CUDA 12.6 wheel（系统 CUDA 13.3 但 PaddlePaddle 自带运行时）
- 引擎初始化在后台线程，不阻塞 GUI

---

### 里程碑 1：数据基础层

### Task 1: 增强数据模型

**Files:**
- Modify: `app/models/ocr_result.py`
- Modify: `app/models/region.py`

**Interfaces:**
- Produces: `FieldResult.match_level: int = 0`, `FieldResult.engine: str = ""`
- Produces: `Region.match_keywords: List[str] = field(default_factory=list)`, `Region.match_mode: str = "value"`

- [ ] **Step 1: 修改 FieldResult**

```python
# app/models/ocr_result.py — 完整替换
from dataclasses import dataclass, field
from typing import Dict


@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    manually_edited: bool = False
    match_level: int = 0     # 0=未匹配 1=IoU精确 2=就近搜索 3=关键词兜底
    engine: str = ""         # "rapidocr" | "paddleocr_vl"


@dataclass
class FileResult:
    source_file: str
    fields: Dict[str, FieldResult]
    success: bool = True
    error_msg: str = ""
```

- [ ] **Step 2: 修改 Region**

```python
# app/models/region.py — 在现有基础上增加两个可选字段
from dataclasses import dataclass, field
from typing import Literal, List

@dataclass
class Region:
    """框选区域数据模型（坐标使用归一化 0~1 比例）"""
    id: str
    field_name: str
    x: float
    y: float
    w: float
    h: float
    field_type: Literal["text", "number", "date", "email", "phone"] = "text"
    ocr_mode: Literal["general", "single_line", "number"] = "general"
    color: str = "#FF5733"
    # PaddleOCR-VL 专属（可选，向后兼容）
    match_keywords: List[str] = field(default_factory=list)
    match_mode: str = "value"  # "exact" | "label_value"

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "Region":
        return cls(**data)
```

注意：`to_dict()` 和 `from_dict()` 保持不变，因为 `self.__dict__.copy()` 自动包含新字段。

- [ ] **Step 3: 验证**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.models.ocr_result import FieldResult, FileResult
from app.models.region import Region

# 测试旧构造方式仍然工作
fr = FieldResult(field_name='test', text='hello', confidence=0.9)
assert fr.match_level == 0
assert fr.engine == ''

# 测试新字段
fr2 = FieldResult(field_name='test', text='hello', confidence=0.9, match_level=1, engine='paddleocr_vl')
assert fr2.match_level == 1

# 测试 Region 向后兼容
r = Region(id='1', field_name='发票号码', x=0.1, y=0.2, w=0.3, h=0.05)
assert r.match_keywords == []
assert r.match_mode == 'value'

# 测试 Region 新字段
r2 = Region(id='2', field_name='发票号码', x=0.1, y=0.2, w=0.3, h=0.05,
            match_keywords=['发票号码', 'No.'], match_mode='label_value')
assert r2.match_keywords == ['发票号码', 'No.']

print('All tests passed')
"
```

- [ ] **Step 4: Commit**

```bash
git add app/models/ocr_result.py app/models/region.py
git commit -m "feat: enhance data models with match_level, engine, match_keywords fields"
```

---

### Task 2: 增强配置加载器

**Files:**
- Modify: `app/utils/config_loader.py`
- Modify: `config.yaml`

**Interfaces:**
- Produces: `get_default_config()` 返回包含完整 `paddleocr_vl` 和 `rapidocr` 配置段的 dict

- [ ] **Step 1: 更新 get_default_config()**

将 [config_loader.py:48-74](app/utils/config_loader.py#L48-L74) 的 `get_default_config()` 中的 `"ocr"` 段替换为：

```python
def get_default_config() -> dict:
    """返回默认配置"""
    return {
        "app": {
            "name": "PDF OCR Tool",
            "version": "2.0.0",
            "window_size": [1600, 1000]
        },
        "pdf": {
            "render_dpi": 200
        },
        "ocr": {
            "engine": "paddleocr_vl",       # "paddleocr_vl" | "rapidocr"
            "lang": "ch",
            "use_gpu": True,
            "use_angle_cls": True,
            "det_db_box_thresh": 0.5,
            "drop_score": 0.5,
            # PaddleOCR-VL 专属
            "paddleocr_vl": {
                "model_name": "PaddleOCR-VL-1.6-0.9B",
                "device": "gpu",
                "warmup_on_startup": True,
                "idle_unload_seconds": 300,
                "backend": "paddle",
                "page_dpi": 200,
                "high_quality_dpi": 300,
                "match_iou_threshold": 0.5,
                "match_neighbor_radius": 50,
            },
            # RapidOCR 专属
            "rapidocr": {
                "use_gpu": False,
                "lang": "ch",
                "det_db_box_thresh": 0.3,
                "drop_score": 0.5,
            },
        },
        "batch": {
            "max_workers": 4,
            "retry_times": 2
        },
        "export": {
            "default_format": "xlsx",
            "include_confidence": True
        }
    }
```

- [ ] **Step 2a: 在 load_config 中读取 PDFOCR_ENGINE 环境变量**

在 `load_config()` 函数返回前添加环境变量覆盖逻辑（`get_default_config()` 之后、`return` 之前）：

```python
def load_config(path: str = None) -> dict:
    # ... (现有逻辑) ...

    config = yaml.safe_load(f) if config_path.exists() else get_default_config()

    # 启动器环境变量覆盖（优先级高于配置文件）
    import os
    env_engine = os.environ.get("PDFOCR_ENGINE", "")
    if env_engine in ("paddleocr_vl", "rapidocr"):
        config.setdefault("ocr", {})["engine"] = env_engine

    return config
```

- [ ] **Step 2: 更新 config.yaml**

在现有的 `config.yaml` 中添加新字段（如果存在），或创建新配置文件。

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.utils.config_loader import load_config, get_default_config
import json
# 验证默认配置包含所有新字段
c = get_default_config()
assert 'paddleocr_vl' in c['ocr']
assert 'rapidocr' in c['ocr']
assert c['ocr']['paddleocr_vl']['match_iou_threshold'] == 0.5
print('Config defaults OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/utils/config_loader.py config.yaml
git commit -m "feat: add PaddleOCR-VL and RapidOCR config sections with defaults"
```

---

### 里程碑 2：引擎抽象层

### Task 3: 创建抽象基类

**Files:**
- Create: `app/core/ocr_engine_base.py`

**Interfaces:**
- Produces: `OCREngineBase(ABC)` — `initialize()`, `recognize(image, mode) -> (str, float)`, `recognize_page(image, regions, page_dpi) -> Dict[str, Tuple[str, float, int, dict]]`, `unload()`, `is_ready: bool`, `engine_name: str`

- [ ] **Step 1: 创建 ocr_engine_base.py**

```python
"""
OCR引擎抽象基类
定义所有OCR引擎必须实现的接口
"""
from abc import ABC, abstractmethod
from typing import Tuple, Dict, List, Any
from PIL import Image


class OCREngineBase(ABC):
    """OCR引擎抽象基类 — 所有引擎必须实现此接口"""

    @abstractmethod
    def initialize(self) -> None:
        """
        同步初始化引擎，加载模型。
        在后台线程中调用，不阻塞UI。
        调用后 is_ready 应为 True。
        """
        ...

    @abstractmethod
    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """
        识别单张图片。

        Args:
            image: PIL Image对象（可能是裁剪后的区域）
            mode: "general" | "single_line" | "number"

        Returns:
            (识别的文本, 平均置信度 0.0~1.0)
        """
        ...

    @abstractmethod
    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        识别整页图片的多个区域。

        Args:
            image: 整页渲染的PIL Image
            regions: Region对象列表
            page_dpi: 页面渲染DPI

        Returns:
            {region_id: (text, confidence, match_level, raw_element)}
            match_level: 0=未匹配 1=IoU 2=就近 3=关键词
            raw_element: PaddleOCR-VL返回的原始element dict（RapidOCR为None）
        """
        ...

    @property
    @abstractmethod
    def is_ready(self) -> bool:
        """引擎是否已初始化完成"""
        ...

    @property
    @abstractmethod
    def engine_name(self) -> str:
        """引擎名称: "rapidocr" | "paddleocr_vl" """
        ...

    @abstractmethod
    def unload(self) -> None:
        """卸载模型释放资源（PaddleOCR-VL 需要，RapidOCR可为空操作）"""
        ...
```

- [ ] **Step 2: 验证语法正确**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.ocr_engine_base import OCREngineBase
print('OCREngineBase imported OK')
# 验证不能直接实例化
try:
    OCREngineBase()
    assert False, 'Should not instantiate'
except TypeError:
    print('Abstract class correctly prevents instantiation')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine_base.py
git commit -m "feat: add OCREngineBase abstract class"
```

---

### Task 4: 重构 RapidOCR 引擎

**Files:**
- Create: `app/core/ocr_engine_rapid.py` （从 `ocr_engine.py` 迁移代码）
- Modify: `app/core/ocr_engine.py` （暂时不动，Task 5 处理）

**Interfaces:**
- Produces: `RapidOCREngine(OCREngineBase)` — 现有 `OCREngine` 逻辑迁入，实现基类接口

- [ ] **Step 1: 创建 ocr_engine_rapid.py**

将现有 [ocr_engine.py](app/core/ocr_engine.py) 的全部代码复制到 `ocr_engine_rapid.py`，然后做以下改动：

1. 类名 `OCREngine` → `RapidOCREngine`（全文替换）
2. 继承 `OCREngineBase`
3. 添加 `engine_name` 属性返回 `"rapidocr"`
4. 添加 `recognize_page()` 方法（循环调用 `recognize()`）
5. 添加 `unload()` 方法（空操作）
6. 移除线程相关功能（`initialize_async`、`_init_future`），统一用 `initialize()`（=`initialize_sync`）

```python
"""
RapidOCR引擎 — 基于 ONNX Runtime 的轻量级OCR
线程安全的单例模式
"""
from typing import Optional, Tuple, Dict, List, Any
from PIL import Image
import numpy as np
import threading
from app.core.ocr_engine_base import OCREngineBase
from app.utils.image_utils import preprocess_for_ocr


class RapidOCREngine(OCREngineBase):
    """
    RapidOCR引擎 — 线程安全单例

    基于 RapidOCR (ONNX Runtime)，CPU运行，无需GPU。
    逐区域裁剪后识别。
    """
    _instance: Optional['RapidOCREngine'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, lang: str = "ch", use_gpu: bool = False, use_angle_cls: bool = True):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return
            self._ocr = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._ocr_lock = threading.RLock()
            self._lang = lang
            self._use_gpu = use_gpu
            self._use_angle_cls = use_angle_cls
            self._initialized_flag = True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用）"""
        if self._initialized:
            return
        with self._ocr_lock:
            if self._initialized:
                return
            try:
                from rapidocr_onnxruntime import RapidOCR
                self._ocr = RapidOCR()
                self._initialized = True
                self._warmup()
            except Exception as e:
                self._init_error = str(e)

    def _warmup(self) -> None:
        if not self._ocr:
            return
        try:
            dummy_img = np.zeros((10, 10, 3), dtype=np.uint8)
            self._ocr(dummy_img)
        except Exception:
            pass

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "rapidocr"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def unload(self) -> None:
        """RapidOCR无需显式卸载"""
        pass

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        if not self._initialized:
            if self._init_error:
                raise RuntimeError(f"OCR引擎初始化失败: {self._init_error}")
            raise RuntimeError("OCR引擎未初始化")

        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)

        with self._ocr_lock:
            if self._ocr is None:
                raise RuntimeError("OCR引擎未正确初始化")
            result, elapse = self._ocr(arr)

        if result is None or len(result) == 0:
            return "", 0.0

        lines = []
        confidences = []
        for line in result:
            text, conf = line[1], line[2]
            lines.append(text)
            confidences.append(conf)

        merged = " ".join(lines) if mode == "single_line" else "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return merged, avg_conf

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """逐区域裁剪后识别（保持现有行为）"""
        results = {}
        W, H = image.size
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            if right <= left or bottom <= top:
                crop = Image.new("RGB", (1, 1), (255, 255, 255))
            else:
                crop = image.crop((left, top, right, bottom))
            text, conf = self.recognize(crop, region.ocr_mode)
            results[region.id] = (text, conf, 0, None)
        return results

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance = None
```

- [ ] **Step 2: 验证 RapidOCR 引擎**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.ocr_engine_rapid import RapidOCREngine
engine = RapidOCREngine()
assert engine.engine_name == 'rapidocr'
assert not engine.is_ready
engine.initialize()
assert engine.is_ready
print('RapidOCREngine OK')

# 测试 recognize
from PIL import Image
img = Image.new('RGB', (100, 30), 'white')
text, conf = engine.recognize(img)
assert isinstance(text, str)
assert isinstance(conf, float)
print(f'Recognize OK: text={repr(text)}, conf={conf}')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine_rapid.py
git commit -m "refactor: extract RapidOCREngine from OCREngine, implement OCREngineBase"
```

---

### Task 5: 创建工厂函数 + 向后兼容层

**Files:**
- Modify: `app/core/ocr_engine.py` （重写为工厂函数）

**Interfaces:**
- Produces: `get_ocr_engine(config: dict) -> OCREngineBase`
- Produces: `OCREngine = get_ocr_engine` （向后兼容别名）
- Consumes: `RapidOCREngine` from Task 4

- [ ] **Step 1: 重写 ocr_engine.py**

```python
"""
OCR引擎工厂 — 根据配置返回对应引擎实例
"""
from typing import Optional
from app.core.ocr_engine_base import OCREngineBase


def get_ocr_engine(config: dict) -> OCREngineBase:
    """
    根据配置创建OCR引擎实例。

    config["ocr"]["engine"]:
        "paddleocr_vl" → PaddleOCREngine（GPU，主引擎）
        "rapidocr"     → RapidOCREngine（CPU，降级备用）

    如果 PaddleOCREngine 导入失败（环境未安装PaddlePaddle），
    自动降级到 RapidOCREngine。
    """
    engine_type = config.get("ocr", {}).get("engine", "rapidocr")

    if engine_type == "paddleocr_vl":
        try:
            from app.core.ocr_engine_paddle import PaddleOCREngine
            return PaddleOCREngine(config)
        except ImportError as e:
            import logging
            logging.getLogger("PDFOCR").warning(
                f"PaddleOCR-VL不可用 ({e})，降级到RapidOCR"
            )
            # 自动降级
            from app.core.ocr_engine_rapid import RapidOCREngine
            ocr_config = config.get("ocr", {})
            rapid_config = ocr_config.get("rapidocr", {})
            return RapidOCREngine(
                lang=rapid_config.get("lang", "ch"),
                use_gpu=rapid_config.get("use_gpu", False),
            )

    # 默认使用 RapidOCR
    from app.core.ocr_engine_rapid import RapidOCREngine
    ocr_config = config.get("ocr", {})
    rapid_config = ocr_config.get("rapidocr", {})
    return RapidOCREngine(
        lang=rapid_config.get("lang", "ch"),
        use_gpu=rapid_config.get("use_gpu", False),
    )


# 向后兼容别名
# 旧代码: from app.core.ocr_engine import OCREngine; OCREngine(lang=..., use_gpu=...)
# 新代码: from app.core.ocr_engine import get_ocr_engine; engine = get_ocr_engine(config)
OCREngine = get_ocr_engine
```

- [ ] **Step 2: 验证工厂函数**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.ocr_engine import get_ocr_engine
from app.utils.config_loader import get_default_config

config = get_default_config()
config['ocr']['engine'] = 'rapidocr'

engine = get_ocr_engine(config)
assert engine.engine_name == 'rapidocr'
engine.initialize()
assert engine.is_ready
print('Factory with RapidOCR OK')

# 测试 PaddleOCR-VL 不可用时的降级
config['ocr']['engine'] = 'paddleocr_vl'
engine2 = get_ocr_engine(config)
# 因为当前venv没有PaddlePaddle，应该自动降级
assert engine2.engine_name == 'rapidocr'
print('Graceful degradation OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine.py
git commit -m "refactor: replace OCREngine class with factory function + backward compat alias"
```

---

### 里程碑 3：PaddleOCR-VL 引擎

### Task 6: 创建 FieldMatcher 三级匹配引擎

**Files:**
- Create: `app/core/field_matcher.py`

**Interfaces:**
- Produces: `FieldMatcher(config)` — `match(elements, regions) -> Dict[str, MatchResult]`
- Produces: `MatchResult = namedtuple('MatchResult', ['text', 'confidence', 'level', 'element'])`

- [ ] **Step 1: 创建 field_matcher.py**

```python
"""
字段匹配引擎 — PaddleOCR-VL 核心
将VLM返回的elements匹配到用户定义的regions

三级策略：
  Level 1: IoU精确匹配（element bbox与region bbox）
  Level 2: 就近搜索（在region周围搜索最近elements，合并相邻）
  Level 3: 关键词正则兜底（在markdown中搜索match_keywords）
"""
from typing import List, Dict, Optional, Tuple, Any
from collections import namedtuple

MatchResult = namedtuple('MatchResult', ['text', 'confidence', 'level', 'element'])


class FieldMatcher:
    """将PaddleOCR-VL elements匹配到用户regions"""

    def __init__(self, config: dict):
        vl_cfg = config.get("ocr", {}).get("paddleocr_vl", {})
        self.iou_threshold = vl_cfg.get("match_iou_threshold", 0.5)
        self.neighbor_radius = vl_cfg.get("match_neighbor_radius", 50)

    def match(self, elements: List[dict], regions: List[Any],
              markdown_text: str = "") -> Dict[str, MatchResult]:
        """
        主匹配方法。

        Args:
            elements: PaddleOCR-VL返回的elements列表
            regions: 用户定义的Region列表
            markdown_text: 整页markdown文本（用于Level 3兜底）

        Returns:
            {region.id: MatchResult(text, confidence, level, element)}
        """
        results: Dict[str, MatchResult] = {}
        remaining = list(elements)  # 可消耗的element池

        for region in regions:
            # Level 1: IoU匹配
            best = self._iou_match(region, remaining)
            if best is not None:
                remaining.remove(best)
                results[region.id] = MatchResult(
                    text=best.get("text", ""),
                    confidence=best.get("confidence", 0.0),
                    level=1,
                    element=best,
                )
                continue

            # Level 2: 就近搜索
            best = self._neighbor_match(region, remaining)
            if best is not None:
                remaining.remove(best)
                text = self._merge_adjacent(best, region, remaining)
                results[region.id] = MatchResult(
                    text=text,
                    confidence=best.get("confidence", 0.0),
                    level=2,
                    element=best,
                )
                continue

            # Level 3: 关键词兜底
            text, conf = self._keyword_match(region, markdown_text)
            if text:
                results[region.id] = MatchResult(
                    text=text, confidence=conf, level=3, element=None,
                )
                continue

            # 未匹配
            results[region.id] = MatchResult(
                text="", confidence=0.0, level=0, element=None,
            )

        return results

    def _calculate_iou(self, box_a: List[float], box_b: List[float]) -> float:
        """计算两个bbox的IoU (Intersection over Union)"""
        xa1, ya1, xa2, ya2 = box_a
        xb1, yb1, xb2, yb2 = box_b

        xi1 = max(xa1, xb1)
        yi1 = max(ya1, yb1)
        xi2 = min(xa2, xb2)
        yi2 = min(ya2, yb2)

        if xi2 <= xi1 or yi2 <= yi1:
            return 0.0

        inter = (xi2 - xi1) * (yi2 - yi1)
        area_a = (xa2 - xa1) * (ya2 - ya1)
        area_b = (xb2 - xb1) * (yb2 - yb1)
        union = area_a + area_b - inter

        return inter / union if union > 0 else 0.0

    def _iou_match(self, region, elements: List[dict]) -> Optional[dict]:
        """Level 1: 找到与region IoU最高的element"""
        # region的归一化坐标需要转换为像素坐标（由调用者在传入elements前处理好）
        # 这里region bbox和element bbox应该已经在同一坐标系（像素）
        best_iou = 0.0
        best_elem = None
        for elem in elements:
            elem_bbox = elem.get("bbox")
            if not elem_bbox or len(elem_bbox) != 4:
                continue
            iou = self._calculate_iou(region._pixel_bbox, elem_bbox)
            if iou > best_iou:
                best_iou = iou
                best_elem = elem
        if best_iou >= self.iou_threshold and best_elem is not None:
            return best_elem
        return None

    def _neighbor_match(self, region, elements: List[dict]) -> Optional[dict]:
        """Level 2: 在region周围搜索最近的element"""
        if not elements:
            return None
        rx, ry, rw, rh = region._pixel_bbox
        rcx, rcy = rx + rw / 2, ry + rh / 2

        best_dist = float('inf')
        best_elem = None
        for elem in elements:
            bbox = elem.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            ecx = (bbox[0] + bbox[2]) / 2
            ecy = (bbox[1] + bbox[3]) / 2
            dist = ((rcx - ecx) ** 2 + (rcy - ecy) ** 2) ** 0.5
            if dist < best_dist and dist <= self.neighbor_radius:
                best_dist = dist
                best_elem = elem
        return best_elem

    def _merge_adjacent(self, best: dict, region, remaining: List[dict]) -> str:
        """合并与best相邻的同一行elements"""
        texts = [best.get("text", "")]
        best_bbox = best.get("bbox", [0, 0, 0, 0])
        by_mid = (best_bbox[1] + best_bbox[3]) / 2

        for elem in list(remaining):
            bbox = elem.get("bbox")
            if not bbox or len(bbox) != 4:
                continue
            ey_mid = (bbox[1] + bbox[3]) / 2
            # 同一行（y中点接近）且在附近
            if abs(ey_mid - by_mid) < 20:
                h_dist = bbox[0] - best_bbox[2]
                if 0 < h_dist < self.neighbor_radius * 2:
                    texts.append(elem.get("text", ""))
        return " ".join(texts)

    def _keyword_match(self, region, markdown_text: str) -> Tuple[str, float]:
        """Level 3: 在markdown中用关键词正则搜索"""
        import re
        if not markdown_text or not region.match_keywords:
            return "", 0.0

        for kw in region.match_keywords:
            # 匹配 "关键词：值" 或 "关键词: 值"
            pattern = re.escape(kw) + r'[：:\s]*(\S+)'
            m = re.search(pattern, markdown_text)
            if m:
                return m.group(1), 0.5  # 关键词兜底置信度设为0.5

        return "", 0.0
```

- [ ] **Step 2: 验证 FieldMatcher**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.field_matcher import FieldMatcher
from app.utils.config_loader import get_default_config

config = get_default_config()
matcher = FieldMatcher(config)
assert matcher.iou_threshold == 0.5
assert matcher.neighbor_radius == 50

# 测试IoU计算
iou = matcher._calculate_iou([0, 0, 100, 100], [50, 50, 150, 150])
assert 0.13 < iou < 0.15, f'Expected ~0.14, got {iou}'

# 测试完全重叠
iou = matcher._calculate_iou([0, 0, 100, 100], [0, 0, 100, 100])
assert iou == 1.0, f'Expected 1.0, got {iou}'

print('FieldMatcher OK')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/core/field_matcher.py
git commit -m "feat: add FieldMatcher with 3-level coordinate-to-field matching"
```

---

### Task 7: 创建 PaddleOCR-VL 引擎

**Files:**
- Create: `app/core/ocr_engine_paddle.py`

**Interfaces:**
- Consumes: `OCREngineBase` from Task 3, `FieldMatcher` from Task 6
- Produces: `PaddleOCREngine(OCREngineBase)` — GPU加速的全功能引擎

- [ ] **Step 1: 创建 ocr_engine_paddle.py**

```python
"""
PaddleOCR-VL 引擎 — 基于视觉语言模型的智能OCR
GPU加速，整页理解，支持表格/手写/公式
"""
from typing import Optional, Tuple, Dict, List, Any
from PIL import Image
import threading
import time
from app.core.ocr_engine_base import OCREngineBase
from app.core.field_matcher import FieldMatcher


class PaddleOCREngine(OCREngineBase):
    """
    PaddleOCR-VL引擎 — 单例

    特性:
    - 整页识别: 一次推理获取全页结构化结果
    - 三级匹配: IoU → 就近 → 关键词
    - GPU常驻: 模型加载后保持常驻，避免重复加载
    - 空闲卸载: 可配置空闲N秒后自动释放GPU显存
    """
    _instance: Optional['PaddleOCREngine'] = None
    _lock = threading.Lock()

    def __new__(cls, *args, **kwargs):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config: dict):
        if hasattr(self, "_initialized_flag"):
            return
        with self.__class__._lock:
            if hasattr(self, "_initialized_flag"):
                return
            self._config = config
            vl_cfg = config.get("ocr", {}).get("paddleocr_vl", {})
            self._pipeline = None
            self._initialized = False
            self._init_error: Optional[str] = None
            self._lock = threading.RLock()
            self._model_name = vl_cfg.get("model_name", "PaddleOCR-VL-1.6-0.9B")
            self._device = vl_cfg.get("device", "gpu")
            self._warmup_on_startup = vl_cfg.get("warmup_on_startup", True)
            self._idle_unload_seconds = vl_cfg.get("idle_unload_seconds", 300)
            self._page_dpi = vl_cfg.get("page_dpi", 200)
            self._matcher = FieldMatcher(config)
            self._last_used_time = time.time()
            self._initialized_flag = True

    def initialize(self) -> None:
        """同步初始化（在后台线程中调用，不阻塞GUI）"""
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            try:
                from paddleocr import PaddleOCRVL
                self._pipeline = PaddleOCRVL(model_name=self._model_name)
                self._initialized = True
                self._last_used_time = time.time()

                # 启动预热
                if self._warmup_on_startup:
                    self._warmup()

            except Exception as e:
                self._init_error = str(e)

    def _warmup(self) -> None:
        """预热模型 — 用小图跑一次推理触发CUDA kernel编译"""
        if not self._pipeline:
            return
        try:
            dummy = Image.new("RGB", (64, 64), "white")
            list(self._pipeline.predict(dummy))
        except Exception:
            pass  # 预热失败不影响正常使用

    @property
    def is_ready(self) -> bool:
        return self._initialized

    @property
    def engine_name(self) -> str:
        return "paddleocr_vl"

    @property
    def init_error(self) -> str:
        return self._init_error or ""

    def unload(self) -> None:
        """卸载GPU模型释放显存"""
        with self._lock:
            if self._pipeline is not None:
                del self._pipeline
                self._pipeline = None
                self._initialized = False

    def _ensure_loaded(self) -> None:
        """确保模型已加载（支持空闲后重新加载）"""
        if not self._initialized:
            self.initialize()
        if not self._initialized:
            raise RuntimeError(f"PaddleOCR-VL初始化失败: {self._init_error}")
        self._last_used_time = time.time()

    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]:
        """单图识别 — 降级为整页识别后只取第一个匹配"""
        # 创建虚拟region覆盖全图
        class _DummyRegion:
            id = "__single__"
            field_name = "text"
            _pixel_bbox = [0, 0, image.width, image.height]
            match_keywords = []
            match_mode = "value"
            ocr_mode = mode

        results = self.recognize_page(image, [_DummyRegion])
        result = results.get("__single__", ("", 0.0, 0, None))
        return result[0], result[1]

    def recognize_page(
        self, image: Image.Image, regions: List[Any], page_dpi: float = 200
    ) -> Dict[str, Tuple[str, float, int, Any]]:
        """
        整页识别 — PaddleOCR-VL一次推理，FieldMatcher匹配到各region
        """
        self._ensure_loaded()

        # 预处理：为每个region计算像素坐标bbox
        W, H = image.size
        for region in regions:
            left = max(0, int(region.x * W))
            top = max(0, int(region.y * H))
            right = min(W, int((region.x + region.w) * W))
            bottom = min(H, int((region.y + region.h) * H))
            region._pixel_bbox = [left, top, right, bottom]

        try:
            with self._lock:
                outputs = list(self._pipeline.predict(image))
        except Exception as e:
            # 推理失败，返回空结果
            return {r.id: ("", 0.0, 0, None) for r in regions}

        if not outputs:
            return {r.id: ("", 0.0, 0, None) for r in regions}

        # 提取elements和markdown
        output = outputs[0] if isinstance(outputs, list) else outputs
        elements = self._extract_elements(output)
        markdown_text = self._extract_markdown(output)

        # 三级匹配
        match_results = self._matcher.match(elements, regions, markdown_text)

        # 转换为统一格式
        results = {}
        for region in regions:
            mr = match_results.get(region.id)
            if mr:
                results[region.id] = (mr.text, mr.confidence, mr.level, mr.element)
            else:
                results[region.id] = ("", 0.0, 0, None)

        self._last_used_time = time.time()
        return results

    def _extract_elements(self, output) -> List[dict]:
        """从PaddleOCR-VL输出提取elements列表"""
        if hasattr(output, 'elements'):
            elements = []
            for elem in output.elements:
                elem_dict = {
                    "type": getattr(elem, "type", "text"),
                    "text": getattr(elem, "text", ""),
                    "confidence": getattr(elem, "confidence", 0.0),
                }
                bbox = getattr(elem, "bbox", None)
                if bbox is not None:
                    if hasattr(bbox, 'tolist'):
                        bbox = bbox.tolist()
                    elem_dict["bbox"] = list(bbox)
                elements.append(elem_dict)
            return elements
        elif isinstance(output, dict):
            return output.get("elements", [])
        return []

    def _extract_markdown(self, output) -> str:
        """从PaddleOCR-VL输出提取markdown文本"""
        if hasattr(output, 'markdown'):
            return str(output.markdown)
        elif isinstance(output, dict):
            return output.get("markdown", "")
        return ""

    def get_vram_usage(self) -> Tuple[float, float]:
        """获取GPU显存使用 (used_gb, total_gb) - 需要pynvml"""
        try:
            import pynvml
            pynvml.nvmlInit()
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            info = pynvml.nvmlDeviceGetMemoryInfo(handle)
            return info.used / 1024**3, info.total / 1024**3
        except Exception:
            return 0.0, 0.0

    def _check_idle_unload(self) -> None:
        """检查是否需要空闲卸载（由定时器调用）"""
        if self._idle_unload_seconds <= 0:
            return
        if not self._initialized:
            return
        elapsed = time.time() - self._last_used_time
        if elapsed > self._idle_unload_seconds:
            self.unload()

    @classmethod
    def reset_instance(cls) -> None:
        with cls._lock:
            if cls._instance is not None:
                cls._instance.unload()
                cls._instance = None
```

- [ ] **Step 2: 验证语法（PaddlePaddle未安装时验证降级逻辑）**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
# 测试导入（当前环境无PaddlePaddle，但文件应能正常导入）
# 因为导入PaddleOCRVL只在initialize()中延迟执行
from app.core.ocr_engine_paddle import PaddleOCREngine
from app.utils.config_loader import get_default_config

config = get_default_config()
try:
    engine = PaddleOCREngine(config)
    assert engine.engine_name == 'paddleocr_vl'
    assert not engine.is_ready
    print('PaddleOCREngine created OK (not initialized)')
except Exception as e:
    print(f'Error: {e}')
"
```

- [ ] **Step 3: Commit**

```bash
git add app/core/ocr_engine_paddle.py
git commit -m "feat: add PaddleOCREngine with GPU-accelerated full-page recognition"
```

---

### 里程碑 4：核心流程集成

### Task 8: 重构 BatchProcessor 支持双引擎分支

**Files:**
- Modify: `app/core/batch_processor.py`

**Interfaces:**
- Consumes: `OCREngineBase.recognize_page()`, `OCREngineBase.engine_name`
- Modifies: `process_one()` — 根据引擎类型分支 `_process_vl` / `_process_rapid`

- [ ] **Step 1: 重构 BatchProcessor**

将 [batch_processor.py:60-108](app/core/batch_processor.py#L60-L108) 的 `process_one()` 方法替换为：

```python
def process_one(self, pdf_path: str, template: Template) -> FileResult:
    """
    处理单个PDF文件 — 根据引擎类型自动选择处理路径

    PaddleOCR-VL: 整页识别 + FieldMatcher匹配
    RapidOCR:     逐区域裁剪识别（原有逻辑）
    """
    try:
        fields = {}
        regions_by_page: Dict[int, list] = {}
        for region in template.regions:
            page_num = getattr(region, 'page_num', 0)
            if page_num not in regions_by_page:
                regions_by_page[page_num] = []
            regions_by_page[page_num].append(region)

        use_vl = self.ocr.engine_name == "paddleocr_vl"

        for page_num, regions in regions_by_page.items():
            rendered_image = self._get_rendered_page(pdf_path, page_num)

            if use_vl:
                # PaddleOCR-VL: 整页一次推理
                page_results = self.ocr.recognize_page(
                    rendered_image, regions,
                    page_dpi=self.config.get("ocr", {}).get("paddleocr_vl", {}).get("page_dpi", 200)
                )
                for region in regions:
                    text, conf, match_level, _ = page_results.get(
                        region.id, ("", 0.0, 0, None)
                    )
                    fields[region.field_name] = FieldResult(
                        field_name=region.field_name,
                        text=text,
                        confidence=conf,
                        match_level=match_level,
                        engine="paddleocr_vl",
                    )
            else:
                # RapidOCR: 逐区域裁剪识别
                W, H = rendered_image.size
                for region in regions:
                    left = max(0, int(region.x * W))
                    top = max(0, int(region.y * H))
                    right = min(W, int((region.x + region.w) * W))
                    bottom = min(H, int((region.y + region.h) * H))
                    if right <= left or bottom <= top:
                        crop = Image.new("RGB", (1, 1), (255, 255, 255))
                    else:
                        crop = rendered_image.crop((left, top, right, bottom))
                    text, conf = self.ocr.recognize(crop, region.ocr_mode)
                    fields[region.field_name] = FieldResult(
                        field_name=region.field_name,
                        text=text,
                        confidence=conf,
                        engine="rapidocr",
                    )

        return FileResult(source_file=pdf_path, fields=fields, success=True)

    except Exception as e:
        return FileResult(source_file=pdf_path, fields={}, success=False, error_msg=str(e))
```

同时在 `BatchProcessor.__init__` 中添加 `config` 参数：

```python
def __init__(self, pdf_loader: PdfLoader, ocr_engine, config: dict, max_workers: int = 4):
    self.pdf_loader = pdf_loader
    self.ocr = ocr_engine
    self.max_workers = max_workers
    self.config = config  # 新增：用于获取page_dpi等配置
    self._page_cache: Dict[str, Image.Image] = {}
    self._page_cache_lock = threading.Lock()
```

**MainWindow 中需要同步更新 BatchProcessor 构造**（Task 11 Step 1 中处理）：

```python
self.processor = BatchProcessor(
    self.pdf_loader, self.ocr_engine,
    self.config,  # 新增参数
    max_workers=self.config["batch"]["max_workers"]
)
```

- [ ] **Step 2: Commit**

```bash
git add app/core/batch_processor.py
git commit -m "feat: add dual-engine support to BatchProcessor (VL full-page / Rapid crop)"
```

---

### 里程碑 5：UI 升级

### Task 9: 创建 GPU 状态指示器

**Files:**
- Create: `app/ui/widgets/gpu_status.py`

- [ ] **Step 1: 创建 gpu_status.py**

```python
"""
GPU状态指示器 — 显示显存使用和引擎状态
"""
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QLabel
from PyQt6.QtCore import QTimer
from qfluentwidgets import BodyLabel


class GpuStatusWidget(QWidget):
    """GPU/引擎状态指示器"""

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(6)

        self.status_icon = QLabel("●")
        self.status_icon.setStyleSheet("font-size: 10px; color: #888;")
        layout.addWidget(self.status_icon)

        self.status_label = BodyLabel("引擎未初始化")
        layout.addWidget(self.status_label)

        # 定时刷新（每5秒更新显存）
        self._timer = QTimer()
        self._timer.timeout.connect(self._refresh)
        self._engine = None

    def set_engine(self, engine):
        """绑定引擎实例"""
        self._engine = engine
        self._refresh()
        if engine and engine.engine_name == "paddleocr_vl":
            self._timer.start(5000)
        else:
            self._timer.stop()

    def _refresh(self):
        if self._engine is None:
            self.status_icon.setStyleSheet("font-size: 10px; color: #888;")
            self.status_label.setText("引擎未初始化")
            return

        if not self._engine.is_ready:
            self.status_icon.setStyleSheet("font-size: 10px; color: #d83b01;")
            self.status_label.setText("引擎加载中...")
            return

        if self._engine.engine_name == "paddleocr_vl":
            try:
                used, total = self._engine.get_vram_usage()
                if used > 0:
                    self.status_icon.setStyleSheet("font-size: 10px; color: #107c10;")
                    self.status_label.setText(
                        f"GPU: PaddleOCR-VL | VRAM {used:.1f}/{total:.1f} GB"
                    )
                else:
                    self.status_icon.setStyleSheet("font-size: 10px; color: #0078d4;")
                    self.status_label.setText("GPU: PaddleOCR-VL (就绪)")
            except Exception:
                self.status_icon.setStyleSheet("font-size: 10px; color: #0078d4;")
                self.status_label.setText("GPU: PaddleOCR-VL (就绪)")
        else:
            self.status_icon.setStyleSheet("font-size: 10px; color: #666;")
            self.status_label.setText("CPU: RapidOCR (就绪)")

    def cleanup(self):
        """停止定时器"""
        self._timer.stop()
```

- [ ] **Step 2: Commit**

```bash
git add app/ui/widgets/gpu_status.py
git commit -m "feat: add GPU status indicator widget"
```

---

### Task 10: 增强 ResultTable 支持匹配级别颜色

**Files:**
- Modify: `app/ui/widgets/result_table.py`

**Interfaces:**
- Consumes: `FieldResult.match_level`, `FieldResult.engine`

- [ ] **Step 1: 修改 _populate_row 中字段列的背景色逻辑**

在 [result_table.py:95-123](app/ui/widgets/result_table.py#L95-L123) 的 `_populate_row` 方法中，替换字段值列的填充逻辑为：

```python
# 字段值列（替换原有的 for col, fn in enumerate(self._field_names, start=1): 循环体）
for col, fn in enumerate(self._field_names, start=1):
    fr = r.fields.get(fn)
    if fr:
        item = QTableWidgetItem(fr.text)
        # PaddleOCR-VL 匹配级别颜色（优先级高于置信度）
        if fr.match_level == 1:
            item.setBackground(QColor("#E5F5E5"))  # 绿色 - IoU精确
            item.setToolTip(f"匹配: IoU精确 | 置信度: {fr.confidence:.1%} | 引擎: {fr.engine}")
        elif fr.match_level == 2:
            item.setBackground(QColor("#FFFBE5"))  # 黄色 - 就近匹配
            item.setToolTip(f"匹配: 就近搜索 | 置信度: {fr.confidence:.1%} | 引擎: {fr.engine}")
        elif fr.match_level == 3:
            item.setBackground(QColor("#FFF0E5"))  # 橙色 - 关键词
            item.setToolTip(f"匹配: 关键词兜底 | 置信度: {fr.confidence:.1%} | 引擎: {fr.engine}")
        elif fr.confidence < 0.5:
            item.setBackground(QColor("#FFE5E5"))  # 红色 - 低置信度
            item.setToolTip(f"置信度: {fr.confidence:.1%} (较低，建议核对) | 引擎: {fr.engine}")
        elif fr.confidence < 0.7:
            item.setBackground(QColor("#FFF4E5"))  # 黄色 - 中等置信度
            item.setToolTip(f"置信度: {fr.confidence:.1%} (一般) | 引擎: {fr.engine}")
        else:
            item.setToolTip(f"置信度: {fr.confidence:.1%} | 引擎: {fr.engine}")

        if fr.manually_edited:
            item.setBackground(QColor("#E5F3FF"))  # 蓝色 - 已编辑
            item.setToolTip(f"{item.toolTip()}\n[已手动编辑]")

        self.setItem(row, col, item)
    else:
        self.setItem(row, col, QTableWidgetItem(""))
```

同时更新 `_reset_row` 方法中的颜色恢复逻辑（[result_table.py:212-221](app/ui/widgets/result_table.py#L212-L221)），使用相同的颜色逻辑。

- [ ] **Step 2: Commit**

```bash
git add app/ui/widgets/result_table.py
git commit -m "feat: add match_level color coding to ResultTable"
```

---

### Task 11: 主窗口 — 引擎工厂集成 + 引擎切换 + GPU 状态

**Files:**
- Modify: `app/ui/main_window.py`

这是最大的单文件改动。需要在 main_window.py 中做以下修改：

1. 导入改用工厂函数
2. 添加引擎切换下拉框
3. 集成 GPU 状态指示器
4. 适配 BatchProcessor 构造

- [ ] **Step 1: 修改导入和引擎初始化**

```python
# 替换第72行: from app.core.ocr_engine import OCREngine
# 改为:
from app.core.ocr_engine import get_ocr_engine
```

```python
# 替换第100-103行: OCREngine() 构造
# self.ocr_engine = OCREngine(lang=..., use_gpu=...)
# 改为:
self.ocr_engine = get_ocr_engine(self.config)
```

```python
# 替换第104-108行: 异步初始化
# self.ocr_engine.initialize_async(callback=self._on_ocr_ready)
# 改为（在后台线程中同步初始化）:
import threading
def _init_ocr():
    self.ocr_engine.initialize()
    # 用 QTimer 在主线程回调
    QTimer.singleShot(0, self._on_ocr_ready)
threading.Thread(target=_init_ocr, daemon=True, name="OCR-Init").start()
```

```python
# 第106-109行: BatchProcessor 构造函数不变
# （BatchProcessor 调用 self.ocr.recognize_page / self.ocr.recognize 即可）
```

- [ ] **Step 2: 在工具栏添加引擎切换下拉框**

在 `_create_toolbar()` 方法的 `toolbar_layout.addStretch()` 之前（[main_window.py:732](app/ui/main_window.py#L732)）添加：

```python
# 引擎切换（在 toolbar_layout.addStretch() 之前）
from qfluentwidgets import ComboBox
self.engine_combo = ComboBox()
self.engine_combo.addItems([
    "PaddleOCR-VL (GPU)",
    "RapidOCR (CPU)",
])
# 根据当前引擎设置默认选项
current_engine = self.config.get("ocr", {}).get("engine", "paddleocr_vl")
self.engine_combo.setCurrentIndex(0 if current_engine == "paddleocr_vl" else 1)
self.engine_combo.currentIndexChanged.connect(self._on_engine_switched)
self.engine_combo.setMinimumWidth(160)
toolbar_layout.addWidget(self.engine_combo)

toolbar_layout.addSpacing(4)

# GPU 状态指示器
from app.ui.widgets.gpu_status import GpuStatusWidget
self.gpu_status = GpuStatusWidget()
toolbar_layout.addWidget(self.gpu_status)
```

- [ ] **Step 3: 添加引擎切换处理和状态栏更新**

在 main_window.py 末尾（类内部）添加新方法：

```python
def _on_engine_switched(self, index: int):
    """引擎切换处理"""
    new_engine_type = "paddleocr_vl" if index == 0 else "rapidocr"
    current_engine = self.config.get("ocr", {}).get("engine", "paddleocr_vl")
    if new_engine_type == current_engine:
        return

    # 确认提示
    from qfluentwidgets import MessageBox
    msg = MessageBox(
        "切换OCR引擎",
        f"切换到 {'PaddleOCR-VL (GPU)' if index == 0 else 'RapidOCR (CPU)'}？\n\n"
        "注意：切换引擎后需要重新识别，当前未保存的识别结果将丢失。",
        self
    )
    msg.yesButton.setText("确认切换")
    msg.cancelButton.setText("取消")
    if not msg.exec():
        # 恢复原选项
        self.engine_combo.blockSignals(True)
        self.engine_combo.setCurrentIndex(0 if current_engine == "paddleocr_vl" else 1)
        self.engine_combo.blockSignals(False)
        return

    # 更新配置
    self.config["ocr"]["engine"] = new_engine_type

    # 重新创建引擎
    if hasattr(self.ocr_engine, 'unload'):
        self.ocr_engine.unload()
    self.ocr_engine = get_ocr_engine(self.config)

    # 异步初始化新引擎
    import threading
    def _reinit():
        self.ocr_engine.initialize()
        QTimer.singleShot(0, self._on_ocr_ready)
    threading.Thread(target=_reinit, daemon=True, name="OCR-Reinit").start()

    # 更新 BatchProcessor
    self.processor = BatchProcessor(
        self.pdf_loader, self.ocr_engine,
        max_workers=self.config["batch"]["max_workers"]
    )

    # 更新GPU状态绑定
    self.gpu_status.set_engine(self.ocr_engine)

    # 清空旧结果
    self._current_preview_result = None
    self._pdf_preview_results.clear()

    InfoBar.success(
        title="引擎已切换",
        content=f"当前引擎: {'PaddleOCR-VL (GPU)' if index == 0 else 'RapidOCR (CPU)'}",
        duration=3000,
        parent=self
    )
```

- [ ] **Step 4: 更新 _on_ocr_ready 绑定 GPU 状态**

在 `_on_ocr_ready()` 方法中，初始化成功后添加：

```python
# 在 self.loading_overlay.hide_overlay() 之后添加:
self.gpu_status.set_engine(self.ocr_engine)
```

- [ ] **Step 5: 更新 _on_use_cpu_mode 适配新接口**

```python
def _on_use_cpu_mode(self):
    """切换到CPU模式并重试"""
    try:
        self.config["ocr"]["engine"] = "rapidocr"
        from app.core.ocr_engine_rapid import RapidOCREngine
        self.ocr_engine = RapidOCREngine(lang="ch", use_gpu=False)
        import threading
        def _reinit():
            self.ocr_engine.initialize()
            QTimer.singleShot(0, self._on_ocr_ready)
        threading.Thread(target=_reinit, daemon=True).start()
        self.processor = BatchProcessor(
            self.pdf_loader, self.ocr_engine,
            max_workers=self.config["batch"]["max_workers"]
        )
        self.gpu_status.set_engine(self.ocr_engine)
        InfoBar.success(title="已切换到CPU模式",
                        content="OCR引擎将以CPU模式运行", duration=3000, parent=self)
    except Exception as e:
        InfoBar.error(title="切换失败", content=str(e), duration=3000, parent=self)
```

- [ ] **Step 6: 更新 _on_try_ocr 和 on_batch_run 中检查引擎状态**

保持不变 — `self.ocr_engine.is_ready` 在基类中定义，工作一致。

- [ ] **Step 7: Commit**

```bash
git add app/ui/main_window.py
git commit -m "feat: integrate engine factory, add engine switcher and GPU status bar"
```

---

### Task 12: 适配 OCRWorker

**Files:**
- Modify: `app/workers/ocr_worker.py`

OCRWorker 使用 `ocr_engine.recognize(image, mode)` — 这个接口在基类中定义且签名不变，所以无需改动。确认即可。

- [ ] **Step 1: Commit** — 如无改动，跳过

---

### Task 13: 增强 LoadingOverlay 支持 PaddleOCR-VL 错误

**Files:**
- Modify: `app/ui/widgets/loading_overlay.py`

在 `_translate_error_enhanced` 方法中添加 PaddlePaddle 相关的错误映射：

- [ ] **Step 1: 添加 PaddlePaddle/CUDA 错误映射**

在 `error_solutions` 字典（[loading_overlay.py:235-296](app/ui/widgets/loading_overlay.py#L235-L296)）开头添加：

```python
# PaddlePaddle/CUDA 相关错误（添加在现有映射之前）
"paddle": (
    "PaddlePaddle环境异常",
    "1. 检查PaddlePaddle GPU是否正确安装\n2. 运行: pip install paddlepaddle-gpu==3.2.1\n3. 或勾选下方「使用CPU模式运行」切换回RapidOCR",
    None
),
"no module named 'paddleocr'": (
    "未安装PaddleOCR-VL",
    "1. 运行: pip install 'paddleocr[doc-parser]>=3.6.0'\n2. 或勾选下方「使用CPU模式运行」使用RapidOCR",
    None
),
"no module named 'paddle'": (
    "未安装PaddlePaddle GPU",
    "1. 运行: pip install paddlepaddle-gpu==3.2.1\n2. 或勾选下方「使用CPU模式运行」使用RapidOCR",
    None
),
"cuda driver version is insufficient": (
    "CUDA驱动版本不兼容",
    "1. 更新NVIDIA显卡驱动\n2. 或勾选下方「使用CPU模式运行」使用RapidOCR",
    None
),
```

- [ ] **Step 2: Commit**

```bash
git add app/ui/widgets/loading_overlay.py
git commit -m "feat: add PaddlePaddle/CUDA error messages to LoadingOverlay"
```

---

### 里程碑 6：环境与部署

### Task 14: 更新配置文件

**Files:**
- Modify: `config.yaml`

- [ ] **Step 1: 更新 config.yaml**

如果已存在 config.yaml，保留现有值并合并新字段。如果不存在，创建包含所有默认值的配置文件。

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.utils.config_loader import load_config, get_default_config
import yaml
from pathlib import Path

config_path = Path('config.yaml')
default = get_default_config()

if config_path.exists():
    # 合并：保留现有值，添加缺失的默认值
    with open(config_path, 'r', encoding='utf-8') as f:
        existing = yaml.safe_load(f) or {}
    # 深度合并（简单实现）
    for key, value in default.items():
        if key not in existing:
            existing[key] = value
        elif isinstance(value, dict) and isinstance(existing.get(key), dict):
            for sub_key, sub_value in value.items():
                if sub_key not in existing[key]:
                    existing[key][sub_key] = sub_value
    final_config = existing
else:
    final_config = default

with open(config_path, 'w', encoding='utf-8') as f:
    yaml.dump(final_config, f, allow_unicode=True, default_flow_style=False, sort_keys=False)

print('Config written OK')
print(f'Engine: {final_config[\"ocr\"][\"engine\"]}')
"
```

- [ ] **Step 2: Commit**

```bash
git add config.yaml
git commit -m "chore: update config.yaml with PaddleOCR-VL and RapidOCR sections"
```

---

### Task 15: 创建启动脚本和依赖清单

**Files:**
- Create: `run.bat`
- Create: `run.sh`
- Create: `setup_env.bat`
- Create: `requirements-gpu.txt`
- Create: `requirements-cpu.txt`

- [ ] **Step 1: 创建 run.bat**

```batch
@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

REM PDFOCR 智能启动器
REM 默认使用 GPU 环境，不可用时回退到 CPU 环境

set "SCRIPT_DIR=%~dp0"
set "GPU_VENV=%SCRIPT_DIR%venv"
set "CPU_VENV=%SCRIPT_DIR%venv-cpu"
set "FORCE_CPU=0"

REM 检查命令行参数
if "%1"=="--cpu" set "FORCE_CPU=1"
if "%1"=="-c" set "FORCE_CPU=1"

if "%FORCE_CPU%"=="1" (
    echo [INFO] 强制使用CPU模式
    set "USE_VENV=%CPU_VENV%"
    set "PDFOCR_ENGINE=rapidocr"
    goto :check_venv
)

REM 检查GPU环境
if exist "%GPU_VENV%\Scripts\python.exe" (
    echo [INFO] 使用GPU环境: PaddleOCR-VL
    set "USE_VENV=%GPU_VENV%"
    set "PDFOCR_ENGINE=paddleocr_vl"
    goto :check_venv
)

REM GPU环境不可用，回退CPU
echo [WARN] GPU环境不可用，回退到CPU环境
set "USE_VENV=%CPU_VENV%"
set "PDFOCR_ENGINE=rapidocr"

:check_venv
if not exist "%USE_VENV%\Scripts\python.exe" (
    echo [ERROR] 未找到Python环境！
    echo   请运行 setup_env.bat 安装环境
    pause
    exit /b 1
)

REM 激活并启动
call "%USE_VENV%\Scripts\activate.bat"
set "PDFOCR_ENGINE=%PDFOCR_ENGINE%"
echo [INFO] 引擎: %PDFOCR_ENGINE%
echo [INFO] 启动中...
python "%SCRIPT_DIR%main.py"

endlocal
```

- [ ] **Step 2: 创建 run.sh**

```bash
#!/bin/bash
# PDFOCR 智能启动器 (Git Bash / Linux)
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
GPU_VENV="$SCRIPT_DIR/venv"
CPU_VENV="$SCRIPT_DIR/venv-cpu"
FORCE_CPU=0

[[ "$1" == "--cpu" || "$1" == "-c" ]] && FORCE_CPU=1

if [[ $FORCE_CPU -eq 1 ]]; then
    echo "[INFO] 强制使用CPU模式"
    USE_VENV="$CPU_VENV"
    export PDFOCR_ENGINE=rapidocr
elif [[ -f "$GPU_VENV/Scripts/python.exe" ]]; then
    echo "[INFO] 使用GPU环境: PaddleOCR-VL"
    USE_VENV="$GPU_VENV"
    export PDFOCR_ENGINE=paddleocr_vl
elif [[ -f "$GPU_VENV/bin/python" ]]; then
    echo "[INFO] 使用GPU环境: PaddleOCR-VL"
    USE_VENV="$GPU_VENV"
    export PDFOCR_ENGINE=paddleocr_vl
else
    echo "[WARN] GPU环境不可用，回退到CPU环境"
    USE_VENV="$CPU_VENV"
    export PDFOCR_ENGINE=rapidocr
fi

if [[ ! -f "$USE_VENV/Scripts/python.exe" && ! -f "$USE_VENV/bin/python" ]]; then
    echo "[ERROR] 未找到Python环境！请运行 setup_env.bat 安装"
    exit 1
fi

echo "[INFO] 引擎: $PDFOCR_ENGINE"
source "$USE_VENV/Scripts/activate" 2>/dev/null || source "$USE_VENV/bin/activate" 2>/dev/null
python "$SCRIPT_DIR/main.py"
```

- [ ] **Step 3: 创建 requirements-gpu.txt**

```
# PDFOCR GPU 环境依赖 (PaddleOCR-VL)
paddlepaddle-gpu==3.2.1
paddleocr[doc-parser]>=3.6.0
PyQt6>=6.5.0
PyQt6-Fluent-Widgets>=1.4.0
QtAwesome>=1.2.0
PyMuPDF>=1.23.0
Pillow>=10.0.0
opencv-python>=4.8.0
numpy>=1.24.0
pandas>=2.0.0
openpyxl>=3.1.0
PyYAML>=6.0
rapidocr-onnxruntime>=1.3.0
pynvml>=11.0
```

- [ ] **Step 4: 创建 requirements-cpu.txt**

```
# PDFOCR CPU 环境依赖 (RapidOCR 降级备用)
rapidocr-onnxruntime>=1.3.0
PyQt6>=6.5.0
PyQt6-Fluent-Widgets>=1.4.0
QtAwesome>=1.2.0
PyMuPDF>=1.23.0
Pillow>=10.0.0
opencv-python>=4.8.0
numpy>=1.24.0
pandas>=2.0.0
openpyxl>=3.1.0
PyYAML>=6.0
```

- [ ] **Step 5: 创建 setup_env.bat**

```batch
@echo off
chcp 65001 >nul
echo ============================================
echo  PDFOCR 环境安装 - PaddleOCR-VL GPU版
echo  硬件: NVIDIA RTX 5060 Laptop (8GB VRAM)
echo ============================================
echo.

set "SCRIPT_DIR=%~dp0"

REM 1. 创建 GPU 主环境
echo [1/3] 创建GPU主环境 (PaddleOCR-VL)...
python -m venv "%SCRIPT_DIR%venv"
call "%SCRIPT_DIR%venv\Scripts\activate.bat"
python -m pip install --upgrade pip
pip install paddlepaddle-gpu==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install "paddleocr[doc-parser]>=3.6.0"
pip install PyQt6>=6.5.0 PyQt6-Fluent-Widgets>=1.4.0 QtAwesome>=1.2.0
pip install PyMuPDF>=1.23.0 Pillow>=10.0.0 opencv-python>=4.8.0
pip install numpy>=1.24.0 pandas>=2.0.0 openpyxl>=3.1.0 PyYAML>=6.0
pip install rapidocr-onnxruntime>=1.3.0 pynvml>=11.0

REM 验证 GPU
echo.
echo [2/3] 验证GPU环境...
python -c "import paddle; print('CUDA可用:', paddle.is_compiled_with_cuda())"

REM 创建 CPU 备用环境
echo.
echo [3/3] 创建CPU备用环境 (RapidOCR)...
python -m venv "%SCRIPT_DIR%venv-cpu"
call "%SCRIPT_DIR%venv-cpu\Scripts\activate.bat"
pip install rapidocr-onnxruntime>=1.3.0
pip install PyQt6>=6.5.0 PyQt6-Fluent-Widgets>=1.4.0 QtAwesome>=1.2.0
pip install PyMuPDF>=1.23.0 Pillow>=10.0.0 opencv-python>=4.8.0
pip install numpy>=1.24.0 pandas>=2.0.0 openpyxl>=3.1.0 PyYAML>=6.0

echo.
echo ============================================
echo  安装完成！
echo  启动方式:
echo    run.bat          - 自动使用GPU环境
echo    run.bat --cpu    - 强制使用CPU环境
echo ============================================
pause
```

- [ ] **Step 6: Commit**

```bash
git add run.bat run.sh setup_env.bat requirements-gpu.txt requirements-cpu.txt
git commit -m "feat: add startup scripts, setup script, and dependency lists"
```

---

### Task 16: 端到端验证

- [ ] **Step 1: 验证 RapidOCR 模式（当前环境）**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.ocr_engine import get_ocr_engine
from app.utils.config_loader import get_default_config

config = get_default_config()
config['ocr']['engine'] = 'rapidocr'
engine = get_ocr_engine(config)
engine.initialize()
assert engine.is_ready
assert engine.engine_name == 'rapidocr'

from PIL import Image
img = Image.new('RGB', (200, 50), 'white')
text, conf = engine.recognize(img)
print(f'RapidOCR: text={repr(text)}, conf={conf}')
assert isinstance(text, str)
assert isinstance(conf, float)
print('RapidOCR mode: PASS')
"
```

- [ ] **Step 2: 验证 PaddleOCR-VL 降级**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
from app.core.ocr_engine import get_ocr_engine
from app.utils.config_loader import get_default_config

config = get_default_config()
config['ocr']['engine'] = 'paddleocr_vl'
engine = get_ocr_engine(config)
# 当前环境无PaddlePaddle，应自动降级
print(f'Engine: {engine.engine_name}')
assert engine.engine_name == 'rapidocr', 'Should degrade to RapidOCR'
print('PaddleOCR-VL graceful degradation: PASS')
"
```

- [ ] **Step 3: 验证 GUI 启动（5秒超时）**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && timeout 5 python main.py 2>&1; echo "Exit: $?"
```

预期：程序启动无报错，timeout 退出码 124（正常）。

- [ ] **Step 4: 验证完整导入链**

```bash
cd tools/PDFOCR && source venv/Scripts/activate && python -c "
# 验证所有新模块可导入
from app.core.ocr_engine_base import OCREngineBase
from app.core.ocr_engine_rapid import RapidOCREngine
from app.core.ocr_engine_paddle import PaddleOCREngine
from app.core.ocr_engine import get_ocr_engine, OCREngine
from app.core.field_matcher import FieldMatcher, MatchResult
from app.ui.widgets.gpu_status import GpuStatusWidget
from app.models.ocr_result import FieldResult, FileResult
from app.models.region import Region
from app.utils.config_loader import load_config, get_default_config
print('All imports OK')
"
```

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "test: add verification steps, all imports and RapidOCR mode pass"
```

---

## 部署指南（首次切换到 GPU 模式）

1. 确保 CUDA 驱动正常：`nvidia-smi`
2. 运行 `setup_env.bat` 创建 GPU 主环境
3. 运行 `run.bat` 启动程序
4. 首次启动 PaddleOCR-VL 会下载模型（~2GB），需等待 5-10 分钟
5. 后续启动直接使用缓存模型

## 回退计划

如果 PaddleOCR-VL 部署遇到问题：
1. 运行 `run.bat --cpu` 强制使用 RapidOCR CPU 模式
2. 或在 GUI 中将引擎切换为 "RapidOCR (CPU)"
3. `venv-cpu/` 环境完全独立，不受 GPU 环境影响
