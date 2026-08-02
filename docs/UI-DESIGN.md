# PDFOCR 双引擎双界面设计说明

## 启动流程

每次启动应用都会强制弹出**引擎选择界面**（GGUF / RapidOCR 两张卡片）：

- 无默认选中，「进入」按钮默认禁用；双击卡片或选中后点「进入」确认。
- Esc / 关闭窗口 = 退出程序，绝不静默带默认值进入。
- 选择结果只写入本次会话的内存配置，**不写回 config.yaml**（每次启动重新选择）。
- `PDFOCR_ENGINE=gguf|rapidocr` 环境变量可直通跳过对话框（自动化/CI/运维用）。

两个引擎是**两个不同的软件形态**，一次会话只启用一个引擎（无热切换）。

## 双窗口概览

| | GGUF 推理操作台 | RapidOCR 文档工作台 |
|---|---|---|
| 窗口类 | `GgufMainWindow`（FluentWindow 侧边导航） | `RapidMainWindow`（MSFluentWindow 顶部标签） |
| 标题 | PDF OCR — 推理操作台 | PDF OCR — 文档工作台 |
| 视觉 | 暗松绿黑 + 黄铜金动作色 + 鼠尾草绿状态色（信号台） | 暖纸底 + 墨色文字 + 档案绿主色（文具档案室） |
| 页面 | 关键字提取 / 识别结果 / 历史记录 / 模型设置 | 工作区 / 识别结果 / 历史记录 |
| 定位 | 本地 VLM 整页推理、关键字批量提取与核对 | 模板框选式文档识别 |

## 快捷键

### GGUF（推理操作台）

| 快捷键 | 动作 |
|---|---|
| Ctrl+O | 上传 PDF 文件 |
| Ctrl+Enter | 提取关键字 |
| Ctrl+S | 保存当前关键字为命名集合 |
| Ctrl+Shift+N | 新建关键字集 |
| Ctrl+Shift+F | 导出关键字汇总 Excel |

### Rapid（文档工作台）

| 快捷键 | 动作 |
|---|---|
| Ctrl+O | 添加 PDF 文件 |
| Ctrl+T | 试识别 |
| Ctrl+Enter | 批量识别 |
| Ctrl+S | 保存模板 |
| Ctrl+Shift+N | 新建模板 |
| Ctrl+Z / Ctrl+Y | 撤销 / 重做框选 |
| Ctrl+Shift+L / Ctrl+Shift+R | 折叠 / 滑出左右面板 |
| Delete | 删除选中字段区域 |
| Space | 快速预览试识别结果 |

## 配置语义

- `config.yaml` 的 `ocr.engine`（`gguf` / `rapidocr`）仅作为自动化兜底：
  交互启动时由引擎选择对话框决定并覆盖内存值，不写盘。
- GGUF 参数（`ocr.gguf.*`：server_path / model_path / mmproj_path / port /
  device / n_gpu_layers / max_tokens / temperature / prompt_type / 滑块等）
  在「模型设置」页编辑：保存并应用写盘、重启引擎进程内重载、
  GPU↔CPU 设备切换需重启程序。
- `appearance.animations_enabled` 由设置对话框（Rapid 外观设置 / GGUF 设置页）
  管理；窗口启动不再覆盖系统动画偏好。

## 会话日志

窗口构造时输出一行会话形态日志，排查问题时一眼定位：

```
Session start | engine=gguf | design=gguf | window=GgufMainWindow
Session start | engine=rapidocr | design=rapid | window=RapidMainWindow
```

## 视觉签名元素（重设计）

- GGUF「信号台」：窗口顶部 2px 引擎状态发光带（初始化=黄铜呼吸 #E0B23C /
  就绪=鼠尾草绿 #8FB573 / 失败=信号红 #E2574C）；深色操作台统计数字使用
  等宽字体（Consolas），像仪表读数。
- Rapid「文具档案室」：PDF 画布框选区域为荧光笔样式（半透明黄填充 +
  #F5C518 描边，黄与档案绿互补）；左右面板带卡片阴影与圆角。

### 色板

GGUF（暗松绿 × 黄铜金）：
`#10150F` 底色 / `#171E16` 面板 / `#202A1E` 浮起 / `#C9A227` 黄铜金动作色 /
`#8FB573` 鼠尾草绿状态色 / `#E9E7D9` 骨白文字。

Rapid（暖纸 × 墨色 × 档案绿）：
`#F6F3ED` 暖纸底 / `#FFFFFF` 卡片 / `#1E7B5C` 档案绿主色 /
`#0E7490` 汽油蓝次级数据色 / `#2A2724` 墨色文字 / `#C77F1D` 警告 /
`#C2423C` 错误。
