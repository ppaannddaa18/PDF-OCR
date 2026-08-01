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
        QTest.mouseClick(dialog.enter_btn, Qt.MouseButton.LeftButton)
        assert dialog.result() == QDialog.DialogCode.Accepted  # 进入
        assert len(dialog.findChildren(InfoBar)) == 1  # 不重复弹


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
