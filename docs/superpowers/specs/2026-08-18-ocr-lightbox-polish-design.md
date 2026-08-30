# OCR 观片台「就绪态打磨」设计

日期：2026-08-18
范围：`main_ocr.py` 入口的 PaddleOCR-VL 主窗口（OcrMainWindow，设计 `paddle_vl`「观片台」）
约束：Rapid / GGUF 窗口与共享组件的代码零改动。

## 背景

观片台三栏白卡布局已落地。实际运行截图暴露出的问题集中在**空载就绪态**：

1. 主区域空态文案是 PdfCanvas 共享的「上传 PDF 后在此显示」（Rapid 语境，与
   本窗口「选文件→自动解析→逐页浏览」的流程错位）；右栏纯白无引导。
2. FluentWindow 侧导航条（← / ≡ / 文件图标）在单页窗口是死控件，占 48px。
3. 工具按钮 `≡配置/↻/⧉/⇩` 中后三枚符号可识别性差。
4. 启动自动载入 26 条历史文件，全部标「等待·点击重新解析」，淹没本次会话文件。

## 决策

1. 导航：整条隐藏（`navigationInterface.setVisible(False)`，try/except 兜底）。
2. 工具按鈕：全文字标签「配置 / 重试 / 复制 / 导出」（secondary_qss），
   「+ 加文件」主蓝 primary_qss 不变。
3. 空态：OcrDocView 自建**两步引导卡**替换画布空态；右栏占位说明。
4. 队列：会话文件 / 历史记录分组，历史默认折叠，会话优先置顶。
5. 细节：未选文件时页码药丸与 `/总页` 置灰。

## 实现要点

### 块 1 导航隐藏（ocr_main_window.py）
`_register_sub_interfaces`：switchTo 后试 `self.navigationInterface.setVisible(False)`。
FluentWindow 的 hBoxLayout 不分配空间给隐藏控件 → 工作区全宽。截图验证无留白。

### 块 2 工具按钮文字化（ocr_main_window.py）
`_create_source_bar` 四枚工具钮 text 改为「配置」「重试」「复制」「导出」，
tooltip 保留；间距/高度不变。

### 块 3 两步引导卡（ocr_result_views.py + ocr_main_window.py）
- `OcrDocView` 增加引导层 `guide_overlay`（覆盖整个 splitter 前的 QWidget，
  中央垂直排布：标题 + 两步文本 + 副行）。
- `show_guide(message=None)` / `hide_guide()`；`show_page()` 时自动 hide_guide。
- 引导卡显示期间隐藏画布自带的 empty state（`canvas._hide_empty_state()`，
  同库私有方法，本窗口专属逻辑）。
- 右栏：`text_browser` 为空时显示占位 QLabel「识别文本将显示在这里」。
- 窗口侧：`_reset_view_after_clear` 与未选文件路径统一 `show_guide()`。
- 文案（冷蓝口吻、主动语态）：
  - 主区标题：选择文件开始识别
  - ① 点击「+ 加文件」添加文档
  - ② 点击左侧文件名，自动解析并逐页浏览
  - 右栏：识别文本将显示在这里 / 右上角切「JSON」可看原始结构

### 块 4 会话/历史分组（ocr_file_panel.py + ocr_main_window.py）
- `OcrFilePanel.add_file(path, history=False)` 记录分组。
- 展示层：单一 QListWidget，重绘式管理（`_rebuild()`）：
  - 顶部不可选标题行「本次会话 (N)」
  - 会话文件按加入顺序排列
  - 「历史记录 (M) ▸/▾」标题行，默认折叠（不显示历史 item）
- 数据层 `_items`/`_status` 按 fid 存 path/meta/status，重绘时同步刷新 item 引用。
- 公共 API 语义保持：`paths()`、`file_id_by_path`、`selected_path`、`select_file`、
  `set_status`、`remove_file`、`clear`、`clear_requested`/`file_selected`/
  `file_remove_requested` 信号、右键菜单「删除该文件」。
- `_restore_history` 以 `history=True` 加入；窗口 `add_files` 默认会话文件。
- 计数角标显示**本次会话数**。

### 块 5 页码置灰（ocr_main_window.py）
`_set_page_enabled(active)`：无文件/单页时页码与 `/总页` 用 text_disabled，
有页时 text_primary / text_secondary；细线仅在 >1 页时显示。

## 验证

- 新增 OcrFilePanel 分组单测（标题行、折叠、会话优先、历史不占 paths）。
- 全量 pytest（len ~695）无回归。
- offscreen 截图经视觉模型复核结构。
- 说明：offscreen 环境缺 CJK 字体产生的方块为环境伪影，真实桌面不受影响。
## 追加：导出菜单 / 右键平移 / 拖拽上传（2026-08-18 第二轮）

范围约束：仅 main_ocr.py 入口的窗口与**OCR 独占组件**（ocr_main_window /
ocr_file_panel / ocr_result_views）；pdf_canvas.py 等共享文件零改动，
Rapid / GGUF 界面与行为不受任何影响。

### 块 1 导出菜单（ocr_main_window.py）
「导出」按钮点击 → QMenu：TXT 文本 / Markdown / JSON / 全部格式。
`_on_export` 拆出 `_do_export(fmt)`，单格式调对应 export_* 函数，
全部格式保持现状三选一导出。

### 块 2 预览右键平移（ocr_result_views.py，不动 pdf_canvas.py）
PdfCanvas 底层已有滚动条位移平移，但只读画布（OCR 窗口）未接通且
不能改共享文件 → OcrDocView 给 `canvas.viewport()` 安装事件过滤器：
- 右键按下（有图时）：记录起点 + ClosedHand 光标，吞掉事件
- 右键移动：滚动条按位移反向平移
- 右键释放：复位光标与状态
- 左键/其他事件一律放行（return False），画布原有行为不变

### 块 3 拖拽文件上传（ocr_file_panel.py + ocr_main_window.py）
OcrFilePanel setAcceptDrops：
- dragEnter：接受本地文件 URL（扩展名白名单与「+ 加文件」一致），
  列表区 accent 色 8% 高亮；dragLeave 复位
- drop：解析路径 → `files_dropped(paths)` 信号 → 窗口 queue_files +
  提示「已拖入 N 个文件，点击「解析」开始」（维持手动解析模式）
