# PaddleOCR-VL 1.6 升级设计文档

**日期**: 2026-07-05
**状态**: 待实现
**设备**: RTX 5060 8GB VRAM, Python 3.12.7, CUDA 13.3

---

## 背景

用户更换新电脑（RTX 5060 GPU），希望将 PDFOCR 项目升级为以 PaddleOCR-VL-1.6（GPU 版本）为中心的识别架构，同时保留 RapidOCR 作为 CPU 降级备用方案。两种引擎通过配置实现全局切换。

### 关键决策

| 决策点 | 选择 |
|--------|------|
| 引擎分工模式 | 全局切换（一次任务使用一种引擎） |
| PaddleOCR-VL 识别流程 | 整页识别 + 坐标匹配字段 |
| Python 环境 | GPU 主 venv + CPU 备用 venv，双环境隔离 |
| 项目重心 | 以 PaddleOCR-VL 为中心，RapidOCR 为降级备用 |

---

## 一、核心架构：OCR 引擎抽象层

### 1.1 设计目标

将当前硬编码 RapidOCR 的 `OCREngine` 重构为抽象工厂模式，支持 PaddleOCR-VL 和 RapidOCR 两种引擎无感切换。

### 1.2 文件结构

```
app/core/
├── ocr_engine_base.py      ← 新增：抽象基类
├── ocr_engine_rapid.py     ← 重构：现有代码迁入，类名 RapidOCREngine
├── ocr_engine_paddle.py    ← 新增：PaddleOCR-VL 引擎
├── ocr_engine.py           ← 重写：工厂函数 + OCREngine 别名向后兼容
└── field_matcher.py        ← 新增：三级匹配引擎
```

### 1.3 抽象基类 OCREngineBase

```python
class OCREngineBase(ABC):
    @abstractmethod
    def initialize(self) -> None: ...
    @abstractmethod
    def recognize(self, image: Image.Image, mode: str = "general") -> Tuple[str, float]: ...
    @abstractmethod
    def recognize_page(self, image: Image.Image, regions: List[Region],
                       page_dpi: float) -> Dict[str, Tuple[str, float]]: ...
    @property
    @abstractmethod
    def is_ready(self) -> bool: ...
    @property
    @abstractmethod
    def engine_name(self) -> str: ...
    @abstractmethod
    def unload(self) -> None: ...  # PaddleOCR-VL 需支持卸载GPU模型
```

### 1.4 工厂函数

```python
def get_ocr_engine(config: dict) -> OCREngineBase:
    engine_type = config["ocr"]["engine"]
    if engine_type == "paddleocr_vl":
        from app.core.ocr_engine_paddle import PaddleOCREngine
        return PaddleOCREngine(config)
    else:
        from app.core.ocr_engine_rapid import RapidOCREngine
        return RapidOCREngine(config)

# 向后兼容
OCREngine = get_ocr_engine
```

### 1.5 RapidOCR 引擎（重构）

- 文件：`app/core/ocr_engine_rapid.py`
- 类名：`RapidOCREngine`
- `recognize()`：逐区域裁剪 + RapidOCR 推理（当前行为，保持不变）
- `recognize_page()`：循环调用 `recognize()` 遍历所有区域
- 引擎名：`"rapidocr"`

### 1.6 PaddleOCR-VL 引擎（新增）

- 文件：`app/core/ocr_engine_paddle.py`
- 类名：`PaddleOCREngine`
- `initialize()`：加载 PaddleOCR-VL 模型到 GPU，运行预热推理
- `recognize()`：单区域识别（降级为识别整图后取匹配结果）
- `recognize_page()`：整页送入 PaddleOCR-VL → 获取 elements 列表 → FieldMatcher 匹配
- `unload()`：卸载 GPU 模型释放显存
- 引擎名：`"paddleocr_vl"`

---

## 二、性能优化策略

### 2.1 模型常驻内存

- 引擎初始化为单例，程序启动时调用 `initialize()` 加载模型到 GPU
- 模型保持常驻，后续识别不再重复加载（避免每次 ~3-5 秒加载开销）
- RapidOCR 也保持同样的单例模式

### 2.2 启动预热

- `initialize()` 中用极小空白图（64×64）跑一次 `recognize()`
- 触发 CUDA kernel 编译缓存，后续推理更快
- 预热在后台线程执行，不阻塞 GUI 启动

