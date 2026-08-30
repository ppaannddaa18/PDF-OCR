"""解析配置弹窗（观片台形态：卡片分组 + token 化提示/按钮）

方向/扭曲矫正是 PaddleOCRVL 构造期参数：开启会加载 DocPreprocessor 子
管线（额外显存占用），修改后需重启引擎生效（窗口层 apply_config 返回
True 时自动重启）。

UX 联动：版面分析关闭时置灰依赖它的控件——辅助内容解析组与图表/印章/
图片文字识别、跨页表格合并（整页模式无布局标签、不生效，勾选值保留）；
应用前按生效值校验像素上下限（0 = 官方回退）；偏离 defaults() 的参数
显示名追加「 *」。
"""
from PyQt6.QtCore import pyqtSignal
from PyQt6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                             QCheckBox, QDoubleSpinBox, QSpinBox,
                             QPushButton, QLabel, QFrame, QMessageBox,
                             QRadioButton, QWidget)

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.button_style import primary_qss, secondary_qss

# 依赖版面分析的两张卡的角标（版面分析未启用时显示）
_BADGE_TEXT = "整页模式下未生效"

# 辅助内容标签 → (显示名, 默认恢复解析?)
_AUX_ITEMS = [
    ("header", "页眉", False),
    ("header_image", "页眉图片", False),
    ("footer", "页脚", False),
    ("footer_image", "页脚图片", False),
    ("number", "页码", True),
    ("footnote", "脚注", False),
    ("aside_text", "旁注文本", False),
]

# 模型参数开关：配置键 → (显示名, 默认值)。
# 注意剔除「版面分析」（use_layout_detection）——它是模式主开关，见模式卡。
_MODEL_SWITCHES = [
    ("use_doc_orientation_classify", "图片方向矫正", False),
    ("use_doc_unwarping", "图片扭曲矫正", False),
    ("use_chart_recognition", "图表识别", True),
    ("use_seal_recognition", "印章识别", True),
    ("use_ocr_for_image_block", "图片文字识别", True),
    ("merge_layout_blocks", "跨页表格合并", True),
]

