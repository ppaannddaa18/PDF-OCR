# PDF OCR Tool

基于 PaddleOCR 的 PDF 文档批量 OCR 识别桌面应用程序。

## 功能特性

- **PDF 文档管理** - 支持多 PDF 文件批量上传、页面渲染预览
- **可视化框选** - 在 PDF 预览上拖拽绘制识别区域，支持调整、移动、删除
- **模板系统** - 保存/加载框选配置，支持默认模板
- **OCR 识别** - 基于 PaddleOCR 中文识别，支持试识别和批量识别
- **图像预处理** - 旋转、亮度、对比度、锐化等预处理功能
- **结果导出** - 支持 Excel/CSV 格式导出
- **撤销/重做** - 完整的命令模式实现

## 环境要求

- Python 3.8+
- Windows / Linux / macOS

## 安装

1. 克隆仓库
   ```bash
   git clone https://github.com/your-username/pdf-ocr-tool.git
   cd pdf-ocr-tool
   ```

2. 安装依赖
   ```bash
   pip install -r requirements.txt
   ```

3. 运行程序
   ```bash
   python main.py
   ```

## 使用说明

1. **上传 PDF** - 点击上传按钮或拖拽 PDF 文件到列表
2. **框选区域** - 在 PDF 预览上拖拽绘制识别区域
3. **配置字段** - 为每个区域设置字段名称和 OCR 模式
4. **执行识别** - 单文件试识别或批量识别
5. **导出结果** - 导出为 Excel 或 CSV 格式

## 快捷键

| 快捷键 | 功能 |
|--------|------|
| Ctrl+O | 上传 PDF |
| Ctrl+S | 保存模板 |
| Ctrl+T | 试识别 |
| Ctrl+Enter | 批量识别 |
| Delete | 删除选中字段 |
| Ctrl+Z | 撤销 |
| Ctrl+Y | 重做 |

## 配置说明

配置文件 `config.yaml` 主要配置项：

| 配置项 | 说明 | 默认值 |
|--------|------|--------|
| `ocr.lang` | OCR 语言 | `ch` |
| `ocr.use_gpu` | 是否使用 GPU | `false` |
| `batch.max_workers` | 并行线程数 | `4` |
| `export.default_format` | 默认导出格式 | `xlsx` |

## 项目结构

```
PDFOCR/
├── main.py              # 程序入口
├── config.yaml          # 配置文件
├── requirements.txt     # 依赖项
├── app/
│   ├── core/            # 核心业务逻辑
│   │   ├── ocr_engine.py    # OCR 引擎
│   │   ├── pdf_loader.py    # PDF 加载器
│   │   ├── exporter.py      # 导出功能
│   │   └── batch_processor.py # 批量处理
│   ├── ui/              # UI 层
│   │   ├── main_window.py   # 主窗口
│   │   └── widgets/         # UI 组件
│   ├── models/          # 数据模型
│   └── utils/           # 工具函数
├── resources/           # 资源文件
└── tests/               # 单元测试
```

## 技术特点

- **单例模式** - OCR 引擎采用单例，避免重复加载模型
- **异步初始化** - OCR 引擎异步加载，不阻塞 UI
- **LRU 缓存** - PDF 文档缓存、预览结果缓存
- **命令模式** - 支持撤销/重做操作
- **多线程处理** - 批量识别使用线程池并行处理

## 依赖项

- PyQt6 - GUI 框架
- PyQt6-Fluent-Widgets - Fluent Design UI 组件库
- PaddleOCR - OCR 引擎
- PyMuPDF - PDF 处理
- pandas - 数据处理

## 许可证

MIT License
