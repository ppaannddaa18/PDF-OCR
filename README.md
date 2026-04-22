## 🤖 Assistant

# PDF 多区域 OCR 批量识别工具 - 代码框架设计

## 一、技术栈确认

- **语言**：Python 3.9+
- **GUI**：PySide6（Qt for Python，比 PyQt 授权更友好）
- **PDF 渲染**：PyMuPDF (fitz)
- **OCR**：PaddleOCR
- **图像处理**：Pillow + OpenCV
- **Excel 导出**：openpyxl
- **数据处理**：pandas
- **打包**：PyInstaller

---

## 二、项目目录结构

```
pdf_ocr_tool/
│
├── main.py                          # 程序入口
├── requirements.txt                 # 依赖列表
├── README.md                        # 使用说明
├── config.yaml                      # 全局配置文件
│
├── app/                             # 主应用代码
│   ├── __init__.py
│   │
│   ├── core/                        # 核心业务逻辑层
│   │   ├── __init__.py
│   │   ├── pdf_loader.py            # PDF 加载与渲染
│   │   ├── ocr_engine.py            # PaddleOCR 封装
│   │   ├── region_manager.py        # 区域（框选）管理
│   │   ├── template_manager.py      # 模板保存/加载
│   │   ├── batch_processor.py       # 批量处理调度
│   │   ├── exporter.py              # Excel/CSV 导出
│   │   └── coordinate_utils.py      # 坐标换算工具
│   │
│   ├── ui/                          # UI 层
│   │   ├── __init__.py
│   │   ├── main_window.py           # 主窗口
│   │   ├── widgets/                 # 自定义控件
│   │   │   ├── __init__.py
│   │   │   ├── pdf_canvas.py        # PDF 展示+框选画布
│   │   │   ├── file_list_panel.py   # 左栏：文件列表
│   │   │   ├── field_panel.py       # 右栏：字段配置
│   │   │   ├── result_table.py      # 结果表格视图
│   │   │   └── progress_dialog.py   # 进度对话框
│   │   └── styles/
│   │       └── app.qss              # Qt 样式表
│   │
│   ├── models/                      # 数据模型
│   │   ├── __init__.py
│   │   ├── region.py                # 区域数据模型
│   │   ├── template.py              # 模板数据模型
│   │   └── ocr_result.py            # OCR 结果数据模型
│   │
│   ├── workers/                     # 后台线程
│   │   ├── __init__.py
│   │   ├── ocr_worker.py            # OCR 异步工作线程
│   │   └── batch_worker.py          # 批量处理线程
│   │
│   └── utils/                       # 工具函数
│       ├── __init__.py
│       ├── logger.py                # 日志
│       ├── config_loader.py         # 配置加载
│       ├── image_utils.py           # 图像预处理
│       └── validators.py            # 字段格式校验
│
├── resources/                       # 资源文件
│   ├── icons/
│   └── templates/                   # 内置模板示例
│
├── tests/                           # 单元测试
│   ├── test_pdf_loader.py
│   ├── test_ocr_engine.py
│   ├── test_coordinate_utils.py
│   └── test_exporter.py
│
└── logs/                            # 运行日志（自动生成）
```

---

## 三、核心模块代码框架

### 3.1 程序入口 `main.py`

```python
import sys
from PySide6.QtWidgets import QApplication
from app.ui.main_window import MainWindow
from app.utils.logger import setup_logger
from app.utils.config_loader import load_config

def main():
    setup_logger()
    config = load_config("config.yaml")

    app = QApplication(sys.argv)
    with open("app/ui/styles/app.qss", "r", encoding="utf-8") as f:
        app.setStyleSheet(f.read())

    window = MainWindow(config)
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()
```

### 3.2 配置文件 `config.yaml`