### 2.3 整页批量处理

- PaddleOCR-VL 模式：每页仅 1 次推理（vs RapidOCR 模式每页 N 个区域 N 次调用）
- N 个区域 → 1 次推理，速度提升接近 N 倍

### 2.4 智能显存管理

| 场景 | 策略 |
|------|------|
| 正常推理 | 模型常驻 GPU（~2.3GB） |
| 多页批量 | 复用模型，逐页推理 |
| 空闲 > 可配置时长 | 可选自动卸载到 CPU（配置 `idle_unload_seconds`） |
| 显存不足 | 程序启动时检测，不足 3GB 时提示切换到 RapidOCR |

### 2.5 图片预处理优化

- NaViT 编码器支持动态分辨率（32×32 ~ 4096×4096），无需固定尺寸 resize
- PDF 渲染 DPI：默认 200，复杂文档（小字/密集排版）自动提升到 300
- 跳过不必要的预处理（去噪/二值化由 VLM 自行处理）

---

## 三、字段匹配策略（PaddleOCR-VL 模式核心）

### 3.1 PaddleOCR-VL 输出结构

```python
{
    "elements": [
        {"type": "text",  "bbox": [x1,y1,x2,y2], "text": "发票号码：12345678", "confidence": 0.97},
        {"type": "table", "bbox": [x1,y1,x2,y2], "markdown": "|品名|数量|...",      "confidence": 0.93},
    ],
    "markdown": "# 发票\n\n发票号码：12345678\n\n...",
    "reading_order": [0, 1, 2, ...]
}
```

### 3.2 三级降级匹配

| 级别 | 策略 | 说明 |
|------|------|------|
| Level 1 | IoU 精确匹配 | 用户区域 bbox 与 element bbox 计算 `交集面积/并集面积`，≥ `match_iou_threshold`(默认0.5) 直接命中 |
| Level 2 | 就近搜索 | IoU 无命中时，在区域周围 `match_neighbor_radius`(默认50px) 内搜索最近 elements，合并相邻文字 |
| Level 3 | 关键词兜底 | 在整个 markdown 中用正则 `字段名[：:]\s*(\S+)` 搜索，提取紧邻值。需模板配置 `match_keywords` |

### 3.3 FieldMatcher 类

```python
class FieldMatcher:
    def __init__(self, config): ...
    def match(self, elements: List[dict], regions: List[Region]) -> Dict[str, MatchResult]:
        """返回 {region_id: (text, confidence, level)}"""
```

### 3.4 模板字段增强（可选）

```yaml
fields:
  - name: "发票号码"
    bbox: [x1, y1, x2, y2]
    match_keywords: ["发票号码", "发票代码", "No."]  # 新增：Level 3 兜底关键词
    match_mode: "value"  # "exact" | "label_value"
```

缺失 `match_keywords` 的旧字段仅使用 Level 1+2 匹配，向后兼容。

### 3.5 匹配结果 UI 标记

| 级别 | 含义 | UI 颜色 |
|------|------|---------|
| Level 1 (IoU) | 精准命中 | 🟢 绿色 |
| Level 2 (就近) | 相邻匹配 | 🟡 黄色 |
| Level 3 (关键词) | 模糊兜底 | 🟠 橙色 |
| Level 0 (未匹配) | 识别失败 | 🔴 红色 |

---

## 四、双 venv 环境架构

### 4.1 环境布局

```
tools/PDFOCR/
├── venv/              ← 主环境：PaddleOCR-VL GPU（默认）
│   └── 依赖：paddlepaddle-gpu, paddleocr[doc-parser], PyQt6, PyMuPDF, ...
│
├── venv-cpu/          ← 备用环境：仅 RapidOCR CPU
│   └── 依赖：rapidocr-onnxruntime, PyQt6, PyMuPDF, ...
│
├── run.bat            ← Windows 启动脚本（自动选环境）
├── run.sh             ← Git Bash 启动脚本
├── setup_env.bat      ← 一键环境安装脚本
├── requirements-gpu.txt
└── requirements-cpu.txt
```

### 4.2 智能启动器逻辑

