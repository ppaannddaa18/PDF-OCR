# Bug 修复 — 全面审计设计文档

日期: 2026-07-07 | 状态: 草案

## 概述

对 PDFOCR 项目进行全面功能/UI bug 审计，经三个独立代理并行审查核心层、UI 层、配置/模型/工具层，发现 **70 个 bug**。按严重程度分为 Critical(5)、High(6)、Medium(25)、Low(34)。

---

## 一、Critical（5个）— 崩溃/数据丢失

### C1 — `_build_paddlex_config` 硬编码 pipeline 名称

- **文件**: `app/core/ocr_engine_paddle.py:127`
- **问题**: `load_pipeline_config("PaddleOCR-VL-1.6")` 硬编码，不随 `self._model_name` 变化。换模型（如 PP-DocBee-2B）时 crash
- **修复**: 从 `self._model_name` 派生 pipeline 名称，或用模型名→pipeline 名的映射

### C2 — 历史文件损坏时静默清空

- **文件**: `app/utils/history_manager.py:59`
- **问题**: `except Exception: self._cached_history = []` 吞掉所有加载错误，清空历史
- **修复**: log 异常，备份损坏文件，返回空历史；不覆盖损坏文件

### C3 — `_on_ocr_ready` 窗口销毁后 use-after-free

- **文件**: `app/ui/main_window.py:144`
- **问题**: `QTimer.singleShot(0, self._on_ocr_ready)` 在后台线程完成时触发。用户可能在初始化完成前关闭窗口，timer 回调时 C++ MainWindow 对象已销毁
- **修复**: `closeEvent` 中递增 `_init_gen`，`_on_ocr_ready` 检查 gen 有效性；添加 `_destroyed` 标志

### C4 — History 反序列化 KeyError 丢失全部历史

- **文件**: `app/utils/history_manager.py:175`
- **问题**: `fd["text"]` 直接索引，历史 JSON 缺字段时 KeyError → 外层 except Exception 清空历史
- **修复**: 用 `fd.get("text", "")` 和 `fd.get("confidence", 0.0)`，所有字段加默认值

### C5 — History 无线程锁竞态损坏

- **文件**: `app/utils/history_manager.py:37-38, 65-67`
- **问题**: `_cached_history` 和 `_dirty` 无锁保护。后台线程 `add_record` 可能与 `_load_history`/`_save_history` 并发
- **修复**: 添加 `threading.Lock()` 保护所有 `_cached_history` 读写

---

## 二、High（6个）— 严重功能异常/显存浪费

### H1 — `app/config.yaml` precision 错误为 fp32

- **文件**: `app/config.yaml:29`
- **问题**: `precision: fp32` 而非 `fp16` → 模型推理速度减半，显存翻倍 (~4GB vs ~2GB)
- **修复**: 改为 `precision: fp16`

### H2 — 引擎默认值覆盖 config 配置

- **文件**: `app/core/ocr_engine_paddle.py:86-87`
- **问题**: `use_layout_detection` 和 `warmup_on_startup` 的 `.get()` 默认值分别为 `True` 和 `True`，但 config 和 config_loader 默认值已改为 `False`
- **修复**: 引擎默认值改为 `False`

### H3 — 后台线程与主线程竞态访问 PIL Image

- **文件**: `app/ui/main_window.py:2143-2145`
- **问题**: `recognize_page_auto(self._current_page_image)` 在后台线程访问 PIL Image，主线程可能同时修改（预处理变更）
- **修复**: 调度前复制 image: `page_image = self._current_page_image.copy()`，传副本给线程

### H4 — 清除历史后 detail_widget 永久隐藏

- **文件**: `app/ui/widgets/history_panel.py:126-131`
- **问题**: `_on_clear_history` 隐藏了 `detail_widget`，但 `_on_item_clicked` 不重新显示
- **修复**: `_on_item_clicked` 开始时 `self.detail_widget.setVisible(True)`

### H5 — `max_vram_gb`/`min_free_vram_gb` 引擎默认值与 config 不一致

- **文件**: `app/core/ocr_engine_paddle.py:108-109`
- **问题**: 引擎默认 `max_vram_gb=7.0` (config 为 `7.8`)、`min_free_vram_gb=0.5` (config 为 `0.1`)
- **修复**: 引擎默认值改为 `7.8` 和 `0.1`

