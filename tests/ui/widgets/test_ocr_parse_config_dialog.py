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
    # 默认：方向/扭曲/版面分析关，图表/印章/图片文字/跨页合并开
    assert pv["use_doc_orientation_classify"] is False
    assert pv["use_doc_unwarping"] is False
    assert pv["use_layout_detection"] is False
    assert pv["use_chart_recognition"] is True
    assert pv["use_seal_recognition"] is True
    assert pv["use_ocr_for_image_block"] is True
    assert pv["merge_layout_blocks"] is True
    assert pv["repetition_penalty"] == 1.1
    assert pv["spotting_max_pixels"] == 1048576


def test_roundtrip(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True,
        "repetition_penalty": 1.3,
        "markdown_ignore_labels": ["header"],
    }}})
    patch = dlg.get_config_patch()
    assert patch["ocr"]["paddle_vl"]["use_doc_orientation_classify"] is True
    assert patch["ocr"]["paddle_vl"]["repetition_penalty"] == 1.3


def test_reset_restores_defaults(qapp):
    dlg = OcrParseConfigDialog({"ocr": {"paddle_vl": {
        "use_doc_orientation_classify": True}}})
    dlg.reset_to_defaults()
    patch = dlg.get_config_patch()
    assert patch["ocr"]["paddle_vl"]["use_doc_orientation_classify"] is False