```yaml
app:
  name: "PDF OCR Tool"
  version: "1.0.0"
  window_size: [1400, 900]

pdf:
  render_dpi: 200           # PDF 渲染 DPI
  max_preview_size: 2000    # 最大预览像素

ocr:
  lang: "ch"                # 语言：ch / en / chinese_cht
  use_gpu: false
  use_angle_cls: true
  det_db_box_thresh: 0.5
  drop_score: 0.5

batch:
  max_workers: 4            # 并发进程数
  retry_times: 2

export:
  default_format: "xlsx"
  include_confidence: true
  include_source_file: true
```

### 3.3 数据模型

**`app/models/region.py`**
```python
from dataclasses import dataclass, field
from typing import Literal

@dataclass
class Region:
    """框选区域数据模型（坐标使用归一化 0~1 比例）"""
    id: str                            # 唯一标识
    field_name: str                    # 字段名（如"姓名"）
    x: float                           # 左上角 x 比例
    y: float                           # 左上角 y 比例
    w: float                           # 宽度比例
    h: float                           # 高度比例
    field_type: Literal["text", "number", "date", "email", "phone"] = "text"
    ocr_mode: Literal["general", "single_line", "number"] = "general"
    color: str = "#FF5733"             # 框的显示颜色

    def to_dict(self) -> dict:
        return self.__dict__.copy()

    @classmethod
    def from_dict(cls, data: dict) -> "Region":
        return cls(**data)
```

**`app/models/template.py`**
```python
from dataclasses import dataclass, field
from typing import List
from datetime import datetime
from app.models.region import Region

@dataclass
class Template:
    name: str
    regions: List[Region] = field(default_factory=list)
    page_width: float = 0.0            # 模板 PDF 页面宽（pt）
    page_height: float = 0.0
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "regions": [r.to_dict() for r in self.regions],
            "page_width": self.page_width,
            "page_height": self.page_height,
            "created_at": self.created_at,
            "description": self.description,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Template":
        data = data.copy()
        data["regions"] = [Region.from_dict(r) for r in data.get("regions", [])]
        return cls(**data)
```

**`app/models/ocr_result.py`**
```python
from dataclasses import dataclass
from typing import Dict

@dataclass
class FieldResult:
    field_name: str
    text: str
    confidence: float
    manually_edited: bool = False

@dataclass
class FileResult:
    source_file: str
    fields: Dict[str, FieldResult]
    success: bool = True
    error_msg: str = ""
```

### 3.4 核心层

**`app/core/pdf_loader.py`**
```python
import fitz
from PIL import Image
import io

class PdfLoader:
    def __init__(self, dpi: int = 200):
        self.dpi = dpi

    def render_page(self, pdf_path: str, page_num: int = 0) -> Image.Image:
        """渲染指定页为 PIL Image"""
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        mat = fitz.Matrix(self.dpi / 72, self.dpi / 72)
        pix = page.get_pixmap(matrix=mat, alpha=False)
        img = Image.open(io.BytesIO(pix.tobytes("png")))
        doc.close()
        return img

    def get_page_size(self, pdf_path: str, page_num: int = 0) -> tuple:
        """返回 PDF 页面原始尺寸 (width_pt, height_pt)"""
        doc = fitz.open(pdf_path)
        page = doc[page_num]
        rect = page.rect
        doc.close()
        return rect.width, rect.height

    def crop_region(self, pdf_path: str, region, page_num: int = 0) -> Image.Image:
        """根据归一化坐标裁剪区域"""
        img = self.render_page(pdf_path, page_num)
        W, H = img.size
        left = int(region.x * W)
        top = int(region.y * H)
        right = int((region.x + region.w) * W)
        bottom = int((region.y + region.h) * H)
        return img.crop((left, top, right, bottom))
```

