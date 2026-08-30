# OCR 解析配置弹窗「显示逻辑」重构设计（主从式五卡）

日期：2026-08-27
范围：`app/ui/widgets/ocr_parse_config_dialog.py` + `tests/ui/widgets/test_ocr_parse_config_dialog.py`
约束：不改引擎 / 主窗口 / 配置键结构；`get_config_patch` 键集合与语义不变；
不动 `defaults()` / 生效值校验 / 预设按钮 / tooltip 文案 / `*` 默认标记。

## 背景

经 tooltip → 联动置灰 → 文案重写三轮增量优化后，显示逻辑仍有结构性缺陷：

1. **支点开关位置错误**：「版面分析」决定 11 个控件是否生效，但只是
   7 个开关之一，淹没在中间卡片——用户看到「未开启版面分析：暂不生效」
   还需跨卡找开关。
2. **依赖组与主开关物理分离**：辅助内容组在卡片 1，主开关在卡片 2，
   依赖关系只能靠文字传递。
3. **两步生效模型不可见**：方向/扭曲矫正需重启引擎、其他即时生效——
   应用前用户无法预知。
4. **卡片命名是引擎视角**（模型参数设置 / 文本检测与识别）。

## 决策

1. **主从式**：「版面分析」提升为顶部「识别模式」卡的主开关，用**互斥
   单选钮**呈现两态——「整页识别（每行文字都带高亮框）/ 版面分析
   （表格结构化，可过滤页眉页脚等）」；说明文字随选中态切换。语义映射
   `use_layout_detection`（配置键、patch 键、值语义不变）。
2. **五卡细分**：识别模式（主开关）/ 识别内容（辅助内容 7 项，依赖版面
   分析）/ 专项识别（图表/印章/图片文字/跨页表格合并，依赖版面分析）/
   文档矫正（方向/扭曲矫正，两种模式均生效）/ 识别质量与效率（采样 3 项
   + 预设，两种模式均生效）。
3. **卡级降级 + 角标**：版面分析未开时，「识别内容」「专项识别」两张卡
   控件整体置灰 + 卡标题行右侧灰字角标「整页模式下未生效」；开启时角标
   消失。原两组底部提示行移除（信息并入角标 + 每项 tooltip 保留生效条件
   说明）。置灰不改配置值，patch 照常输出。
4. **重启徽标 + 按钮区动态提示**：方向/扭曲矫正行内挂小胶囊「重启生效」；
   按钮区上方动态提示「本次修改包含需重启引擎的参数：应用后引擎将自动
   重启」，由两复选框 toggled 驱动、相对**构造时配置**比对（配置已变即
   提示）；应用后引擎重启流程不变（`apply_config` 返回 True → 窗口层后台
   重启管线）。
5. **模式单选钮的 Qt 语义**：autoExclusive 组内不能对选中钮单独
   `setChecked(False)`（Qt 忽略），置否须选中另一枚触发互斥——统一走
   `_set_mode_radio(layout_on)` 助手。
6. **保留不动**：全部 tooltip 文案（含生效条件）、`*` 偏离默认标记、生效值
   校验（`_validate`）、预设按钮、底部悬停提示/图例、`defaults()`、
   `apply_requested`/`_on_apply` 流程。

## 布局（示意）

```
识别模式   ○ 整页识别（每行文字都带高亮框）
          ● 版面分析（表格结构化，可过滤页眉页脚等）
识别内容   [整页模式下未生效]  □页眉 □页眉图片 □页脚 □页脚图片 ☑页码 □脚注 □旁注文本
专项识别   [整页模式下未生效]  ☑图表识别 ☑印章识别 ☑图片文字识别 ☑跨页表格合并
文档矫正   □图片方向矫正 [重启生效]  □图片扭曲矫正 [重启生效]
识别质量与效率  重复抑制强度 1.1 / 图像最小总像素 0 / 图像最大总像素 1605632（官方默认 省显存）
按钮区     [本次修改需重启引擎]  取消 重置 应用
```

## 实现要点

### 1. 模式卡（`_build_ui` 重构）
- 两个 `QRadioButton` 存 `self._mode_radios = {"whole": rb, "layout": rb}`；
  互斥组自动组成；`layout` 选中 ⇔ `use_layout_detection=True`；初始化勾选
  态、`reset_to_defaults`、`_refresh_modified_markers` 均走 `_mode_is_layout()`
  取值（`use_layout_detection` 已从 `_model_switches` 移除）。
- 选项下方灰字说明 QLabel（`self._mode_hint`，挂 `_hints` 统一样式），
  由 `_refresh_layout_dependents` 按选中态填充。

### 2. 五卡构建
- 卡片顺序：模式 → 识别内容 → 专项识别 → 文档矫正 → 质量与效率；
  「模型参数设置」卡拆分：方向/扭曲矫正 → 文档矫正卡；图表/印章/图片
  文字/跨页合并 → 专项识别卡。
- 卡标题行改为 HBox：标题 QLabel + 角标 QLabel（`self._badges` 字典，
  `_section(title, badge_key=...)` 可选挂载）。

### 3. `_refresh_layout_dependents` 改造
- 输入不变（版面分析状态），行为改为：两张依赖卡全部控件 `setEnabled`
  （识别内容 7 项 + 专项识别 4 项）与对应角标 `setVisible`；同时刷新
  `_mode_hint` 说明文案；删除 `_aux_hint/_model_hint` 与对应常量。

### 4. 重启徽标 + `_refresh_apply_hint`
- 方向/扭曲矫正行：QCheckBox + 「重启生效」QLabel 同列（HBox 行包裹）；
  无交互，样式随 `_hints` 灰字。
- `_refresh_apply_hint()`：任一矫正复选框 toggled → 与构造时配置快照
  （`self._init_doc_sw`）比对，有差异则按钮区上方提示 QLabel 显示，否则
  隐藏；初始（构造末尾）与 reset 后经信号自动刷新。

### 5. 信号接线
- 不变原则：构造完成后统一接线；`layout` 单选钮 `toggled` →
  `_refresh_layout_dependents`；全部复选框/单选钮 `toggled` 与数值框
  `valueChanged` → `_refresh_modified_markers`；矫正复选框额外 →
  `_refresh_apply_hint`。

## 测试要点

- 更新：模式态断言改用 `_mode_is_layout()` / 单选钮勾选；仅配
  `block_spotting` 时「版面分析」单选钮选中（I1 回归）；两卡角标两态与
  控件可用性（删除 `_aux_hint/_model_hint` 断言）；`test_correction_
  checkboxes_enabled` 增「重启生效」徽标 ×2 断言；模式「置否」用例统一
  改为选中另一枚单选钮（autoExclusive Qt 语义）。
- 新增：`test_mode_radios_semantics`（互斥/映射/patch 双键）、
  `test_card_badges_toggle`（角标文案与模式说明两态）、
  `test_apply_hint_dynamic`（矫正改动→提示出现/恢复→隐藏/重置→与配置
  不同→显示）、`test_modified_markers_uses_mode_radio`（radio 变动触发表记
  刷新并重置清除）。
- 既有用例保留（tooltips/校验/预设/标记/roundtrip/取消按钮等，仅适配
  模式控件引用方式）。

## 明确不做

向导式重排、隐藏失效项、参数搜索、`paddle_vl_settings_page`
（维持仅弹窗范围）、引擎/配置结构改动。
