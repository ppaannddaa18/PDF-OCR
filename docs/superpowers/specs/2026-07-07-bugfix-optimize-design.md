# Bug 修复 + 性能/显存优化 — 设计文档

日期: 2026-07-07 | 状态: 已批准

## 概述

对 PDFOCR 双模式架构（PaddleOCR-VL-1.6 自动版面解析 + RapidOCR 手动框选）进行全面 bug 修复、性能优化和显存优化。

---

## 一、高优先级 Bug 修复

### B1 — FinanceProcessor 配置路径双层错误
- **文件**: `app/core/finance_processor.py:13-17`
- **问题**: `cfg.get("invoice", {})` 应走 `cfg.get("finance", {}).get("invoice", {})`；validation 同理
- **影响**: `config.yaml` 中 `finance.invoice.keywords` 和 `finance.validation.*` 完全被忽略，始终用硬编码默认值
- **修复**: 修正路径为 `cfg.get("finance", {}).get("invoice", {})` 和 `cfg.get("finance", {}).get("validation", {})`

### B2 — main_window 传入错误的 config 层级 + 每次重复创建
- **文件**: `app/ui/main_window.py:2176-2177`
- **问题**: 每次点击"解析"新建 `FinanceProcessor(self.config)`，且传整个 config 而非 `finance` 子字典
- **修复**: 在 `__init__` 中创建 `self._finance_processor = FinanceProcessor(self.config)` 一次，`_on_page_parsed` 中复用。B1 修复后路径修正自动生效

### B3 — `_find_neighbor` 退步值返回关键词自身
- **文件**: `app/core/finance_processor.py:34-35`
- **问题**: 找不到邻居时 `value = anchor.content`，但 anchor 内容是 "发票号码" 关键词本身，导致字段值=字段名
- **修复**: 用正则 `re.compile(r'[：:]\s*')` 分割 anchor.content，取分割后的第二部分作为值；分割失败则返回空字符串

### B4 — 同名字段识别结果互相覆盖
- **文件**: `app/core/batch_processor.py:88-98`, `app/models/ocr_result.py`, `app/core/exporter.py`, `app/ui/widgets/field_panel.py:327-366`
- **问题**: `FileResult.fields` 以 `field_name` 为 key，多个同名字段（如两个"金额"区域）互相覆盖
- **修复**: `FileResult.fields` 的 key 从 `field_name` 改为 `region_id`；`field_panel.show_preview_result` 和 `Exporter` 同步适配

---

## 二、中优先级 Bug 修复

### B5 — `_extract_elements()` 与 `extract_blocks()` 逻辑重复
- **文件**: `app/core/ocr_engine_paddle.py:301-366` + `app/core/layout_extractor.py:9-75`
- **问题**: 两处独立解析 `overall_ocr_res` + `parsing_res_list`，~70 行重复逻辑，每次推理执行两次
- **修复**: `_extract_elements()` 改为调用 `extract_blocks()` 获取 `List[Block]`，再转换 Block → dict 格式供 `recognize_page` 下游 FieldMatcher 消费

### B6 — `update_region` 频繁重建 handles
- **文件**: `app/ui/widgets/pdf_canvas.py:578-591`
- **问题**: 每次 `update_region` 调用 `_create_handles()`，内部删除 5 个旧 handle + 创建 5 个新 handle + 添加 scene
- **修复**: 首次创建 handles 后，后续只调用 `update_handle_positions()` 移动位置；handles 为空时才创建

### B7 — `_find_neighbor` Y 阈值硬编码
- **文件**: `app/core/finance_processor.py:65`
- **问题**: `abs(by1 - ay1) < 30` 不随图片 DPI 缩放，高分辨率图片上匹配失败
- **修复**: 从 blocks 的 bbox 动态计算中位字符高度，阈值取 `median_line_height * 1.5`，下限 30px

### B8 — VRAM 守卫 + empty_cache 代码重复
- **文件**: `app/core/ocr_engine_paddle.py:174-177,238-248`
- **问题**: `recognize_page` 和 `recognize_page_auto` 各有一份 VRAM 检查 + `empty_cache` 逻辑
- **修复**: 抽取为 `_vram_guard(image_size) -> int` 返回 max_pixels 和 `_post_inference_cleanup()` 处理 `empty_cache`

### B9 — `empty_cache()` 异常捕获过宽
- **文件**: `app/core/ocr_engine_paddle.py:193-196,263-267`
- **问题**: `except Exception` 吞掉所有错误（CPU 模式下 `paddle.device.cuda` 不存在时静默失败）
- **修复**: 改为 `except (OSError, RuntimeError, AttributeError)`，记录 warning

---

## 三、低优先级修复

### B10 — Warmup 后未清理 CUDA 缓存
- **文件**: `app/core/ocr_engine_paddle.py:121-124`
- **修复**: warmup 推理后调用复用的 `_post_inference_cleanup()` 释放临时缓冲区 (~50-200MB)