**`app/core/ocr_engine.py`**
```python
from paddleocr import PaddleOCR
from PIL import Image
import numpy as np
from app.utils.image_utils import preprocess_for_ocr

class OCREngine:
    _instance = None

    def __new__(cls, *args, **kwargs):
        # 单例：避免 PaddleOCR 模型被重复加载
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, lang="ch", use_gpu=False, use_angle_cls=True):
        if hasattr(self, "_initialized"):
            return
        self.ocr = PaddleOCR(
            use_angle_cls=use_angle_cls,
            lang=lang,
            use_gpu=use_gpu,
            show_log=False,
        )
        self._initialized = True

    def recognize(self, image: Image.Image, mode: str = "general") -> tuple:
        """
        返回 (合并文本, 平均置信度)
        """
        img = preprocess_for_ocr(image, mode)
        arr = np.array(img)
        result = self.ocr.ocr(arr, cls=True)

        if not result or not result[0]:
            return "", 0.0

        lines = []
        confidences = []
        for line in result[0]:
            text, conf = line[1][0], line[1][1]
            lines.append(text)
            confidences.append(conf)

        merged = " ".join(lines) if mode == "single_line" else "\n".join(lines)
        avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
        return merged, avg_conf
```

**`app/core/template_manager.py`**
```python
import json
from pathlib import Path
from app.models.template import Template

class TemplateManager:
    def save(self, template: Template, filepath: str):
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(template.to_dict(), f, ensure_ascii=False, indent=2)

    def load(self, filepath: str) -> Template:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return Template.from_dict(data)

    def list_templates(self, folder: str) -> list:
        return [str(p) for p in Path(folder).glob("*.json")]
```

**`app/core/batch_processor.py`**
```python
from typing import List, Callable
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.models.template import Template
from app.models.ocr_result import FileResult, FieldResult

class BatchProcessor:
    def __init__(self, pdf_loader: PdfLoader, ocr_engine: OCREngine):
        self.pdf_loader = pdf_loader
        self.ocr = ocr_engine

    def process_one(self, pdf_path: str, template: Template) -> FileResult:
        try:
            fields = {}
            for region in template.regions:
                crop = self.pdf_loader.crop_region(pdf_path, region)
                text, conf = self.ocr.recognize(crop, region.ocr_mode)
                fields[region.field_name] = FieldResult(
                    field_name=region.field_name,
                    text=text,
                    confidence=conf,
                )
            return FileResult(source_file=pdf_path, fields=fields, success=True)
        except Exception as e:
            return FileResult(source_file=pdf_path, fields={}, success=False, error_msg=str(e))

    def process_batch(
        self,
        pdf_paths: List[str],
        template: Template,
        progress_cb: Callable[[int, int, str], None] = None,
    ) -> List[FileResult]:
        results = []
        total = len(pdf_paths)
        for idx, path in enumerate(pdf_paths):
            result = self.process_one(path, template)
            results.append(result)
            if progress_cb:
                progress_cb(idx + 1, total, path)
        return results
```

**`app/core/exporter.py`**
```python
import pandas as pd
from typing import List
from app.models.ocr_result import FileResult

class Exporter:
    def to_excel(self, results: List[FileResult], output_path: str, include_confidence: bool = True):
        rows = []
        for r in results:
            row = {"源文件": r.source_file, "状态": "成功" if r.success else f"失败：{r.error_msg}"}
            for field_name, fr in r.fields.items():
                row[field_name] = fr.text
                if include_confidence:
                    row[f"{field_name}_置信度"] = round(fr.confidence, 3)
            rows.append(row)
        df = pd.DataFrame(rows)
        df.to_excel(output_path, index=False, engine="openpyxl")

    def to_csv(self, results: List[FileResult], output_path: str):
        # 类似实现
        pass
```

**`app/core/coordinate_utils.py`**
```python
def pixel_to_ratio(px: int, py: int, pw: int, ph: int, img_w: int, img_h: int) -> tuple:
    """像素坐标 → 归一化比例"""
    return px / img_w, py / img_h, pw / img_w, ph / img_h

def ratio_to_pixel(rx: float, ry: float, rw: float, rh: float, img_w: int, img_h: int) -> tuple:
    """归一化比例 → 像素坐标"""
    return int(rx * img_w), int(ry * img_h), int(rw * img_w), int(rh * img_h)
```

### 3.5 UI 层核心

