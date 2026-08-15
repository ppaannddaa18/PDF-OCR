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
    assert pv["spotting_max_pixels"] == 1048576
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
    """既有设置页读写 block_spotting：仅配该键时版面分析复选框应勾选（I1 回归）"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {"block_spotting": True}}})
    assert dlg._model_switches["use_layout_detection"].isChecked() is True
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
    """方向/扭曲矫正复选框可用 + 组内灰色提示文案（开启加载预处理模块）"""
    from PyQt6.QtWidgets import QLabel
    dlg = OcrParseConfigDialog({})
    assert dlg._model_switches["use_doc_orientation_classify"].isEnabled() is True
    assert dlg._model_switches["use_doc_unwarping"].isEnabled() is True
    assert dlg._model_switches["use_layout_detection"].isEnabled() is True
    assert dlg._model_switches["use_chart_recognition"].isEnabled() is True
    # 模型参数组内存在灰色小字提示（QLabel 文案命中）
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any("开启将加载文档预处理模块" in t for t in texts)
    assert any("需重启引擎生效" in t for t in texts)


def test_patch_includes_correction_keys(qapp):
    """get_config_patch 输出方向/扭曲矫正两键（值 = 复选框状态）"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True, "use_doc_unwarping": True}}})
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert pv["use_doc_orientation_classify"] is True
    assert pv["use_doc_unwarping"] is True
    # 取消勾选 → 输出 False（非移除键）
    dlg._model_switches["use_doc_orientation_classify"].setChecked(False)
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
    assert dlg._max_px.value() == d["spotting_max_pixels"] == 1048576
    assert dlg._model_switches["use_layout_detection"].isChecked() is False
    assert dlg._model_switches["use_chart_recognition"].isChecked() is True


def test_aux_group_hint_text(qapp):
    """T11：辅助内容组灰色小字提示逐块模式生效条件"""
    from PyQt6.QtWidgets import QLabel
    dlg = OcrParseConfigDialog({})
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any("仅开启版面分析" in t for t in texts)