```
1. 检测 venv/ 是否存在且可用 → 是：激活 GPU 环境，设置 PDFOCR_ENGINE=paddleocr_vl
2. venv/ 不可用 → 回退 venv-cpu/，设置 PDFOCR_ENGINE=rapidocr
3. run.bat --cpu → 强制使用 venv-cpu/，PDFOCR_ENGINE=rapidocr
4. Python 端：读取 PDFOCR_ENGINE 环境变量，覆盖 config["ocr"]["engine"]（若 config 设置不同步）
```

环境变量 `PDFOCR_ENGINE` 作为启动脚本与 Python 程序的通信桥梁，优先级高于 config.yaml。

### 4.3 配置文件 `config.yaml`

```yaml
ocr:
  engine: paddleocr_vl           # 默认引擎
  
  paddleocr_vl:
    model_name: PaddleOCR-VL-1.6-0.9B
    device: gpu
    warmup_on_startup: true
    idle_unload_seconds: 300
    backend: paddle
    page_dpi: 200
    high_quality_dpi: 300
    match_iou_threshold: 0.5
    match_neighbor_radius: 50
    
  rapidocr:
    use_gpu: false
    lang: ch
    det_db_box_thresh: 0.3
    drop_score: 0.5
```

### 4.4 兼容性处理

| 场景 | 策略 |
|------|------|
| GPU 不可用 | 启动器自动回退 CPU，程序自动切换引擎 |
| CUDA 版本不匹配 | PaddlePaddle CUDA 12.6 wheel 自带 CUDA 库，独立于系统 |
| 显存 < 3GB | 启动时检测并警告，建议切换 RapidOCR |
| 旧模板无 match_keywords | 可选字段，缺失时仅用 Level 1+2 |
| 旧 config 无 paddleocr_vl 段 | ConfigLoader 提供完整默认值 |

---

## 五、识别流程重构

### 5.1 两种模式对比

```
RapidOCR 模式（保留）:
  PDF → 渲染 → 裁剪区域1 → OCR → 文字1
              → 裁剪区域2 → OCR → 文字2
              → 裁剪区域N → OCR → 文字N
  特点: N 次推理，精准裁剪，无版面理解

PaddleOCR-VL 模式（主流程）:
  PDF → 渲染整页 → PaddleOCR-VL 1次推理 → elements[{bbox, text, type, conf}]
                → FieldMatcher 三级匹配 → 各字段结果
  特点: 1 次推理，VLM 理解版面，支持表格/手写/公式
```

### 5.2 BatchProcessor 重构

```python
class BatchProcessor:
    def process_page(self, page_image, regions, page_num) -> Dict[str, FieldResult]:
        if self.ocr.engine_name == "paddleocr_vl":
            return self._process_vl(page_image, regions, page_num)
        else:
            return self._process_rapid(page_image, regions, page_num)
```

- `_process_vl()`：整页识别 + FieldMatcher 匹配
- `_process_rapid()`：逐区域裁剪识别（现有逻辑）

### 5.3 数据模型增强

```python
@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    manually_edited: bool = False
    match_level: int = 0     # 新增: 1/2/3/0 PaddleOCR-VL匹配级别
    engine: str = ""         # 新增: "paddleocr_vl" | "rapidocr"
```

---

## 六、UI 适配

### 6.1 新增控件

- **引擎切换下拉框**：工具栏右上角，`PaddleOCR-VL (GPU) ← 推荐` / `RapidOCR (CPU) ← 降级备用`
- **GPU 状态指示器**：工具栏状态区，显示 GPU 型号、显存使用
- **结果表格增强**：增加"匹配方式"列，颜色标记置信度

### 6.2 设置对话框新增 OCR 引擎页

- 默认引擎选择
- PaddleOCR-VL 专属：预热开关、空闲卸载、渲染 DPI、IoU 阈值
- RapidOCR 专属：语言、检测阈值

### 6.3 交互行为

- 切换引擎时弹出确认提示（当前任务会中断）
- GPU 不可用时自动降级并显示警告
- 引擎状态实时显示：🟢就绪 / 🟡加载中 / 🔴不可用 / ⚪已卸载
- 引擎初始化在后台线程进行（通过 QThread worker），不阻塞 GUI；加载期间引擎切换下拉框禁用

---

## 七、部署与验证

### 7.1 部署步骤