**`app/ui/main_window.py`**
```python
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QHBoxLayout, QVBoxLayout,
    QPushButton, QFileDialog, QMessageBox, QTabWidget
)
from PySide6.QtCore import Qt
from app.ui.widgets.pdf_canvas import PdfCanvas
from app.ui.widgets.file_list_panel import FileListPanel
from app.ui.widgets.field_panel import FieldPanel
from app.ui.widgets.result_table import ResultTable
from app.core.pdf_loader import PdfLoader
from app.core.ocr_engine import OCREngine
from app.core.batch_processor import BatchProcessor
from app.core.template_manager import TemplateManager
from app.core.exporter import Exporter
from app.workers.batch_worker import BatchWorker

class MainWindow(QMainWindow):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowTitle(config["app"]["name"])
        self.resize(*config["app"]["window_size"])

        # 核心组件
        self.pdf_loader = PdfLoader(dpi=config["pdf"]["render_dpi"])
        self.ocr_engine = OCREngine(
            lang=config["ocr"]["lang"],
            use_gpu=config["ocr"]["use_gpu"],
        )
        self.processor = BatchProcessor(self.pdf_loader, self.ocr_engine)
        self.template_mgr = TemplateManager()
        self.exporter = Exporter()

        self.results = []
        self._init_ui()
        self._connect_signals()

    def _init_ui(self):
        central = QWidget()
        main_layout = QHBoxLayout(central)

        # 左栏：文件列表
        self.file_panel = FileListPanel()

        # 中栏：PDF 画布（含工具栏）
        center_widget = QWidget()
        center_layout = QVBoxLayout(center_widget)
        self.pdf_canvas = PdfCanvas()
        toolbar = self._create_toolbar()
        center_layout.addWidget(toolbar)
        center_layout.addWidget(self.pdf_canvas, 1)

        # 右栏：字段配置
        self.field_panel = FieldPanel()

        # 底部：结果表格（用 Tab 切换）
        self.tabs = QTabWidget()
        self.tabs.addTab(center_widget, "模板编辑")
        self.result_table = ResultTable()
        self.tabs.addTab(self.result_table, "识别结果")

        main_layout.addWidget(self.file_panel, 1)
        main_layout.addWidget(self.tabs, 4)
        main_layout.addWidget(self.field_panel, 2)

        self.setCentralWidget(central)

    def _create_toolbar(self):
        from PySide6.QtWidgets import QToolBar
        toolbar = QToolBar()
        toolbar.addAction("上传PDF", self.on_upload)
        toolbar.addAction("试识别", self.on_try_ocr)
        toolbar.addAction("批量识别", self.on_batch_run)
        toolbar.addAction("导出Excel", self.on_export)
        toolbar.addSeparator()
        toolbar.addAction("保存模板", self.on_save_template)
        toolbar.addAction("加载模板", self.on_load_template)
        return toolbar

    def _connect_signals(self):
        self.file_panel.file_selected.connect(self.on_file_selected)
        self.pdf_canvas.region_drawn.connect(self.field_panel.add_region)
        self.field_panel.region_changed.connect(self.pdf_canvas.update_regions)
        self.field_panel.region_deleted.connect(self.pdf_canvas.remove_region)

    # ---------- 事件处理 ----------
    def on_upload(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择PDF", "", "PDF Files (*.pdf)")
        if files:
            self.file_panel.add_files(files)
            # 将首份作为模板
            self.on_file_selected(files[0])

    def on_file_selected(self, pdf_path: str):
        image = self.pdf_loader.render_page(pdf_path)
        self.pdf_canvas.load_image(image)

    def on_try_ocr(self):
        template = self.field_panel.build_template()
        current_pdf = self.file_panel.current_file()
        if not current_pdf or not template.regions:
            QMessageBox.warning(self, "提示", "请先上传PDF并框选区域")
            return
        result = self.processor.process_one(current_pdf, template)
        self.field_panel.show_preview_result(result)

    def on_batch_run(self):
        template = self.field_panel.build_template()
        files = self.file_panel.all_files()
        if not files or not template.regions:
            QMessageBox.warning(self, "提示", "请先上传PDF并设置字段")
            return

        self.worker = BatchWorker(self.processor, files, template)
        self.worker.progress.connect(self._on_progress)
        self.worker.finished_all.connect(self._on_batch_done)
        self.worker.start()

    def _on_progress(self, done, total, current_file):
        self.statusBar().showMessage(f"处理中 {done}/{total}: {current_file}")

    def _on_batch_done(self, results):
        self.results = results
        self.result_table.load_results(results)
        self.tabs.setCurrentIndex(1)
        QMessageBox.information(self, "完成", f"共处理 {len(results)} 个文件")

    def on_export(self):
        if not self.results:
            QMessageBox.warning(self, "提示", "尚无识别结果")
            return
        path, _ = QFileDialog.getSaveFileName(self, "导出Excel", "result.xlsx", "Excel (*.xlsx)")
        if path:
            # 如用户在表格里手动编辑过，需同步回 self.results
            self.results = self.result_table.collect_results()
            self.exporter.to_excel(self.results, path)
            QMessageBox.information(self, "成功", f"已导出到 {path}")

    def on_save_template(self):
        path, _ = QFileDialog.getSaveFileName(self, "保存模板", "", "JSON (*.json)")
        if path:
            template = self.field_panel.build_template()
            self.template_mgr.save(template, path)

    def on_load_template(self):
        path, _ = QFileDialog.getOpenFileName(self, "加载模板", "", "JSON (*.json)")
        if path:
            template = self.template_mgr.load(path)
            self.field_panel.load_template(template)
            self.pdf_canvas.update_regions(template.regions)
```

