# tests/ui/test_animation_manager.py
"""AnimationManager 单元测试（Task 14）"""
import pytest
from PyQt6.QtCore import QAbstractAnimation
from PyQt6.QtTest import QTest
from PyQt6.QtWidgets import QWidget

from app.ui.animation_manager import AnimationManager

# 模块加载时的初始状态（反映系统 reduced-motion 检测结果），作为默认值断言基准
_INITIAL_ENABLED = AnimationManager.is_enabled()


@pytest.fixture(autouse=True)
def reset_animation_manager():
    """每个测试后复位全局动画状态，避免跨测试/跨文件污染"""
    yield
    AnimationManager.stop_all()
    AnimationManager.set_enabled(_INITIAL_ENABLED)


class TestAnimationManager:
    def test_default_enabled_matches_detected_preference(self, qapp):
        """默认状态与模块加载时检测到的系统动画偏好一致（非恒真：与检测值比对）"""
        assert isinstance(_INITIAL_ENABLED, bool)
        assert AnimationManager.is_enabled() is _INITIAL_ENABLED

    def test_set_enabled_toggles_state(self, qapp):
        AnimationManager.set_enabled(False)
        assert AnimationManager.is_enabled() is False
        AnimationManager.set_enabled(True)
        assert AnimationManager.is_enabled() is True

    def test_animate_disabled_sets_final_value_and_returns_none(self, qapp):
        """禁用动画时直接设置最终值且返回 None"""
        AnimationManager.set_enabled(False)
        widget = QWidget()
        widget.setMinimumWidth(100)
        assert widget.minimumWidth() == 100

        result = AnimationManager.animate(widget, b"minimumWidth", 100, 300)
        assert result is None
        assert widget.minimumWidth() == 300

    def test_animate_enabled_returns_running_animation(self, qapp):
        """启用动画时返回运行中的动画对象，属性不直接跳到最终值"""
        AnimationManager.set_enabled(True)
        widget = QWidget()
        widget.setMinimumWidth(100)

        anim = AnimationManager.animate(widget, b"minimumWidth", 100, 300, duration=1000)
        assert anim is not None
        assert anim.state() == QAbstractAnimation.State.Running
        # 动画刚启动（currentTime=0），属性仍为起始值
        assert widget.minimumWidth() == 100
        assert anim in AnimationManager._animations

    def test_animate_finished_removes_from_registry(self, qapp):
        """动画自然结束后从注册表移除，属性到达最终值"""
        AnimationManager.set_enabled(True)
        widget = QWidget()
        anim = AnimationManager.animate(widget, b"minimumWidth", 100, 300, duration=10)
        assert anim is not None

        QTest.qWait(150)  # 等待 10ms 动画完成
        assert anim not in AnimationManager._animations
        assert widget.minimumWidth() == 300

    def test_stop_all_stops_and_clears_registry(self, qapp):
        """stop_all 停止全部动画并清空注册表，未完成动画不跳到最终值"""
        AnimationManager.set_enabled(True)
        widget = QWidget()
        AnimationManager.animate(widget, b"minimumWidth", 100, 300, duration=5000)
        AnimationManager.animate(widget, b"maximumWidth", 100, 400, duration=5000)
        assert len(AnimationManager._animations) == 2

        AnimationManager.stop_all()
        assert AnimationManager._animations == []
        assert widget.minimumWidth() == 100  # 立即停止，未完成则停留在起始值

    def test_explicit_stop_removes_animation_from_registry(self, qapp):
        """I-1 回归：显式 stop()（不发射 finished）后动画仍从注册表移除

        组件快速折叠/展开时 stop 旧动画，若不清理将永久滞留注册表造成内存泄漏
        """
        AnimationManager.set_enabled(True)
        widget = QWidget()
        anim = AnimationManager.animate(widget, b"minimumWidth", 100, 300, duration=5000)
        assert anim in AnimationManager._animations  # 运行中保留

        anim.stop()
        assert anim.state() == QAbstractAnimation.State.Stopped
        assert anim not in AnimationManager._animations  # stop 后立即清理

    def test_rapid_toggle_no_registry_leak(self, qapp):
        """I-1 触发路径回归：快速折叠/展开（每轮 stop 旧动画）后注册表无残留"""
        from PyQt6.QtTest import QTest
        from app.ui.widgets.collapsible_panel import CollapsiblePanel

        AnimationManager.set_enabled(True)
        panel = CollapsiblePanel()
        for _ in range(5):
            panel.collapse()
            panel.expand()
        QTest.qWait(400)  # 等待最后一轮 300ms 动画自然结束
        assert AnimationManager._animations == []

    def test_animate_disabled_then_enabled_recovers_animation(self, qapp):
        """禁用时 setProperty 直接生效后，重新启用动画仍可正常运行"""
        AnimationManager.set_enabled(False)
        widget = QWidget()
        assert AnimationManager.animate(widget, b"minimumWidth", 100, 300) is None
        assert widget.minimumWidth() == 300

        AnimationManager.set_enabled(True)
        anim = AnimationManager.animate(widget, b"minimumWidth", 300, 100, duration=1000)
        assert anim is not None
        assert anim.state() == QAbstractAnimation.State.Running
        assert widget.minimumWidth() == 300  # 动画尚未运行，属性保持禁用时设置的最终值