# 参数悬停说明（tooltip）：配置键/标签 → 使用者向文案
_TOOLTIPS = {
    # ── 辅助内容（勾选 = 保留；未勾选 = 识别前忽略；仅版面分析开启时生效） ──
    "header": "页眉文字（页面顶部的标题或备注）。\n"
              "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
              "仅在开启「版面分析」后生效",
    "header_image": "页眉里的图片。\n"
                    "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
                    "仅在开启「版面分析」后生效",
    "footer": "页脚文字（页面底部的落款、连续说明等）。\n"
              "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
              "仅在开启「版面分析」后生效",
    "footer_image": "页脚里的图片。\n"
                    "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
                    "仅在开启「版面分析」后生效",
    "number": "页码。\n"
              "默认勾选（保留页码）；不勾选 = 识别前忽略。\n"
              "仅在开启「版面分析」后生效",
    "footnote": "脚注（正文下方的小字注释）。\n"
                "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
                "仅在开启「版面分析」后生效",
    "aside_text": "旁注文本（页面边栏、空白处的注释）。\n"
                  "勾选 = 保留在识别结果里；不勾选 = 识别前忽略。\n"
                  "仅在开启「版面分析」后生效",
    # ── 模型参数 ──
    "use_doc_orientation_classify": "扫描件歪斜或倒置时自动转正（0/90/180/270°），"
                                    "方向不对的文字更容易识别。\n"
                                    "开启会加载文档预处理模块（额外占用显存），"
                                    "修改后需重启引擎",
    "use_doc_unwarping": "弯曲、褶皱的扫描件先自动展平再识别。\n"
                         "开启会加载文档预处理模块（额外占用显存），"
                         "修改后需重启引擎",
    "whole_page": "整页一次识别（默认）：每行文字都会带高亮框。\n"
                  "辅助内容过滤、图表/印章/图片识别、跨页表格合并均不生效；\n"
                  "如需这些功能请切换到「版面分析」",
    "use_layout_detection": "识别前先做版面分析，把页面按表格/图表/文本/图片分开处理："
                            "表格识别更结构化，页眉页脚等辅助内容才能过滤。\n"
                            "关闭 = 整页一次识别（每行文字都会带高亮框）。\n"
                            "注意：辅助内容过滤、图表/印章/图片识别、跨页表格合并"
                            "都依赖本开关",
    "use_chart_recognition": "图表（柱状图、折线图等）用专用识别方式。\n"
                             "不勾选 = 图表区域直接忽略、不出现在结果里。\n"
                             "仅在开启「版面分析」后生效",
    "use_seal_recognition": "印章（公章、发票章等）用专用识别方式。\n"
                            "不勾选 = 印章区域直接忽略。\n"
                            "仅在开启「版面分析」后生效",
    "use_ocr_for_image_block": "图片（插图、页眉图、页脚图等）里的文字用 OCR 识别。\n"
                               "不勾选 = 这些图片整体忽略。\n"
                               "仅在开启「版面分析」后生效",
    "merge_layout_blocks": "同一表格跨页时合并为一个完整表格。\n"
                           "仅在开启「版面分析」后生效",
    # ── 文本检测与识别 ──
    "repetition_penalty": "防止识别结果陷入同一句的重复循环（既慢又乱码）。\n"
                          "取值越大抑制越强；0 或 1.0 = 不干预（官方行为）。\n"
                          "一般用 1.1",
    "spotting_min_pixels": "太小的文字块会被放大后再识别（太小看不清）。\n"
                           "0 = 官方默认值 112896，一般无需修改",
    "spotting_max_pixels": "太大的整页/文字块会先缩小再识别，控制显存占用。\n"
                           "0 = 官方默认 1605632；显存紧张可调低（如 1048576），"
                           "但文字缩小时小字识别会变差，预览高亮框容易偏移（坐标不准），"
                           "建议保持默认",
}