**`app/ui/widgets/pdf_canvas.py`**（关键：PDF 展示 + 框选）
```python
from PySide6.QtWidgets import QGraphicsView, QGraphicsScene, QGraphicsPixmapItem, QGraphicsRectItem
from PySide6.QtGui import QPixmap, QPainter, QPen, QColor, QImage
from PySide6.QtCore import Qt, QRectF, Signal, QPointF
from PIL import Image
import uuid
from app.models.region import Region

class PdfCanvas(QGraphicsView):
    region_drawn = Signal(Region)          # 用户完成框选

    def __init__(self):
        super().__init__()
        self.scene_ = QGraphicsScene()
        self.setScene(self.scene_)
        self.setRenderHint(QPainter.Antialiasing)
        self.setDragMode(QGraphicsView.NoDrag)

        self.pixmap_item = None
        self.img_w = 0
        self.img_h = 0

        self.drawing = False
        self.start_pt = None
        self.temp_rect = None
        self.region_items = {}   # region_id -> QGraphicsRectItem

    def load_image(self, pil_image: Image.Image):
        self.scene_.clear()
        self.region_items.clear()
        self.img_w, self.img_h = pil_image.size
        qimg = QImage(pil_image.tobytes("raw", "RGB"), self.img_w, self.img_h,
                      self.img_w * 3, QImage.Format_RGB888)
        pix = QPixmap.fromImage(qimg)
        self.pixmap_item = self.scene_.addPixmap(pix)
        self.setSceneRect(QRectF(pix.rect()))
        self.fitInView(self.pixmap_item, Qt.KeepAspectRatio)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self.pixmap_item:
            self.drawing = True
            self.start_pt = self.mapToScene(event.pos())
            self.temp_rect = QGraphicsRectItem()
            pen = QPen(QColor("#FF5733"), 2, Qt.DashLine)
            self.temp_rect.setPen(pen)
            self.scene_.addItem(self.temp_rect)
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self.drawing and self.temp_rect:
            cur = self.mapToScene(event.pos())
            rect = QRectF(self.start_pt, cur).normalized()
            self.temp_rect.setRect(rect)
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self.drawing and self.temp_rect:
            self.drawing = False
            rect = self.temp_rect.rect()
            if rect.width() > 5 and rect.height() > 5:
                region = Region(
                    id=str(uuid.uuid4())[:8],
                    field_name=f"字段{len(self.region_items)+1}",
                    x=rect.x() / self.img_w,
                    y=rect.y() / self.img_h,
                    w=rect.width() / self.img_w,
                    h=rect.height() / self.img_h,
                )
                # 正式加入
                pen = QPen(QColor(region.color), 2)
                self.temp_rect.setPen(pen)
                self.region_items[region.id] = self.temp_rect
                self.region_drawn.emit(region)
            else:
                self.scene_.removeItem(self.temp_rect)
            self.temp_rect = None
        super().mouseReleaseEvent(event)

    def update_regions(self, regions: list):
        # 清理所有已有框再重绘
        for item in self.region_items.values():
            self.scene_.removeItem(item)
        self.region_items.clear()

        for r in regions:
            rect = QRectF(r.x * self.img_w, r.y * self.img_h,
                          r.w * self.img_w, r.h * self.img_h)
            item = QGraphicsRectItem(rect)
            item.setPen(QPen(QColor(r.color), 2))
            self.scene_.addItem(item)
            self.region_items[r.id] = item

    def remove_region(self, region_id: str):
        if region_id in self.region_items:
            self.scene_.removeItem(self.region_items[region_id])
            del self.region_items[region_id]

    def wheelEvent(self, event):
        # 滚轮缩放
        factor = 1.15 if event.angleDelta().y() > 0 else 1 / 1.15
        self.scale(factor, factor)
```

