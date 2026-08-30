"""OcrParseConfigDialog 测试（offscreen）

复用 tests/ui/conftest.py 的会话级 qapp fixture（不定义本地重复 fixture）。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from app.ui.widgets.ocr_parse_config_dialog import OcrParseConfigDialog


def test_defaults_patch(qapp):
    dlg = OcrParseConfigDialog({})
    patch = dlg.get_config_patch()
    pv = patch["ocr"]["paddle_vl"]
    # 方向/扭曲矫正：默认 False（构造期参数，开启需重启引擎）；其余开关默认
    # 版面分析关，图表/印章/图片文字/跨页合并开
    assert pv["use_doc_orientation_classify"] is False
    assert pv["use_doc_unwarping"] is False
    assert pv["use_layout_detection"] is False
    assert pv["use_chart_recognition"] is True
    assert pv["use_seal_recognition"] is True
    assert pv["use_ocr_for_image_block"] is True
    assert pv["merge_layout_blocks"] is True
    assert pv["repetition_penalty"] == 1.1
    assert pv["spotting_max_pixels"] == 1605632
    # 双键兼容：use_layout_detection 与 block_spotting 等价，patch 同时输出且同值
    assert pv["block_spotting"] is False
    assert pv["block_spotting"] == pv["use_layout_detection"]
    # 空配置回退默认忽略集（与 defaults() 一致：仅页码默认恢复解析）
    ignore = pv["markdown_ignore_labels"]
    assert "number" not in ignore
    for label in ("header", "header_image", "footer", "footer_image",
                  "footnote", "aside_text"):
        assert label in ignore


def test_roundtrip(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "repetition_penalty": 1.3,
        "markdown_ignore_labels": ["header"],
    }}})
    patch = dlg.get_config_patch()
    pv = patch["ocr"]["paddle_vl"]
    # 方向矫正：配置 True → 勾选并输出 True（恢复可配置）
    assert pv["use_doc_orientation_classify"] is True
    assert pv["repetition_penalty"] == 1.3
    # markdown_ignore_labels 语义：header 未勾选（恢复解析）→ 忽略集含 header；
    # number 默认勾选 → 忽略集不含 number（真实 PP-DocLayoutV3 标签）
    assert "header" in pv["markdown_ignore_labels"]
    assert "number" not in pv["markdown_ignore_labels"]


def test_block_spotting_seed_layout_checkbox(qapp):
    """既有设置页读写 block_spotting：仅配该键时「版面分析」单选钮应选中（I1 回归）"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {"block_spotting": True}}})
    assert dlg._mode_radios["layout"].isChecked() is True
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    # 开启态双键同值输出（开）
    assert pv["use_layout_detection"] is True
    assert pv["block_spotting"] is True


