"""引擎选择对话框 + choose_engine 测试（Task P1）

覆盖：两卡片/无默认选中、单选启用按钮、Esc/关闭 reject、双击确认、
依赖缺失徽章、warning 只弹一次、choose_engine 的 env 直通/弹窗/写内存不写盘。
"""
import pytest
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QApplication, QDialog
from qfluentwidgets import InfoBar

from app.ui.engine_select_dialog import EngineSelectDialog
from app.ui.theme_manager import ThemeManager
import main as main_module

# check_engine_availability 的假返回（choose_engine 弹窗路径用）
_FAKE_AVAILABILITY = {"gguf": {"available": True, "issues": []},
                      "rapidocr": {"available": True, "issues": []}}


class TestEngineSelectDialog:
    def test_two_cards_no_default_selection(self, qapp):
        """两卡片存在、无默认选中、进入按钮禁用"""
        dialog = EngineSelectDialog({})
        assert dialog.gguf_card is not None
        assert dialog.rapid_card is not None
        assert dialog.selected_engine() is None
        assert dialog.enter_btn.isEnabled() is False

    def test_select_card_enables_button(self, qapp):
        """点击卡片 → selected_engine 正确、按钮可用；切卡可换选"""
        dialog = EngineSelectDialog({})
        dialog.show()
        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        assert dialog.selected_engine() == "gguf"
        assert dialog.enter_btn.isEnabled() is True
        QTest.mouseClick(dialog.rapid_card, Qt.MouseButton.LeftButton)
        assert dialog.selected_engine() == "rapid"

    def test_asymmetric_card_layout(self, qapp):
        """结构重排：GGUF 卡为主（更宽），Rapid 卡为辅"""
        dialog = EngineSelectDialog({})
        assert dialog.gguf_card.minimumWidth() > dialog.rapid_card.minimumWidth()

    def test_cards_equal_height(self, qapp):
        """两卡最小高度一致（等高对齐，消除右侧下方空白）"""
        dialog = EngineSelectDialog({})
        assert dialog.gguf_card.minimumHeight() == dialog.rapid_card.minimumHeight()
        assert dialog.gguf_card.minimumHeight() >= 360

    def test_unselected_card_has_neutral_border(self, qapp):
        """未选中卡片有 1px 中性描边（深色卡在浅底上轮廓清晰）"""
        dialog = EngineSelectDialog({})
        border = ThemeManager.COLORS["gguf"]["dark"]["border"]
        assert f"border: 1px solid {border}" in dialog.gguf_card.styleSheet()

    def test_enter_button_neutral_dark_style(self, qapp):
        """进入按钮：启用近黑实心白字、禁用浅灰（不绑定引擎品牌色）"""
        dialog = EngineSelectDialog({})
        light = ThemeManager.COLORS["rapid"]["light"]
        sheet = dialog.enter_btn.styleSheet()
        assert light["text_primary"] in sheet  # 启用底色（近黑）
        assert light["white"] in sheet          # 白字
        assert light["text_disabled"] in sheet  # 禁用文字色
        assert light["bg_hover"] in sheet       # 禁用底色

    def test_radio_hover_style_in_card_qss(self, qapp):
        """radio 圆圈样式走卡片类级 QSS：未选中 muted、hover 变色、选中 accent 填充"""
        dialog = EngineSelectDialog({})
        sheet = dialog.gguf_card.styleSheet()
        muted = dialog.gguf_card._colors["muted"]
        hover = dialog.gguf_card._colors["hover_border"]
        accent = dialog.gguf_card._colors["accent"]
        assert f"#radioCircle" in sheet
        assert muted in sheet  # 未选中外圈
        assert hover in sheet  # hover 外圈
        assert accent in sheet  # 选中填充

    def test_session_tag_on_selection(self, qapp):
        """选中卡片显示「本会话」标签，切换后标签跟随"""
        dialog = EngineSelectDialog({})
        dialog.show()
        assert dialog.gguf_card._session_tag.text() == "本会话"
        assert dialog.gguf_card._session_tag.isVisible() is False

        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        assert dialog.gguf_card._session_tag.isVisible() is True
        assert dialog.rapid_card._session_tag.isVisible() is False

        QTest.mouseClick(dialog.rapid_card, Qt.MouseButton.LeftButton)
        assert dialog.gguf_card._session_tag.isVisible() is False
        assert dialog.rapid_card._session_tag.isVisible() is True

    def test_radio_indicator_reflects_selection(self, qapp):
        """单选圆圈：未选为空，选中显示 ✓，切换时跟随"""
        dialog = EngineSelectDialog({})
        dialog.show()
        assert dialog.gguf_card._radio.text() == ""

        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        assert dialog.gguf_card._radio.text() == "✓"
        assert dialog.rapid_card._radio.text() == ""

        QTest.mouseClick(dialog.rapid_card, Qt.MouseButton.LeftButton)
        assert dialog.gguf_card._radio.text() == ""
        assert dialog.rapid_card._radio.text() == "✓"

    def test_title_tooltips_explain_terms(self, qapp):
        """术语 Tooltip：GGUF/VLM 与 RapidOCR 有解释"""
        dialog = EngineSelectDialog({})
        assert "GGUF" in dialog.gguf_card._title.toolTip()
        assert "VLM" in dialog.gguf_card._title.toolTip()
        assert "RapidOCR" in dialog.rapid_card._title.toolTip()

    def test_selected_background_tint(self, qapp):
        """选中后卡片背景微变（GGUF surface_2 / Rapid bg_selected）"""
        dialog = EngineSelectDialog({})
        dialog.show()

        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        gguf_tint = ThemeManager.COLORS["gguf"]["dark"]["surface_2"]
        assert gguf_tint in dialog.gguf_card.styleSheet()

        QTest.mouseClick(dialog.rapid_card, Qt.MouseButton.LeftButton)
        rapid_tint = ThemeManager.COLORS["rapid"]["light"]["bg_selected"]
        assert rapid_tint in dialog.rapid_card.styleSheet()

    def test_keyboard_select_and_confirm(self, qapp):
        """卡片键盘：Space 选中，Enter 选中并确认"""
        dialog = EngineSelectDialog({})
        dialog.show()
        dialog.gguf_card.setFocus()
        QTest.keyClick(dialog.gguf_card, Qt.Key.Key_Space)
        assert dialog.selected_engine() == "gguf"
        assert dialog.enter_btn.isEnabled() is True

        dialog.rapid_card.setFocus()
        QTest.keyClick(dialog.rapid_card, Qt.Key.Key_Return)
        assert dialog.selected_engine() == "rapid"
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_esc_rejects(self, qapp):
        """Esc → reject（choose_engine 侧由此退出程序）"""
        dialog = EngineSelectDialog({})
        QTimer.singleShot(50, lambda: QTest.keyClick(dialog, Qt.Key.Key_Escape))
        assert dialog.exec() == QDialog.DialogCode.Rejected

    def test_close_rejects(self, qapp):
        """关闭按钮 / X → reject"""
        dialog = EngineSelectDialog({})
        QTimer.singleShot(50, dialog.close)
        assert dialog.exec() == QDialog.DialogCode.Rejected

    def test_double_click_confirms(self, qapp):
        """双击卡片 = 选择并确认"""
        dialog = EngineSelectDialog({})
        dialog.show()
        QTest.mouseDClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        assert dialog.selected_engine() == "gguf"
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_missing_deps_show_badge_but_selectable(self, qapp):
        """依赖缺失 → 红徽章 + 缺项文本；仍允许选择"""
        dialog = EngineSelectDialog({})
        dialog.set_availability({
            "gguf": {"available": False, "issues": ["未找到 llama-server.exe", "模型文件不存在: x.gguf"]},
            "rapidocr": {"available": True, "issues": []},
        })
        assert dialog.gguf_card._badge.text() == "依赖不完整"
        assert "未找到 llama-server.exe" in dialog.gguf_card._issues_label.text()
        assert dialog.rapid_card._badge.text() == "就绪"
        dialog.show()
        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        assert dialog.selected_engine() == "gguf"
        assert dialog.enter_btn.isEnabled() is True

    def test_warning_badge_for_partial_deps(self, qapp):
        """available=True 但带警告级缺项 → 黄徽章「部分依赖缺失」"""
        dialog = EngineSelectDialog({})
        dialog.set_availability({
            "gguf": {"available": True, "issues": ["警告：ggml-cuda.dll 缺失"]},
            "rapidocr": {"available": True, "issues": []},
        })
        assert dialog.gguf_card._badge.text() == "部分依赖缺失"
        assert "ggml-cuda.dll" in dialog.gguf_card._issues_label.text()
        assert dialog.rapid_card._badge.text() == "就绪"
        # 警告级不阻塞选择确认（直接进入）
        dialog.show()
        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_set_availability_default_fallback(self, qapp):
        """availability 缺 key / 缺字段时回退为可用默认，不崩溃"""
        dialog = EngineSelectDialog({})
        dialog.set_availability({})
        assert dialog.gguf_card._badge.text() == "就绪"
        assert dialog.rapid_card._badge.text() == "就绪"
        assert dialog._availability == {
            "gguf": {"available": True, "issues": []},
            "rapid": {"available": True, "issues": []},
        }

    def test_cards_only_gguf_rapid(self, qapp):
        """paddle_vl 卡片已移除，只剩 gguf/rapid"""
        dialog = EngineSelectDialog({"ocr": {"gguf": {}, "rapidocr": {}}})
        keys = [card.engine_key for card in dialog._cards]
        assert keys == ["gguf", "rapid"]

    def test_warning_shown_once_on_confirm(self, qapp):
        """依赖不完整时确认：第一次弹 warning 不进入，第二次才进入且不重复弹"""
        dialog = EngineSelectDialog({})
        dialog.set_availability({
            "gguf": {"available": False, "issues": ["未找到 llama-server.exe"]},
            "rapidocr": {"available": True, "issues": []},
        })
        dialog.show()
        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Rejected  # 未进入
        assert len(dialog.findChildren(InfoBar)) == 1
        assert dialog.findChildren(InfoBar)[0].isVisible()  # 弹窗真实可见
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted  # 进入
        assert len(dialog.findChildren(InfoBar)) == 1  # 不重复弹

    def test_warning_per_engine_after_card_switch(self, qapp):
        """双引擎均不可用时：切卡后第二个引擎的 warning 不被跳过（按引擎记录）"""
        dialog = EngineSelectDialog({})
        dialog.set_availability({
            "gguf": {"available": False, "issues": ["未找到 llama-server.exe"]},
            "rapidocr": {"available": False, "issues": ["rapidocr 依赖缺失"]},
        })
        dialog.show()
        # GGUF：第一次确认 → warning 不进入
        QTest.mouseClick(dialog.gguf_card, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert len(dialog.findChildren(InfoBar)) == 1
        # 切到 Rapid：该引擎的 warning 未弹过 → 仍应弹且不进入
        QTest.mouseClick(dialog.rapid_card, Qt.MouseButton.LeftButton)
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Rejected
        assert len(dialog.findChildren(InfoBar)) == 2
        # 再点 Rapid 确认 → 进入
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted

    def test_focus_border_uses_hover_color_not_accent(self, qapp):
        """键盘焦点：中性色虚线（不冒充选中金框）；悬停/选中用品牌色实线"""
        dialog = EngineSelectDialog({})
        sheet = dialog.gguf_card.styleSheet()
        accent = dialog.gguf_card._colors["accent"]
        hover = dialog.gguf_card._colors["hover_border"]
        border = dialog.gguf_card._colors["border"]
        assert "[selected='true']" in sheet  # 选中态规则存在
        focus_rule = sheet.split(":focus")[1].split("[selected")[0]
        assert "dashed" in focus_rule          # 焦点虚线（键盘态）
        assert border in focus_rule.split(":hover")[0]  # focus 用中性 border 色
        assert hover in focus_rule             # :hover 规则仍用品牌色
        selected_rule = sheet.split("[selected='true']")[1]
        assert accent in selected_rule  # 选中 → accent（覆盖聚焦/悬停）


class TestChooseEngine:
    def test_env_shortcut_no_dialog(self, qapp, monkeypatch):
        """PDFOCR_ENGINE=rapidocr → 不构造对话框直接返回"""
        monkeypatch.setenv("PDFOCR_ENGINE", "rapidocr")
        called = []
        monkeypatch.setattr(main_module, "_show_engine_dialog",
                            lambda c: called.append(c) or "rapid")
        config = {}
        assert main_module.choose_engine(config) == "rapidocr"
        assert config["ocr"]["engine"] == "rapidocr"
        assert called == []  # env 分支在任何对话框构造前返回

    def test_env_invalid_falls_back_to_dialog(self, qapp, monkeypatch):
        """PDFOCR_ENGINE 非 gguf/rapidocr → 忽略并走对话框层"""
        monkeypatch.setenv("PDFOCR_ENGINE", "bogus")
        calls = []
        monkeypatch.setattr(main_module, "_show_engine_dialog",
                            lambda c: calls.append(c) or "gguf")
        config = {}
        assert main_module.choose_engine(config) == "gguf"
        assert config["ocr"]["engine"] == "gguf"
        assert calls == [config]

    def test_accepted_normalizes_engine_memory_not_disk(self, qapp, monkeypatch):
        """Accepted 后写内存 config（'rapid' → 'rapidocr' 归一化），不触发写盘"""
        from app.utils import config_loader
        monkeypatch.delenv("PDFOCR_ENGINE", raising=False)
        monkeypatch.setattr(main_module, "_show_engine_dialog", lambda c: "rapid")
        saved = []
        monkeypatch.setattr(config_loader, "save_config", lambda c: saved.append(c))
        config = {}
        assert main_module.choose_engine(config) == "rapidocr"
        assert config["ocr"]["engine"] == "rapidocr"
        assert saved == []

    def test_normalize_engine(self, qapp):
        """卡片 key → 配置权威值映射"""
        assert main_module._normalize_engine("gguf") == "gguf"
        assert main_module._normalize_engine("rapid") == "rapidocr"

    def test_show_dialog_rejected_quits_and_exits(self, qapp, monkeypatch):
        """对话框 rejected → QApplication.quit() + SystemExit，绝不带默认值进入"""
        import app.ui.engine_select_dialog as dialog_module
        import app.utils.engine_checker as checker_module
        monkeypatch.delenv("PDFOCR_ENGINE", raising=False)

        class FakeDialog:
            def __init__(self, config):
                pass

            def set_availability(self, avail):
                pass

            def exec(self):
                return QDialog.DialogCode.Rejected

            def selected_engine(self):
                return None

        monkeypatch.setattr(dialog_module, "EngineSelectDialog", FakeDialog)
        monkeypatch.setattr(checker_module, "check_engine_availability",
                            lambda c: _FAKE_AVAILABILITY)
        quits = []
        monkeypatch.setattr(QApplication, "quit", lambda: quits.append(1))
        with pytest.raises(SystemExit):
            main_module._show_engine_dialog({})
        assert quits == [1]

    def test_rejected_exit_not_swallowed_by_choose_engine(self, qapp, monkeypatch):
        """rejected 的退出不被 choose_engine 吞掉"""
        monkeypatch.delenv("PDFOCR_ENGINE", raising=False)
        monkeypatch.setattr(main_module, "_show_engine_dialog",
                            lambda c: (_ for _ in ()).throw(SystemExit(0)))
        with pytest.raises(SystemExit):
            main_module.choose_engine({})
