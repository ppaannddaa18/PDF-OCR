# OCR 观片台：导出菜单 / 预览右键平移 / 拖拽入队 设计

日期：2026-08-18
范围：main_ocr.py 入口的 OcrMainWindow（paddle_vl 设计）；PdfCanvas 为共享组件，
本次只新增只读模式行为，Rapid 框选模式零变化。

## 需求

1. 「导出」按钮支持三种格式选择（TXT / Markdown / JSON / 全部）。
2. 预览区域右键拖动平移页面（OCR 只读画布当前未接通，底层逻辑已存在）。
3. 支持把本地文档/图片拖入左侧列表加入队列。

## 实现要点

### 块 1 导出菜单（ocr_main_window.py）
- 「导出」按钮点击弹出 RoundMenu（qfluentwidgets，贴合观片台圆角/主题）：
  TXT 文本 / Markdown / JSON / 全部格式。
- `_on_export` 拆为菜单分发 + `_do_export(fmt)`（None=全部三格式）：
  单格式调 `export_txt / export_markdown / export_json` 对应函数；
  无可导出内容/目录取消/失败提示逻辑不变。

### 块 2 预览右键平移（pdf_canvas.py，共享组件只加不改）
- 平移手势已存在（right_dragging + 滚动条位移 + ClosedHandCursor），
  但 `_is_drawing_blocked()`（OCR/GGUF 只读画布）分支提前返回未接通。
- 在 blocked 分支的 press/move/release 三处补右键平移（仅 pixmap_item 存在时）。
- Rapid（非 blocked）行为零变化。

### 块 3 拖拽入队（ocr_file_panel.py + ocr_main_window.py）
- OcrFilePanel `setAcceptDrops(True)`（面板 + 列表，列表经 eventFilter 转发）。
- dragEnter：MIME urls 含白名单扩展名（pdf/png/jpg/jpeg/bmp/tif/tiff）
  → 接受 + 面板高亮（primary 8% 底 + primary 边框）；dragLeave/drop 复位。
- drop：过滤出本地文件路径 → `files_dropped(paths)` 信号。
- 窗口连接 → `queue_files(paths)` + 状态栏「已拖入 N 个文件，点击「解析」开始」，
  维持手动解析模式（与「+ 加文件」一致）。

## 验证

- 新增：导出分发单测（单格式只调对应函数）、只读画布右键平移状态机、
  拖拽 drop 过滤与信号。
- 全量 pytest + 截图目测（导出菜单、拖拽高亮）。