```bash
# 1. 确认 GPU
nvidia-smi

# 2. 创建 GPU 主环境
python -m venv venv
source venv/Scripts/activate  # Windows Git Bash
pip install paddlepaddle-gpu==3.2.1 -i https://www.paddlepaddle.org.cn/packages/stable/cu126/
pip install "paddleocr[doc-parser]>=3.6.0"
pip install PyQt6 PyQt6-Fluent-Widgets QtAwesome PyMuPDF Pillow opencv-python numpy pandas openpyxl PyYAML pyyaml

# 3. 验证
python -c "import paddle; print('CUDA:', paddle.is_compiled_with_cuda())"

# 4. 创建 CPU 备用环境（可选）
python -m venv venv-cpu
source venv-cpu/Scripts/activate
pip install rapidocr-onnxruntime PyQt6 PyQt6-Fluent-Widgets QtAwesome PyMuPDF Pillow opencv-python numpy pandas openpyxl PyYAML pyyaml

# 5. 运行
run.bat           # 自动使用 GPU
run.bat --cpu     # 强制 CPU
```

### 7.2 文件变更清单

| 文件 | 操作 | 说明 |
|------|------|------|
| `app/core/ocr_engine_base.py` | 新增 | 引擎抽象基类 |
| `app/core/ocr_engine_rapid.py` | 重构 | RapidOCREngine — 现有代码迁入 |
| `app/core/ocr_engine_paddle.py` | 新增 | PaddleOCREngine — PaddleOCR-VL 实现 |
| `app/core/ocr_engine.py` | 重写 | 工厂函数 + 向后兼容别名 |
| `app/core/field_matcher.py` | 新增 | 三级匹配引擎 |
| `app/core/batch_processor.py` | 重构 | VL 整页 / Rapid 裁剪分支 |
| `app/models/ocr_result.py` | 增强 | 新增 match_level, engine 字段 |
| `app/models/region.py` | 增强 | 新增 match_keywords, match_mode 可选字段 |
| `app/ui/main_window.py` | 增强 | 引擎切换、GPU 状态指示器 |
| `app/ui/widgets/result_table.py` | 增强 | 匹配级别颜色标记 |
| `app/ui/widgets/gpu_status.py` | 新增 | GPU 状态 Widget |
| `app/utils/config_loader.py` | 增强 | paddleocr_vl 配置段 + 默认值 |
| `config.yaml` | 更新 | 新增 OCR 引擎配置 |
| `run.bat` | 新增 | Windows 智能启动器 |
| `run.sh` | 新增 | Git Bash 启动器 |
| `setup_env.bat` | 新增 | 一键环境安装 |
| `requirements-gpu.txt` | 新增 | GPU 依赖清单 |
| `requirements-cpu.txt` | 新增 | CPU 依赖清单 |

### 7.3 验证清单

- [ ] GPU 引擎基础：启动程序，PaddleOCR-VL 就绪，识别发票字段正确
- [ ] 引擎切换：运行时切换 RapidOCR ↔ PaddleOCR-VL，重新识别正常
- [ ] 降级回退：`venv/` 不可用时自动回退 `venv-cpu/`
- [ ] 批量处理：多页 PDF 连续识别，GPU 显存无泄漏
- [ ] 字段匹配精度：验证 Level 1/2/3/0 各场景
- [ ] 旧模板兼容：无 `match_keywords` 的旧模板正常工作

---

## 八、注意事项

1. **PaddlePaddle CUDA 兼容性**：系统 CUDA 13.3 比 PaddlePaddle 官方支持的最高版本 CUDA 12.6 更新，需使用 PaddlePaddle 的 CUDA 12.6 wheel，它自带 CUDA 运行时库，不依赖系统 CUDA 版本。
2. **RTX 5060 Blackwell 架构**：如 PaddlePaddle 标准后端有问题，可切换 vLLM 后端（`backend: vllm`），vLLM 对 Blackwell 架构有更好支持。
3. **首次加载慢**：PaddleOCR-VL 首次 `predict()` 会触发模型下载和 CUDA kernel 编译，可能需要 30-60 秒。后续推理恢复正常速度。
4. **不改变现有功能**：RapidOCR 模式的识别逻辑完全保留，仅代码位置迁移到 `ocr_engine_rapid.py`，行为不变。
