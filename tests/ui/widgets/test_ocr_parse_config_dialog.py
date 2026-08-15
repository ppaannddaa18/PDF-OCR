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
    # 方向/扭曲矫正：不支持（管线未加载 DocPreprocessor）→ patch 不输出，
    # 引擎保持默认 False；版面分析关，图表/印章/图片文字/跨页合并开
    assert "use_doc_orientation_classify" not in pv
    assert "use_doc_unwarping" not in pv
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


def test_roundtrip(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "repetition_penalty": 1.3,
        "markdown_ignore_labels": ["header"],
    }}})
    patch = dlg.get_config_patch()
    pv = patch["ocr"]["paddle_vl"]
    # 方向矫正：配置曾为 True 也不输出（禁用键不参与 patch）
    assert "use_doc_orientation_classify" not in pv
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
    # 重置后矫正键仍不输出（默认 False 由引擎侧保持）
    assert "use_doc_orientation_classify" not in patch["ocr"]["paddle_vl"]


def test_correction_checkboxes_disabled(qapp):
    """方向/扭曲矫正复选框禁用 + 组内灰色提示文案；其余开关仍可用"""
    from PyQt6.QtWidgets import QLabel
    dlg = OcrParseConfigDialog({})
    assert dlg._model_switches["use_doc_orientation_classify"].isEnabled() is False
    assert dlg._model_switches["use_doc_unwarping"].isEnabled() is False
    assert dlg._model_switches["use_layout_detection"].isEnabled() is True
    assert dlg._model_switches["use_chart_recognition"].isEnabled() is True
    # 模型参数组内存在灰色小字提示（QLabel 文案命中）
    texts = [lbl.text() for lbl in dlg.findChildren(QLabel)]
    assert any("当前版本不支持" in t for t in texts)


def test_patch_excludes_disabled_keys(qapp):
    """get_config_patch 不输出方向/扭曲矫正两键（引擎保持默认 False）"""
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True, "use_doc_unwarping": True}}})
    pv = dlg.get_config_patch()["ocr"]["paddle_vl"]
    assert "use_doc_orientation_classify" not in pv
    assert "use_doc_unwarping" not in pv