def test_reset_restores_defaults(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    dlg.reset_to_defaults()
    patch = dlg.get_config_patch()
    # 重置后矫正键输出 False（默认由 defaults() 提供）
    assert patch["ocr"]["paddle_vl"]["use_doc_orientation_classify"] is False
    assert patch["ocr"]["paddle_vl"]["use_doc_unwarping"] is False


def test_correction_checkboxes_enabled(qapp):
    """方向/扭曲矫正始终可用（两种模式均生效）+ 「重启生效」徽标 ×2"""
    from PyQt6.QtWidgets import QLabel
    dlg = OcrParseConfigDialog({})
    assert dlg._correction_checks["use_doc_orientation_classify"].isEnabled() is True
    assert dlg._correction_checks["use_doc_unwarping"].isEnabled() is True
    assert dlg._mode_radios["layout"].isEnabled() is True
    # tooltip 说明修改后需重启引擎
    assert "重启引擎" in \
        dlg._correction_checks["use_doc_orientation_classify"].toolTip()
    assert "重启引擎" in dlg._correction_checks["use_doc_unwarping"].toolTip()
    # 行尾「重启生效」徽标（两个矫正项各一枚）
    badges = [lbl.text() for lbl in dlg.findChildren(QLabel)
              if lbl.text() == "重启生效"]
    assert len(badges) == 2


def test_layout_dependent_switches_disabled(qapp):
    """版面分析关闭时依赖它的四开关置灰、两卡角标显示；开启后恢复可用"""
    dlg = OcrParseConfigDialog({})
    for key in ("use_chart_recognition", "use_seal_recognition",
                "use_ocr_for_image_block", "merge_layout_blocks"):
        assert dlg._model_switches[key].isEnabled() is False, key
    assert dlg._badges["aux"].isHidden() is False
    assert dlg._badges["special"].isHidden() is False
    dlg._mode_radios["layout"].setChecked(True)
    for key in ("use_chart_recognition", "use_seal_recognition",
                "use_ocr_for_image_block", "merge_layout_blocks"):
        assert dlg._model_switches[key].isEnabled() is True, key
    assert dlg._badges["aux"].isHidden() is True
    assert dlg._badges["special"].isHidden() is True


def test_patch_includes_correction_keys(qapp):
    """get_config_patch 输出方向/扭曲矫正两键（值 = 复选框状态）"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True, "use_doc_unwarping": True}}})
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert pv["use_doc_orientation_classify"] is True
    assert pv["use_doc_unwarping"] is True
    # 取消勾选 → 输出 False（非移除键）
    dlg._correction_checks["use_doc_orientation_classify"].setChecked(False)
    pv2 = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert pv2["use_doc_orientation_classify"] is False
    assert pv2["use_doc_unwarping"] is True


def test_cancel_button_rejects(qapp):
    """T11：取消按钮存在且点击后弹窗 Rejected"""
    from PyQt6.QtWidgets import QDialog, QPushButton
    dlg = OcrParseConfigDialog({})
    btns = [b for b in dlg.findChildren(QPushButton)]
    cancel = next(b for b in btns if b.text() == "取消")
    cancel.click()
    assert dlg.result() == QDialog.DialogCode.Rejected


def test_rep_spin_decimals_one(qapp):
    """T11：重复抑制强度显示 1 位小数（1.1 而非 1.10）"""
    dlg = OcrParseConfigDialog({})
    assert dlg._rep_spin.decimals() == 1
    assert dlg._rep_spin.textFromValue(1.1) == "1.1"


def test_reset_matches_defaults(qapp):
    """T11：reset_to_defaults 复用 defaults()——重置后表单值 == defaults()"""
    from app.ui.widgets.ocr_parse_config_dialog import _AUX_ITEMS
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_layout_detection": True,
        "use_chart_recognition": False,
        "repetition_penalty": 1.7,
        "spotting_min_pixels": 100,
        "spotting_max_pixels": 999,
        "markdown_ignore_labels": ["number"],
    }}})
    dlg.reset_to_defaults()
    d = dlg.defaults()
    for label, _, _ in _AUX_ITEMS:
        assert dlg._aux_checks[label].isChecked() == \
            (label not in d["markdown_ignore_labels"])
    assert dlg._rep_spin.value() == d["repetition_penalty"] == 1.1
    assert dlg._min_px.value() == d["spotting_min_pixels"] == 0
    assert dlg._max_px.value() == d["spotting_max_pixels"] == 1605632
    assert dlg._mode_is_layout() is False
    assert dlg._model_switches["use_chart_recognition"].isChecked() is True


def test_mode_radios_semantics(qapp):
    """模式单选钮：互斥、映射 use_layout_detection、patch 双键同值输出"""
    dlg = OcrParseConfigDialog({})
    assert dlg._mode_radios["whole"].isChecked() is True
    assert dlg._mode_radios["layout"].isChecked() is False
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert pv["use_layout_detection"] is False
    assert pv["block_spotting"] is False
    dlg._mode_radios["layout"].setChecked(True)
    assert dlg._mode_radios["whole"].isChecked() is False  # 互斥
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert pv["use_layout_detection"] is True
    assert pv["block_spotting"] is True


def test_card_badges_toggle(qapp):
    """卡角标文案与模式说明：角标 = 「整页模式下未生效」，说明随选中态切换"""
    dlg = OcrParseConfigDialog({})
    assert dlg._badges["aux"].text() == "整页模式下未生效"
    assert "整页一次识别" in dlg._mode_hint.text()
    dlg._mode_radios["layout"].setChecked(True)
    assert "表格更结构化" in dlg._mode_hint.text()


def test_all_items_effective_end_to_end(qapp):
    """端到端：弹窗每个调整项 → patch → apply_config → 引擎实例属性

    覆盖全部 12 个键位（辅助内容 7 项合 1 键 + 模型开关 7 键 + 采样 3 键），
    引擎单例在测试末尾 reset 防污染其他用例。
    """
    from app.core.ocr_engine_paddle_vl import PaddleOCRVLEngine
    PaddleOCRVLEngine.reset_instance()
    try:
        dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {}}})

        # 辅助内容解析组：只保留页眉/页码，其余全部忽略
        aux_keep = {"header", "number"}
        for label in dlg._aux_checks:
            dlg._aux_checks[label].setChecked(label in aux_keep)
        # 模型参数组：6 个开关翻转 + 模式单选钮切到版面分析
        new_sw = {
            "use_doc_orientation_classify": True,
            "use_doc_unwarping": True,
            "use_chart_recognition": False,
            "use_seal_recognition": False,
            "use_ocr_for_image_block": False,
            "merge_layout_blocks": False,
        }
        for key, val in new_sw.items():
            chk = (dlg._correction_checks[key]
                   if key in dlg._correction_checks
                   else dlg._model_switches[key])
            chk.setChecked(val)
        dlg._mode_radios["layout"].setChecked(True)
        # 采样参数组
        dlg._rep_spin.setValue(0.7)
        dlg._min_px.setValue(50_000)
        dlg._max_px.setValue(1_000_000)

        patch = dlg.get_config_patch()
        pv = patch["ocr"]["paddle_vl"]
        eng = PaddleOCRVLEngine({"ocr": {"paddle_vl": {}}})
        eng.apply_config(patch)

        # 辅助内容 → markdown_ignore_labels（引擎忽略集 == 弹窗未勾选集）
        expected_ignore = {label for label in dlg._aux_checks
                           if label not in aux_keep}
        assert set(pv["markdown_ignore_labels"]) == expected_ignore
        assert set(eng._markdown_ignore_labels) == expected_ignore
        # 模型开关 → 引擎属性（use_layout_detection 与 block_spotting 双键并存）
        assert eng._use_doc_orientation_classify is True
        assert eng._use_doc_unwarping is True
        assert pv["use_layout_detection"] is True
        assert pv["block_spotting"] is True
        assert eng._block_spotting is True
        assert eng._use_chart_recognition is False
        assert eng._use_seal_recognition is False
        assert eng._use_ocr_for_image_block is False
        assert eng._merge_layout_blocks is False
        # 采样参数 → 引擎属性
        assert eng._repetition_penalty == 0.7
        assert eng._spotting_min_pixels == 50_000
        assert eng._spotting_max_pixels == 1_000_000
    finally:
        PaddleOCRVLEngine.reset_instance()


def test_tooltips_present(qapp):
    """全部 17 个参数控件均有非空 tooltip，关键参数文案命中"""
    dlg = OcrParseConfigDialog({})
    # 辅助内容 7 项：非空 + 统一生效条件说明
    for label, chk in dlg._aux_checks.items():
        assert chk.toolTip(), f"辅助内容 {label} 缺 tooltip"
        assert "版面分析" in chk.toolTip()
        assert "忽略" in chk.toolTip()
    # 专项开关 4 项 + 矫正 2 项 + 模式单选钮 2 项 + 采样 3 项：非空
    for key, chk in (*dlg._model_switches.items(),
                     *dlg._correction_checks.items()):
        assert chk.toolTip(), f"模型开关 {key} 缺 tooltip"
    for key, rb in dlg._mode_radios.items():
        assert rb.toolTip(), f"模式单选钮 {key} 缺 tooltip"
    for key, w in (("repetition_penalty", dlg._rep_spin),
                   ("spotting_min_pixels", dlg._min_px),
                   ("spotting_max_pixels", dlg._max_px)):
        assert w.toolTip(), f"采样参数 {key} 缺 tooltip"
    # 关键文案抽查
    assert "重启引擎" in \
        dlg._correction_checks["use_doc_orientation_classify"].toolTip()
    assert "重启引擎" in dlg._correction_checks["use_doc_unwarping"].toolTip()
    assert "版面" in dlg._mode_radios["layout"].toolTip()
    assert "重复" in dlg._rep_spin.toolTip()
    assert "坐标" in dlg._max_px.toolTip()
    # 采样组行标签（显式 QLabel）也可查看说明
    from PyQt6.QtWidgets import QLabel
    labels = {lbl.text(): lbl.toolTip() for lbl in dlg.findChildren(QLabel)}
    for name in ("重复抑制强度", "图像最小总像素数", "图像最大总像素数"):
        assert labels.get(name), f"采样行标签 {name} 缺 tooltip"


def test_aux_group_disabled_without_layout(qapp):
    """版面分析关闭时辅助内容 7 项置灰（值保留），开启后恢复可用"""
    dlg = OcrParseConfigDialog({})
    for chk in dlg._aux_checks.values():
        assert chk.isEnabled() is False
    dlg._mode_radios["layout"].setChecked(True)
    for chk in dlg._aux_checks.values():
        assert chk.isEnabled() is True
    # 值保留：置灰期间勾选状态照常进入 patch（开启版面分析后立即生效）。
    # 置否：autoExclusive 组选中另一枚（整页识别）
    dlg._mode_radios["whole"].setChecked(True)
    assert dlg._mode_radios["layout"].isChecked() is False
    assert dlg._aux_checks["header"].isEnabled() is False
    dlg._aux_checks["header"].setChecked(True)
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert "header" not in pv["markdown_ignore_labels"]


def test_discoverability_hint(qapp):
    """底部灰字：悬停可查看说明 + 偏离默认图例"""
    from PyQt6.QtWidgets import QLabel
    dlg = OcrParseConfigDialog({})
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any("悬停" in t for t in texts)
    assert any("*" in t and "重置" in t for t in texts)


def test_validate_pixel_bounds(qapp):
    """生效值校验：0 回退官方默认后比较（含 min=0 + 小 max 隐藏矛盾）"""
    dlg = OcrParseConfigDialog({})
    assert dlg._validate() == ""            # 默认 0 / 1605632 合法
    dlg._min_px.setValue(2_000_000)         # 显式矛盾
    assert "生效值" in dlg._validate()
    dlg._min_px.setValue(0)
    dlg._max_px.setValue(50_000)            # 隐藏矛盾：0 回退 112896 > 50000
    assert dlg._validate() != ""
    dlg._max_px.setValue(0)                 # 双 0 → 官方回退 112896/1605632 合法
    assert dlg._validate() == ""


def test_apply_blocked_on_invalid(qapp, monkeypatch):
    """矛盾值下应用被阻止：弹警告、不 emit apply_requested、弹窗不关闭"""
    from PyQt6.QtWidgets import QDialog, QMessageBox
    calls = []
    monkeypatch.setattr(QMessageBox, "warning",
                        staticmethod(lambda *a, **k: calls.append(a)))
    dlg = OcrParseConfigDialog({})
    emitted = []
    dlg.apply_requested.connect(lambda p: emitted.append(p))
    dlg._min_px.setValue(2_000_000)
    dlg._on_apply()
    assert calls                              # 弹出过警告
    assert not emitted                        # 未发应用信号
    assert dlg.result() != QDialog.DialogCode.Accepted  # 弹窗保持打开


def test_modified_markers(qapp):
    """偏离 defaults() 的参数显示名追加「 *」，信号驱动、重置后清除"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "repetition_penalty": 1.5,
        "use_chart_recognition": False,
    }}})
    assert dlg._num_rows["repetition_penalty"][1].text() == "重复抑制强度 *"
    assert dlg._model_switches["use_chart_recognition"].text() == "图表识别 *"
    # 未偏离的参数无标记
    assert dlg._model_switches["use_seal_recognition"].text() == "印章识别"
    # 信号驱动：改回默认值标记即时消失
    dlg._rep_spin.setValue(1.1)
    assert dlg._num_rows["repetition_penalty"][1].text() == "重复抑制强度"
    # 重置后全部清除
    dlg.reset_to_defaults()
    for chk in (*dlg._aux_checks.values(), *dlg._model_switches.values(),
                *dlg._correction_checks.values()):
        assert " *" not in chk.text(), chk.text()
    assert dlg._mode_radios["layout"].text() == "版面分析"
    for name, lbl in dlg._num_rows.values():
        assert " *" not in lbl.text(), lbl.text()