**`app/ui/widgets/field_panel.py`**（右栏字段配置）
```python
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QComboBox, QHeaderView, QLabel
)
from PySide6.QtCore import Signal
from app.models.region import Region
from app.models.template import Template

class FieldPanel(QWidget):
    region_changed = Signal(list)          # List[Region]
    region_deleted = Signal(str)           # region_id

    def __init__(self):
        super().__init__()
        self.regions = {}   # id -> Region
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("字段配置"))

        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "识别结果", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_clear = QPushButton("清空所有字段")
        btn_clear.clicked.connect(self.clear_all)
        layout.addWidget(btn_clear)

    def add_region(self, region: Region):
        self.regions[region.id] = region
        row = self.table.rowCount()
        self.table.insertRow(row)

        # 字段名（可编辑）
        self.table.setItem(row, 0, QTableWidgetItem(region.field_name))

        # 类型下拉
        type_combo = QComboBox()
        type_combo.addItems(["text", "number", "date", "email", "phone"])
        type_combo.setCurrentText(region.field_type)
        self.table.setCellWidget(row, 1, type_combo)

        # 识别结果（初始为空）
        self.table.setItem(row, 2, QTableWidgetItem(""))

        # 删除按钮
        btn = QPushButton("删除")
        btn.clicked.connect(lambda _, rid=region.id: self._delete(rid))
        self.table.setCellWidget(row, 3, btn)

        self.table.item(row, 0).setData(256, region.id)  # 存 region_id

    def _delete(self, region_id):
        if region_id in self.regions:
            del self.regions[region_id]
        # 找到并删除对应行
        for row in range(self.table.rowCount()):
            if self.table.item(row, 0).data(256) == region_id:
                self.table.removeRow(row)
                break
        self.region_deleted.emit(region_id)

    def clear_all(self):
        self.regions.clear()
        self.table.setRowCount(0)
        self.region_changed.emit([])

    def build_template(self) -> Template:
        regions = []
        for row in range(self.table.rowCount()):
            rid = self.table.item(row, 0).data(256)
            r = self.regions[rid]
            r.field_name = self.table.item(row, 0).text()
            r.field_type = self.table.cellWidget(row, 1).currentText()
            regions.append(r)
        return Template(name="current", regions=regions)

    def load_template(self, template: Template):
        self.clear_all()
        for r in template.regions:
            self.add_region(r)
        self.region_changed.emit(list(self.regions.values()))

    def show_preview_result(self, file_result):
        for row in range(self.table.rowCount()):
            name = self.table.item(row, 0).text()
            if name in file_result.fields:
                fr = file_result.fields[name]
                item = QTableWidgetItem(fr.text)
                if fr.confidence < 0.7:
                    from PySide6.QtGui import QColor
                    item.setBackground(QColor("#FFE5E5"))
                self.table.setItem(row, 2, item)
```