### H6 — 取消时双信号发射致 UI 状态混乱

- **文件**: `app/workers/batch_worker.py:43-46`
- **问题**: 取消时同时 emit `cancelled` + `finished_all`，两个 slot 同时执行
- **修复**: 取消时只 emit `cancelled`，不再 emit `finished_all`

---

## 三、Medium（25个）

### 核心层（13个）
- **M1** — `ocr_engine_paddle.py:253-255`: VRAM 耗尽静默返回空 PageResult，无法区分"空页"和"资源不足"
- **M2** — `ocr_engine_paddle.py:360`: `empty_cache()` 多线程竞态，一个线程回收显存影响另一线程推理
- **M3** — `ocr_engine.py:36,39-44`: `config.setdefault` 突变调用者 config，device/precision 泄漏
- **M4** — `batch_processor.py:108-131`: RapidOCR 路径绕过 `recognize_page()`，match_level 始终为 0
- **M5** — `batch_processor.py:197,234`: `future.result()` 异常传播，results 含 None 条目
- **M6** — `field_matcher.py:157,168`: Y 轴容差硬编码 20px，不随 DPI 缩放
- **M7** — `field_matcher.py:72-76`: 关键词匹配置信度伪造为 0.5
- **M8** — `layout_extractor.py:58-65`: 多边形坐标（>4 元素）被错误当作完整 bbox
- **M9** — `table_extractor.py:56-58`: `dropna` 误删全空但合法的列
- **M10** — `pdf_loader.py:49-89`: `fitz.open` 文件 I/O 在锁内执行，阻塞所有线程
- **M11** — `pdf_loader.py:107-131`: `shutdown` 后 `clear_cache` 重建 ThreadPoolExecutor，资源泄漏
- **M12** — `finance_processor.py:26-39`: 关键词子串匹配无词边界，"日期"匹配"出生日期"等
- **M13** — `template_manager.py:11-14`: 模板文件损坏/无效时无错误处理，直接 crash

### UI 层（6个）
- **M14** — `main_window.py:1993-2009`: 引擎重初始化 TOCTOU 竞态，旧引擎可能被 unload 后仍被调用
- **M15** — `main_window.py:1973-1981,276`: 引擎切换后 `self.processor` 持旧引擎引用至初始化完成
- **M16** — `main_window.py:494-499`: 双向滚动同步可能振荡
- **M17** — `widgets/field_panel.py:254-257`: 字段类型修改不持久化，切换文件或退出时丢失
- **M18** — `main_window.py:2206-2253`: `closeEvent` 不保存当前 PDF 配置
- **M19** — `main_window.py:1970-1971`: 热切换引擎不写入 config.yaml，重启后恢复

### 配置层（6个）
- **M20** — `history_manager.py:173-178`: `region_id` 在历史恢复中丢失
- **M21** — `lru_cache.py:126-136`: `contains()` 对过期条目不删除，内存泄漏
- **M22** — `lru_cache.py:138-156`: `keys()/values()/items()` 忽略 TTL
- **M23** — `batch_worker.py:20,40`: `_completed_results` 跨批次累积
- **M24** — `validators.py:74-85`: 日期归一化破坏格式区分能力
- **M25** — `ocr_engine.py:28-29` vs `ocr_engine_paddle.py:108`: `max_vram_gb` 双层默认值不一致

---

## 四、Low（34个）— 死代码/类型/维护性

### 核心层（16个）
- L1 — `ocr_engine_paddle.py:258`: 死 isinstance 检查（参数已类型标注）
- L2 — `batch_processor.py:93-97,120-124`: FieldResult.field_name 与 dict key 不一致
- L3 — `batch_processor.py:93,120`: 空 field_name 无保护
- L4 — `pdf_loader.py:46`: 页面大小估算常数不准确
- L5 — `pdf_loader.py:181`: `callable` 应为 `Callable`
- L6 — `pdf_loader.py:52-59`: access_time 从未更新，死数据
- L7 — `field_matcher.py:183`: 空 keyword 匹配一切
- L8 — `layout_extractor.py:37`: `float()` 转换无异常处理
- L9 — `finance_processor.py:66`: O(n log n) 排序计算中位数
- L10 — `exporter.py:8-17,26-35`: 行构建逻辑重复
- L11 — `batch_processor.py:84`: 链式 `.get()` 遇到 None 中间层崩溃
- L12 — `ocr_engine_paddle.py:338-342`: 8M 上限不随实际 VRAM 变化
- L13 — `ocr_engine_rapid.py:31-34`: 双检锁没有 volatile 保障
- L14 — `layout_extractor.py:37`: rec_score 转换异常
- L15 — `table_extractor.py:56-58`: 多余的 dropna
- L16 — `batch_processor.py:93,120`: 空 field_name