def test_apply_hint_dynamic(qapp):
    """按钮区动态提示：矫正开关相对构造配置变动时显示，复位后隐藏"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    # 构造时已开启 → 无改动 → 提示隐藏
    assert dlg._apply_hint.isHidden() is True
    dlg._correction_checks["use_doc_orientation_classify"].setChecked(False)
    assert dlg._apply_hint.isHidden() is False
    dlg._correction_checks["use_doc_orientation_classify"].setChecked(True)
    assert dlg._apply_hint.isHidden() is True
    # 重置 = 默认开关状态（关）≠ 配置（开）→ 提示出现
    dlg.reset_to_defaults()
    assert dlg._apply_hint.isHidden() is False


def test_modified_markers_uses_mode_radio(qapp):
    """模式标记：版面分析相对默认（整页）偏移时单选钮追加「 *」，恢复后清除"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_layout_detection": True}}})
    assert dlg._mode_radios["layout"].text() == "版面分析 *"
    dlg._mode_radios["whole"].setChecked(True)  # 置否：选中整页识别互斥切换
    assert dlg._mode_radios["layout"].text() == "版面分析"
    dlg._mode_radios["layout"].setChecked(True)
    assert dlg._mode_radios["layout"].text() == "版面分析 *"
    dlg.reset_to_defaults()
    assert dlg._mode_radios["layout"].text() == "版面分析"


def test_max_pixels_presets(qapp):
    """最大像素预设按钮：官方默认 1605632 / 省显存 1048576"""
    from PyQt6.QtWidgets import QPushButton
    dlg = OcrParseConfigDialog(
        {"ocr": {"paddle_vl": {"spotting_max_pixels": 999}}})
    btns = {b.text(): b for b in dlg.findChildren(QPushButton)
            if b.text() in ("官方默认", "省显存")}
    assert set(btns) == {"官方默认", "省显存"}
    btns["省显存"].click()
    assert dlg._max_px.value() == 1048576
    btns["官方默认"].click()
    assert dlg._max_px.value() == 1605632