class OcrParseConfigDialog(QDialog):
    """解析配置弹窗：应用 → apply_requested(patch)；重置 → 恢复默认"""

    apply_requested = pyqtSignal(dict)

    def __init__(self, config: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("解析配置")
        self.setMinimumWidth(560)
        pv = config.get("ocr", {}).get("paddle_vl", {})
        # 构造时矫正开关快照：按钮区「需重启」动态提示的比对基准
        self._init_doc_sw = (
            bool(pv.get("use_doc_orientation_classify", False)),
            bool(pv.get("use_doc_unwarping", False)))
        self._build_ui(pv)
        self.apply_theme()
        ThemeManager.register_refresh_callback(self.apply_theme)

    def apply_theme(self):
        """设计刷新回调：弹窗底 + 卡片分组 + 标题/提示 token 化"""
        t = ThemeManager
        self.setObjectName('cfgDialog')
        self.setStyleSheet(
            f"QDialog#cfgDialog {{ background: "
            f"{t.get_color('bg_primary')}; }}"
            f"QFrame#cfgCard {{ background: {t.get_color('bg_surface')};"
            f"border: 1px solid {t.get_color('border')};"
            f"border-radius: {t.get_radius('md')}px; }}")
        for lbl in self._titles:
            lbl.setStyleSheet(
                f"color: {t.get_color('text_primary')};"
                f"font-size: 13px; font-weight: 600;")
        for h in self._hints:
            h.setStyleSheet(
                f"color: {t.get_color('text_secondary')};"
                f"font-size: 11px;")

    # —— 构建 ——
    def _section(self, title: str, badge_key: str = None):
        """卡片分组：白卡 + 标题行（可选角标）+ 表单区（QFormLayout 语义）。

        badge_key 非空时标题右侧挂角标（存 _badges，由
        _refresh_layout_dependents 按版面分析状态显隐）。
        """
        card = QFrame()
        card.setObjectName('cfgCard')
        lay = QVBoxLayout(card)
        lay.setContentsMargins(16, 12, 16, 14)
        lay.setSpacing(8)
        title_row = QHBoxLayout()
        title_row.setSpacing(8)
        lbl = QLabel(title)
        self._titles.append(lbl)
        title_row.addWidget(lbl)
        if badge_key:
            badge = QLabel(_BADGE_TEXT)
            badge.setVisible(False)
            self._hints.append(badge)
            title_row.addWidget(badge)
            self._badges[badge_key] = badge
        title_row.addStretch(1)
        lay.addLayout(title_row)
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setVerticalSpacing(6)
        lay.addLayout(form)
        return card, form

    def _add_tip_row(self, form, key: str, name: str, widget, tip: str):
        """带悬停说明的表单行：参数名与控件均可查看 tooltip；
        行标签记入 _num_rows 供偏离默认标记刷新"""
        lbl = QLabel(name)
        lbl.setToolTip(tip)
        widget.setToolTip(tip)
        form.addRow(lbl, widget)
        self._num_rows[key] = (name, lbl)

    def _build_ui(self, pv: dict):
        self._titles = []
        self._hints = []
        self._badges = {}
        self._num_rows = {}
        # 识别模式：主开关（互斥单选）——「版面分析」开启 = 逐块模式。
        # 兼容读点：既有设置页（paddle_vl_settings_page）与引擎读写的是
        # block_spotting（与 use_layout_detection 等价），任一开启即选中
        layout_on = bool(pv.get("use_layout_detection", False)) or \
            bool(pv.get("block_spotting", False))
        self._mode_radios = {}
        mode_card, mform = self._section("识别模式")
        self._mode_radios["whole"] = QRadioButton("整页识别")
        self._mode_radios["layout"] = QRadioButton("版面分析")
        self._mode_radios["whole"].setToolTip(_TOOLTIPS["whole_page"])
        self._mode_radios["layout"].setToolTip(_TOOLTIPS["use_layout_detection"])
        mform.addRow(self._mode_radios["whole"])
        mform.addRow(self._mode_radios["layout"])
        self._mode_hint = QLabel("")  # 选项说明：随选中态切换
        self._hints.append(self._mode_hint)
        mform.addRow(self._mode_hint)
        self._set_mode_radio(layout_on)
        # 识别内容卡：辅助内容过滤（版面分析未开时整卡降级）
        ignore = set(pv.get(
            "markdown_ignore_labels",
            [label for label, _, default in _AUX_ITEMS if not default]))
        self._aux_checks = {}
        aux_card, form = self._section("识别内容", badge_key="aux")
        for label, name, _ in _AUX_ITEMS:
            chk = QCheckBox(name)
            chk.setChecked(label not in ignore)
            chk.setToolTip(_TOOLTIPS[label])
            self._aux_checks[label] = chk
            form.addRow(chk)
        # 专项识别卡：图表/印章/图片文字/跨页表格合并（版面分析未开时整卡降级）
        self._model_switches = {}
        special_card, sform = self._section("专项识别", badge_key="special")
        for key, name, default in _MODEL_SWITCHES:
            if key in ("use_doc_orientation_classify", "use_doc_unwarping"):
                continue
            chk = QCheckBox(name)
            chk.setChecked(bool(pv.get(key, default)))
            chk.setToolTip(_TOOLTIPS[key])
            self._model_switches[key] = chk
            sform.addRow(chk)
        # 文档矫正卡：方向/扭曲矫正 + 「重启生效」徽标（两种模式均生效）
        self._correction_checks = {}
        corr_card, cform = self._section("文档矫正")
        for key, name, default in _MODEL_SWITCHES:
            if key not in ("use_doc_orientation_classify", "use_doc_unwarping"):
                continue
            chk = QCheckBox(name)
            chk.setChecked(bool(pv.get(key, default)))
            chk.setToolTip(_TOOLTIPS[key])
            self._correction_checks[key] = chk
            chk.toggled.connect(self._refresh_apply_hint)
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(0, 0, 0, 0)
            row_lay.setSpacing(6)
            row_lay.addWidget(chk)
            restart = QLabel("重启生效")
            self._hints.append(restart)
            row_lay.addWidget(restart)
            row_lay.addStretch(1)
            cform.addRow(row)
        # 采样参数组
        self._rep_spin = QDoubleSpinBox()
        self._rep_spin.setRange(0.0, 2.0)
        self._rep_spin.setSingleStep(0.1)
        self._rep_spin.setDecimals(1)  # 显示 1.1 而非 1.10
        self._rep_spin.setValue(float(pv.get("repetition_penalty", 1.1) or 0))
        self._min_px = QSpinBox()
        self._min_px.setRange(0, 100_000_000)
        self._min_px.setValue(int(pv.get("spotting_min_pixels", 0) or 0))
        self._max_px = QSpinBox()
        self._max_px.setRange(0, 100_000_000)
        self._max_px.setValue(int(pv.get("spotting_max_pixels", 1605632) or 1605632))
        self._max_px.setToolTip(_TOOLTIPS["spotting_max_pixels"])
        # 最大像素预设：官方默认（识别最准）/ 省显存（8GB 卡显存紧张时）
        max_w = QWidget()
        max_lay = QHBoxLayout(max_w)
        max_lay.setContentsMargins(0, 0, 0, 0)
        max_lay.setSpacing(4)
        for text, val, tip in (
                ("官方默认", 1605632, "填入 1605632（官方默认值，识别最准）"),
                ("省显存", 1048576, "填入 1048576（更省显存，但小字识别变差、高亮框易偏移）")):
            b = QPushButton(text)
            b.setFlat(True)
            b.setFixedHeight(22)
            b.setToolTip(tip)
            b.clicked.connect(lambda _=False, v=val: self._max_px.setValue(v))
            max_lay.addWidget(b)
        max_lay.addWidget(self._max_px)
        sample_card, sform = self._section("识别质量与效率")
        self._add_tip_row(sform, "repetition_penalty", "重复抑制强度",
                          self._rep_spin, _TOOLTIPS["repetition_penalty"])
        self._add_tip_row(sform, "spotting_min_pixels", "图像最小总像素数",
                          self._min_px, _TOOLTIPS["spotting_min_pixels"])
        self._add_tip_row(sform, "spotting_max_pixels", "图像最大总像素数",
                          max_w, _TOOLTIPS["spotting_max_pixels"])
        # 按钮：取消 / 重置 / 应用
        apply_btn = QPushButton("应用")
        reset_btn = QPushButton("重置")
        cancel_btn = QPushButton("取消")
        apply_btn.setStyleSheet(primary_qss())
        apply_btn.setFixedHeight(30)
        reset_btn.setStyleSheet(secondary_qss())
        reset_btn.setFixedHeight(30)
        cancel_btn.setStyleSheet(secondary_qss())
        cancel_btn.setFixedHeight(30)
        apply_btn.clicked.connect(self._on_apply)
        reset_btn.clicked.connect(self.reset_to_defaults)
        cancel_btn.clicked.connect(self.reject)
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        btn_row.addStretch(1)
        btn_row.addWidget(cancel_btn)
        btn_row.addWidget(reset_btn)
        btn_row.addWidget(apply_btn)
        # 按钮区动态提示：含需重启参数时显示（_refresh_apply_hint 驱动）
        self._apply_hint = QLabel("本次修改包含需重启引擎的参数："
                                  "应用后引擎将自动重启")
        self._hints.append(self._apply_hint)
        self._apply_hint.setVisible(False)
        # 底部灰字：悬停说明可发现性 + 偏离默认图例（合成一行）
        footer_hint = QLabel("鼠标悬停参数名或控件可查看作用说明 · "
                             "带 * 的参数已偏离默认值（重置可恢复）")
        self._hints.append(footer_hint)
        # 组装
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 20, 20, 16)
        layout.setSpacing(12)
        layout.addWidget(mode_card)
        layout.addWidget(aux_card)
        layout.addWidget(special_card)
        layout.addWidget(corr_card)
        layout.addWidget(sample_card)
        layout.addWidget(self._apply_hint)
        layout.addWidget(footer_hint)
        layout.addLayout(btn_row)
        # 联动与标记刷新：构造完成后统一接线（部件未齐前 setChecked
        # 不触发槽，避免 _num_rows/_rep_spin 尚未创建时进槽）
        self._mode_radios["layout"].toggled.connect(
            self._refresh_layout_dependents)
        for chk in (*self._aux_checks.values(), *self._model_switches.values(),
                    *self._correction_checks.values()):
            chk.toggled.connect(self._refresh_modified_markers)
        for rb in self._mode_radios.values():
            rb.toggled.connect(self._refresh_modified_markers)
        for spin in (self._rep_spin, self._min_px, self._max_px):
            spin.valueChanged.connect(self._refresh_modified_markers)
        self._refresh_layout_dependents()
        self._refresh_apply_hint()
        self._refresh_modified_markers()

    # —— 读取 ——
    def get_config_patch(self) -> dict:
        """收集当前表单值 → 只含改动键的完整 paddle_vl 补丁"""
        pv = {}
        ignore = [label for label, _, _ in _AUX_ITEMS
                  if not self._aux_checks[label].isChecked()]
        pv["markdown_ignore_labels"] = ignore
        for key, chk in self._model_switches.items():
            pv[key] = chk.isChecked()
        for key, chk in self._correction_checks.items():
            pv[key] = chk.isChecked()
        # 引擎兼容：use_layout_detection 与既有 block_spotting 等价，双键并存
        layout_on = self._mode_is_layout()
        pv["use_layout_detection"] = layout_on
        pv["block_spotting"] = layout_on
        pv["repetition_penalty"] = self._rep_spin.value()
        pv["spotting_min_pixels"] = self._min_px.value()
        pv["spotting_max_pixels"] = self._max_px.value()
        return {"ocr": {"paddle_vl": pv}}

    def reset_to_defaults(self):
        """恢复默认：统一复用 defaults() 字段值（消除与重置逻辑重复的死代码）"""
        d = self.defaults()
        for label, _, _ in _AUX_ITEMS:
            self._aux_checks[label].setChecked(
                label not in d["markdown_ignore_labels"])
        for key, _ in self._model_switches.items():
            self._model_switches[key].setChecked(bool(d.get(key, False)))
        for key, _ in self._correction_checks.items():
            self._correction_checks[key].setChecked(
                bool(d.get(key, False)))
        self._set_mode_radio(bool(d.get("use_layout_detection", False)))
        self._rep_spin.setValue(d["repetition_penalty"])
        self._min_px.setValue(d["spotting_min_pixels"])
        self._max_px.setValue(d["spotting_max_pixels"])

    @staticmethod
    def defaults() -> dict:
        """paddle_vl 默认解析配置（与弹窗重置后状态一致）"""
        return {
            "markdown_ignore_labels": [label for label, _, default in _AUX_ITEMS
                                       if not default],
            "use_doc_orientation_classify": False,
            "use_doc_unwarping": False,
            "use_layout_detection": False,
            "block_spotting": False,
            "use_chart_recognition": True,
            "use_seal_recognition": True,
            "use_ocr_for_image_block": True,
            "merge_layout_blocks": True,
            "repetition_penalty": 1.1,
            "spotting_min_pixels": 0,
            "spotting_max_pixels": 1605632,
        }

    # —— 联动状态 / 校验 / 偏离默认标记 ——

    def _mode_is_layout(self) -> bool:
        """版面分析（逐块模式）是否开启——模式单选钮映射 use_layout_detection"""
        return self._mode_radios["layout"].isChecked()

    def _set_mode_radio(self, layout_on: bool):
        """切换模式单选钮：autoExclusive 组不能对选中钮单独 setChecked(False)
        （Qt 会忽略），置否须选中另一枚钮触发互斥"""
        (self._mode_radios["layout"] if layout_on
         else self._mode_radios["whole"]).setChecked(True)

    def _refresh_layout_dependents(self):
        """版面分析关闭时置灰依赖它的控件，并切换模式说明与卡角标。

        整页模式（版面分析关）下页面按单个整页盒识别、不产生布局标签：
        辅助内容过滤与图表/印章/图片文字识别、跨页表格合并都无作用对象。
        置灰不改变配置值——get_config_patch 照常输出，开启后立即生效。
        方向/扭曲矫正与采样三项两种模式均生效，始终可用。
        """
        active = self._mode_is_layout()
        for chk in self._aux_checks.values():
            chk.setEnabled(active)
        for chk in self._model_switches.values():
            chk.setEnabled(active)
        self._badges["aux"].setVisible(not active)
        self._badges["special"].setVisible(not active)
        self._mode_hint.setText(
            "按表格/图表/文本/图片分开识别：表格更结构化，可过滤页眉页脚等"
            "辅助内容" if active else
            "整页一次识别：每行文字都带高亮框；辅助内容过滤、图表/印章/"
            "图片识别、跨页表格合并不生效")

    def _refresh_apply_hint(self):
        """按钮区动态提示：矫正开关相对构造时配置有改动 → 应用后会重启引擎"""
        changed = any(
            self._correction_checks[key].isChecked() != v
            for key, v in zip(("use_doc_orientation_classify",
                               "use_doc_unwarping"), self._init_doc_sw))
        self._apply_hint.setVisible(changed)

    def _validate(self) -> str:
        """应用前校验：像素上下限按生效值比较（0 = 回退官方默认，
        对齐引擎 _DEFAULT_MIN_PIXELS / _OFFICIAL_SPOTTING_MAX_PIXELS）"""
        eff_min = self._min_px.value() or 112896
        eff_max = self._max_px.value() or 1605632
        if eff_min > eff_max:
            return (f"图像最小总像素数生效值 {eff_min} 大于最大总像素数"
                    f"生效值 {eff_max}（0 = 官方默认：最小 112896 / "
                    f"最大 1605632），请调整后重试")
        return ""

    def _refresh_modified_markers(self):
        """偏离 defaults() 的参数显示名追加「 *」（图例见底部灰字）"""
        d = self.defaults()
        for label, name, _ in _AUX_ITEMS:
            expect = label not in d["markdown_ignore_labels"]
            modified = self._aux_checks[label].isChecked() != expect
            self._aux_checks[label].setText(name + (" *" if modified else ""))
        for key, name, _ in _MODEL_SWITCHES:
            chk = (self._correction_checks[key]
                   if key in self._correction_checks
                   else self._model_switches[key])
            modified = chk.isChecked() != bool(d.get(key, False))
            chk.setText(name + (" *" if modified else ""))
        # 模式单选钮（版面分析）：与默认（整页识别）不一致时标记
        rb = self._mode_radios["layout"]
        modified = self._mode_is_layout() != bool(
            d.get("use_layout_detection", False))
        rb.setText("版面分析" + (" *" if modified else ""))
        for key, spin in (("repetition_penalty", self._rep_spin),
                          ("spotting_min_pixels", self._min_px),
                          ("spotting_max_pixels", self._max_px)):
            name, lbl = self._num_rows[key]
            modified = spin.value() != d[key]
            lbl.setText(name + (" *" if modified else ""))

    def _on_apply(self):
        err = self._validate()
        if err:
            QMessageBox.warning(self, "参数矛盾", err)
            return
        self.apply_requested.emit(self.get_config_patch())
        self.accept()