**`app/ui/widgets/file_list_panel.py`**
```python
from PySide6.QtWidgets import QWidget, QVBoxLayout, QListWidget, QLabel
from PySide6.QtCore import Signal
from pathlib import Path

class FileListPanel(QWidget):
    file_selected = Signal(str)

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("PDF 文件列表"))
        self.list_widget = QListWidget()
        self.list_widget.itemClicked.connect(
            lambda item: self.file_selected.emit(item.data(256))
        )
        layout.addWidget(self.list_widget)
        self.files = []

    def add_files(self, paths: list):
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self.list_widget.addItem(Path(p).name)
                self.list_widget.item(self.list_widget.count()-1).setData(256, p)

    def current_file(self):
        item = self.list_widget.currentItem()
        return item.data(256) if item else None

    def all_files(self):
        return list(self.files)
```

**`app/ui/widgets/result_table.py`**
```python
from PySide6.QtWidgets import QTableWidget, QTableWidgetItem, QHeaderView
from PySide6.QtGui import QColor
from app.models.ocr_result import FileResult, FieldResult
from pathlib import Path

class ResultTable(QTableWidget):
    def __init__(self):
        super().__init__()
        self.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self._results = []

    def load_results(self, results: list):
        self._results = results
        if not results:
            return
        # 收集所有字段名
        field_names = []
        for r in results:
            for fn in r.fields:
                if fn not in field_names:
                    field_names.append(fn)

        headers = ["源文件"] + field_names + ["状态"]
        self.setColumnCount(len(headers))
        self.setHorizontalHeaderLabels(headers)
        self.setRowCount(len(results))

        for row, r in enumerate(results):
            self.setItem(row, 0, QTableWidgetItem(Path(r.source_file).name))
            for col, fn in enumerate(field_names, start=1):
                fr = r.fields.get(fn)
                if fr:
                    item = QTableWidgetItem(fr.text)
                    if fr.confidence < 0.7:
                        item.setBackground(QColor("#FFE5E5"))
                    self.setItem(row, col, item)
            status = "成功" if r.success else f"失败: {r.error_msg}"
            self.setItem(row, len(headers)-1, QTableWidgetItem(status))

    def collect_results(self) -> list:
        """用户在表格中编辑过的值回写到 results"""
        field_names = [self.horizontalHeaderItem(i).text()
                       for i in range(1, self.columnCount()-1)]
        for row, r in enumerate(self._results):
            for col, fn in enumerate(field_names, start=1):
                item = self.item(row, col)
                if item and fn in r.fields:
                    new_text = item.text()
                    if new_text != r.fields[fn].text:
                        r.fields[fn].text = new_text
                        r.fields[fn].manually_edited = True
        return self._results
```

### 3.6 后台线程

**`app/workers/batch_worker.py`**
```python
from PySide6.QtCore import QThread, Signal

class BatchWorker(QThread):
    progress = Signal(int, int, str)       # done, total, current_file
    finished_all = Signal(list)            # List[FileResult]

    def __init__(self, processor, pdf_files, template):
        super().__init__()
        self.processor = processor
        self.pdf_files = pdf_files
        self.template = template

    def run(self):
        def cb(done, total, current):
            self.progress.emit(done, total, current)
        results = self.processor.process_batch(self.pdf_files, self.template, cb)
        self.finished_all.emit(results)
```

### 3.7 工具函数