### B11 — `max_pixels` 上下限优化
- **文件**: `app/core/ocr_engine_paddle.py:299`
- **修复**: 上限从 16M → 8M（8GB 显卡安全）；下限从 1M → 0.5M（避免小图升采样浪费）

### B12 — numpy 转换移出锁外
- **文件**: `app/core/ocr_engine_paddle.py:184,255`
- **修复**: `np.array(image)` 移到 `with self._pipeline_lock:` 之前执行，减少锁持有时间 ~50-200ms

### B13 — 默认配置与 config.yaml 对齐
- **文件**: `app/utils/config_loader.py:105-106`
- **修复**: 默认值 `use_layout_detection` → `True`, `warmup_on_startup` → `True`

### B14 — 死代码清理
- **文件**: `app/ui/widgets/gpu_status.py:87-90`
- **修复**: 删除不会被触发的 `closeEvent` override

---

## 四、性能优化（基于 PaddleOCR-VL 官方文档）

### P1 — `recognize_page` 复用 `recognize_page_auto`
- **文件**: `app/core/ocr_engine_paddle.py:222-292`
- **优化**: 内部调用 `recognize_page_auto` 获取 PageResult，从 blocks 做 FieldMatcher 匹配，消除第二次 JSON 解析
- **风险**: 改动旧识别路径，需保留三级匹配（IoU/就近/关键词）行为不变

### P2 — `vlm_extra_args` 按元素类型分级分辨率（核心 VRAM 优化）
- **文件**: `app/core/ocr_engine_paddle.py`, `app/config.yaml`
- **来源**: 官方文档标注 `min_pixels`/`max_pixels` 是 "single most impactful parameters for VRAM usage"
- **新增配置项**:
  ```yaml
  ocr.paddleocr_vl.vlm_resolution:
    text:    { min_pixels: 262144, max_pixels: 1048576 }   # 256K-1M
    table:   { min_pixels: 524288, max_pixels: 4194304 }   # 512K-4M
    formula: { min_pixels: 524288, max_pixels: 4194304 }
    chart:   { min_pixels: 524288, max_pixels: 4194304 }
    seal:    { min_pixels: 65536,  max_pixels: 262144 }    # 64K-256K
  ```
- **推理时**: 构建 `vlm_extra_args` dict 传入 `pipeline.predict()`

### P3 — `max_new_tokens` 限长
- **文件**: `app/core/ocr_engine_paddle.py:186-189`
- **新增配置项**: `ocr.paddleocr_vl.max_new_tokens: 2048`
- **修复**: `self._pipeline.predict(arr, max_new_tokens=self._max_new_tokens, ...)`

### P4 — `use_tensorrt` + `enable_hpi` 实验性加速
- **文件**: `app/core/ocr_engine_paddle.py`, `app/config.yaml`
- **新增配置项**（默认 false，需 CUDA 11.8 + TensorRT 8.6）:
  ```yaml
  ocr.paddleocr_vl.use_tensorrt: false
  ocr.paddleocr_vl.enable_hpi: false
  ```
- **初始化时**: 传入 `PaddleOCRVL(...)` 构造函数

### P5 — 设置 `min_pixels` 防止小图强制升采样
- **文件**: `app/core/ocr_engine_paddle.py:189`
- **修复**: 推理时传递 `min_pixels=512*512`（约 0.26M，配合 B11 下限）

---

## 五、改动文件汇总

| 文件 | 涉及项 |
|------|--------|
| `app/core/finance_processor.py` | B1, B3, B7 |
| `app/ui/main_window.py` | B2 |
| `app/core/ocr_engine_paddle.py` | B5, B8, B9, B10, B11, B12, P1, P2, P3, P4, P5 |
| `app/ui/widgets/pdf_canvas.py` | B6 |
| `app/core/batch_processor.py` | B4 |
| `app/ui/widgets/field_panel.py` | B4 |
| `app/core/exporter.py` | B4 |
| `app/models/ocr_result.py` | B4 |
| `app/utils/config_loader.py` | B13 |
| `app/config.yaml` | P2, P3, P4 |
| `app/ui/widgets/gpu_status.py` | B14 |

**总计: 11 个文件**

---

## 六、验证

```bash
# 1. 运行所有测试
python -m pytest tests/ -v

# 2. GUI 启动 + GPU 模式 → 引擎就绪
python main.py

# 3. 检查 config.yaml finance 自定义关键词是否生效:
#    设置 finance.invoice.keywords: ["发票号码", "开票日期", "价税合计", "购买方", "销售方"]
#    解析 → 结果面板"字段提取"视图应显示自定义字段

# 4. GPU→RapidOCR→GPU 热切换不崩溃

# 5. 同名字段: 两个"金额"区域 → 批量识别 → 各自应有独立结果

# 6. 代码: B5 后 _extract_elements 不再独立解析 JSON（通过代码审查确认）
```