### UI 层（4个）
- L17 — `widgets/file_list_panel.py:168-180`: QTimer 在 panel 隐藏后仍可能触发
- L18 — `main_window.py:494-499`: `scroll_to` 无场景矩形非空保护
- L19 — `main_window.py:158,1377`: LRU 缓存 50 个 FileResult 内存占用
- L20 — `main_window.py:206-234`: QShortcut 在 field panel 失焦时不触发

### 配置层（14个）
- L21 — `history_manager.py:59`: silent except 范围过大
- L22 — `history_manager.py:37-38`: 无锁
- L23 — `command_history.py:117`: max_size 无校验
- L24 — `image_utils.py:75-76`: 小缓存 + 无意义的三整数乘法缓存
- L25 — `config_loader.py:105`: `use_layout_detection` 默认 `True`（与 config 不同步）
- L26 — `config.yaml`: `export.include_source_file` 死配置
- L27 — `config.yaml` vs `app/config.yaml`: `finance`/`layout_visualization` 段缺失
- L28 — `config_loader.py:60-78`: 仅检查顶层类型
- L29 — `main.py:48` vs `main_window.py:93`: engine 默认值不一致
- L30 — `config_loader.py:53-55`: 环境变量覆盖不完整
- L31 — `config_loader.py:105`: precision 默认值
- L32 — `region.py:7-14`: docstring 丢失
- L33 — `ocr_result.py:19`: fields key 与 field_name 分裂
- L34 — `result_table.py:162-163`: 编辑结果时 region_id 丢失

---

## 五、改动文件汇总

| 文件 | 涉及项 |
|------|--------|
| `app/core/ocr_engine_paddle.py` | C1, H2, H5, M1, M2, L1, L12 |
| `app/core/ocr_engine.py` | M3, M25, L29 |
| `app/core/batch_processor.py` | M4, M5, L2, L3, L11, L16 |
| `app/core/field_matcher.py` | M6, M7, L7 |
| `app/core/layout_extractor.py` | M8, L8, L14 |
| `app/core/table_extractor.py` | M9, L15 |
| `app/core/finance_processor.py` | M12, L9 |
| `app/core/pdf_loader.py` | M10, M11, L4, L5, L6 |
| `app/core/template_manager.py` | M13 |
| `app/core/exporter.py` | L10 |
| `app/core/ocr_engine_rapid.py` | L13 |
| `app/ui/main_window.py` | C3, H3, M14, M15, M16, M18, M19, L18, L19, L20 |
| `app/ui/widgets/history_panel.py` | H4 |
| `app/ui/widgets/field_panel.py` | M17 |
| `app/ui/widgets/file_list_panel.py` | L17 |
| `app/ui/widgets/layout_visualizer.py` | M16 相关 |
| `app/workers/batch_worker.py` | H6, M23 |
| `app/utils/history_manager.py` | C2, C4, C5, M20, L21, L22 |
| `app/utils/lru_cache.py` | M21, M22 |
| `app/utils/config_loader.py` | L25, L28, L30, L31 |
| `app/utils/validators.py` | M24 |
| `app/utils/command_history.py` | L23 |
| `app/utils/image_utils.py` | L24 |
| `app/models/region.py` | L32 |
| `app/models/ocr_result.py` | L33 |
| `app/config.yaml` | H1 |
| `config.yaml` | L26, L27 |
| `app/utils/history_manager.py` | L33 |

---

## 六、验证

```bash
# 1. 运行全部测试
python -m pytest tests/ -v

# 2. GUI 启动 — 所有功能正常
python main.py

# 3. 历史功能: 添加记录 → 重启 → 恢复正确
# 4. 引擎切换: GPU→RapidOCR→GPU 三次不崩溃
# 5. 取消批量: 进度条消失，不双弹窗
# 6. 同名字段: 两个金额区域 → 各自有独立结果
# 7. 关闭窗口: 配置保存，下次启动恢复
```