**`app/utils/image_utils.py`**
```python
from PIL import Image, ImageEnhance, ImageFilter
import cv2
import numpy as np

def preprocess_for_ocr(image: Image.Image, mode: str = "general") -> Image.Image:
    """OCR 前的图像预处理：放大、去噪、对比度增强"""
    # 放大小图
    if min(image.size) < 100:
        image = image.resize((image.size[0]*3, image.size[1]*3), Image.LANCZOS)

    # 转灰度 + 自适应阈值（仅对 general/number 模式）
    if mode == "number":
        arr = np.array(image.convert("L"))
        arr = cv2.adaptiveThreshold(arr, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                    cv2.THRESH_BINARY, 31, 10)
        image = Image.fromarray(arr).convert("RGB")
    else:
        # 轻度增强对比度
        image = ImageEnhance.Contrast(image.convert("RGB")).enhance(1.2)

    return image
```

**`app/utils/logger.py`**
```python
import logging
from pathlib import Path
from datetime import datetime

def setup_logger():
    Path("logs").mkdir(exist_ok=True)
    log_file = f"logs/app_{datetime.now().strftime('%Y%m%d')}.log"
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(),
        ]
    )
```

**`app/utils/config_loader.py`**
```python
import yaml

def load_config(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)
```

**`app/utils/validators.py`**
```python
import re

PATTERNS = {
    "email": r"^[\w\.-]+@[\w\.-]+\.\w+$",
    "phone": r"^1[3-9]\d{9}$",
    "date":  r"^\d{4}[-/年]\d{1,2}[-/月]\d{1,2}日?$",
    "number": r"^-?\d+(\.\d+)?$",
}

def validate(text: str, field_type: str) -> bool:
    if field_type == "text":
        return True
    pat = PATTERNS.get(field_type)
    return bool(re.match(pat, text.strip())) if pat else True
```

### 3.8 依赖文件 `requirements.txt`

```
PySide6>=6.5.0
PyMuPDF>=1.23.0
paddleocr>=2.7.0
paddlepaddle>=2.5.0
Pillow>=10.0.0
opencv-python>=4.8.0
numpy>=1.24.0
pandas>=2.0.0
openpyxl>=3.1.0
PyYAML>=6.0
```

---

## 四、开发顺序建议

1. **Day 1-2**：搭建项目骨架 + `PdfLoader` + `OCREngine` 独立跑通（先用脚本测试）
2. **Day 3-4**：`MainWindow` + `PdfCanvas` + `FileListPanel`，完成上传和显示
3. **Day 5-6**：`FieldPanel` + 框选交互 + 坐标换算
4. **Day 7**：`BatchProcessor` + `BatchWorker` 异步批量处理
5. **Day 8**：`ResultTable` + `Exporter`，完成导出
6. **Day 9**：`TemplateManager` 模板保存/加载
7. **Day 10**：联调、异常处理、日志完善
8. **Day 11-12**：PyInstaller 打包测试

---

## 五、打包命令（PyInstaller）

```bash
pyinstaller --name "PDF_OCR_Tool" \
  --windowed \
  --icon=resources/icons/app.ico \
  --add-data "config.yaml:." \
  --add-data "app/ui/styles/app.qss:app/ui/styles" \
  --collect-all paddleocr \
  --collect-all paddle \
  main.py
```

⚠️ **打包注意**：PaddleOCR 模型文件较大（约 15MB），首次运行会自动下载到用户目录。可在打包前运行一次让模型就位，或提前下载模型文件嵌入资源目录。

---

## 六、关键设计亮点

| 设计 | 优势 |
|------|------|
| **归一化坐标** | 不同 DPI/尺寸 PDF 通用，模板可复用 |
| **OCR 单例** | 避免重复加载 PaddleOCR 模型（加载需数秒） |
| **分层架构** | UI / Worker / Core / Model 解耦，便于测试和替换 |
| **信号槽解耦** | UI 组件之间通过 Signal 通信，无强依赖 |
| **模板 JSON 化** | 方便分享、版本管理、未来云同步 |

---

需要我进一步展开哪部分？例如：
- 🔧 某个具体模块的完整可运行代码
- 📦 PaddleOCR 模型离线打包详细方案  
- 🎨 Qt 样式表（QSS）美化方案
- ⚡ 多进程并发优化（`ProcessPoolExecutor` 版本的 `BatchProcessor`）
- 🧪 单元测试示例
