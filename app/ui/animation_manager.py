"""
动画管理器 - 统一管理所有界面动画，支持全局禁用与系统 reduced-motion 偏好

设计：
- 所有组件动画统一通过 AnimationManager.animate() 创建，便于集中启停控制
- 禁用动画时 animate() 直接设置目标属性的最终值并返回 None（无动画对象），
  调用方需容忍返回值为 None（如 finished 连接的隐藏逻辑需处理 None 分支）
- 管理器持有所有动画的强引用（_animations），防止被 Python GC 回收导致动画中断；
  动画自然结束或被销毁时自动从注册表移除
- 模块加载时检测系统动画偏好（prefers-reduced-motion）：
  - 首选 QStyleHints.Feature.AnimationsEnabled（Qt >= 6.10，hasFeature 判断）
  - 回退 QStyleHints.animationsEnabled()（部分 PyQt6 绑定以方法/属性暴露）
  - 两个 API 均不可用（如本机 PyQt6 6.11.0 / Qt 6.11.1 的 QStyleHints 未暴露
    任何动画相关 API，经验证 dir() 无 animationsEnabled/hasFeature/Feature）
    或检测失败时 try/except 保护并默认启用动画（_enabled = True）
"""
from PyQt6.QtCore import QObject, QPropertyAnimation, QEasingCurve, QAbstractAnimation


def _detect_system_animations_enabled() -> bool:
    """检测系统动画偏好（prefers-reduced-motion），API 不可用时默认启用

    返回 False 表示系统禁用了动画（Windows「显示动画」关闭等），
    此时 AnimationManager 初始化为禁用状态。
    """
    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QStyleHints

        app = QApplication.instance()
        if app is None:
            return True
        style_hints = app.styleHints()

        # 首选：Qt >= 6.10 的 QStyleHints.Feature.AnimationsEnabled
        feature_enum = getattr(QStyleHints, "Feature", None)
        if feature_enum is not None and hasattr(feature_enum, "AnimationsEnabled"):
            has_feature = getattr(style_hints, "hasFeature", None)
            if has_feature is not None:
                return bool(has_feature(feature_enum.AnimationsEnabled))

        # 回退：animationsEnabled() 方法/属性（部分 PyQt6 绑定提供）
        animations_enabled = getattr(style_hints, "animationsEnabled", None)
        if animations_enabled is not None:
            result = animations_enabled()
            if result is not None:
                return bool(result)
    except Exception:
        pass
    # API 不可用或检测失败：默认启用
    return True


class AnimationManager(QObject):
    """动画管理器 - 统一管理所有动画，支持禁用"""

    _enabled = _detect_system_animations_enabled()
    _animations = []

    @classmethod
    def is_enabled(cls) -> bool:
        """动画是否启用"""
        return cls._enabled

    @classmethod
    def set_enabled(cls, enabled: bool):
        """设置动画启用状态"""
        cls._enabled = enabled

    @classmethod
    def animate(cls, target, property_name: bytes, start_value, end_value,
                duration: int = 300, easing: QEasingCurve.Type = QEasingCurve.Type.InOutCubic):
        """创建并启动动画

        Args:
            target: 动画目标对象（QObject，如 QWidget）
            property_name: 目标属性名（bytes，如 b"pos" / b"minimumWidth"）
            start_value: 起始值
            end_value: 结束值
            duration: 动画时长（ms），默认 300
            easing: 缓动曲线，默认 InOutCubic

        Returns:
            运行中的动画对象；动画禁用时直接设置最终值并返回 None
        """
        if not cls._enabled:
            # 如果动画禁用，直接设置最终值
            target.setProperty(property_name.decode(), end_value)
            return None

        animation = QPropertyAnimation(target, property_name)
        animation.setDuration(duration)
        animation.setStartValue(start_value)
        animation.setEndValue(end_value)
        animation.setEasingCurve(easing)
        animation.start()

        cls._animations.append(animation)

        def _cleanup():
            try:
                cls._animations.remove(animation)
            except ValueError:
                pass  # 已被 stop_all 等移除，容忍重复清理

        def _on_state_changed(state, _old_state):
            # Stopped 状态覆盖两条结束路径：自然完成（finished）与显式 stop()
            # （stop() 不发射 finished；组件快速折叠/展开时 stop 旧动画，若不在此
            # 清理会永久滞留在注册表造成内存泄漏，见 I-1）
            if state == QAbstractAnimation.State.Stopped:
                _cleanup()

        # 注意：只连接 stateChanged，不连接 destroyed —— PyQt 在 C++ 对象析构期间
        # 回调 Python 槽可能导致进程级崩溃（无 Python 异常直接退出），实测验证；
        # 动画目标销毁导致的失效对象由 stop_all 的 RuntimeError 守卫兜底
        animation.stateChanged.connect(_on_state_changed)

        return animation

    @classmethod
    def stop_all(cls):
        """停止所有动画"""
        for anim in cls._animations[:]:
            try:
                anim.stop()
            except RuntimeError:
                pass  # 动画对象已随目标销毁而失效，跳过
            try:
                cls._animations.remove(anim)
            except ValueError:
                pass  # stop() 同步触发 stateChanged 清理时已被移除


def apply_config_animation_setting(config: dict) -> bool:
    """应用 config 的动画设置（appearance.animations_enabled）

    仅当 config 显式包含该键时应用并返回 True（覆盖系统 reduced-motion
    检测）；无键（旧配置）时保持系统检测并返回 False。修复 Rapid 设置
    对话框保存后下次启动不恢复的问题（main.py 启动时调用）。
    """
    appearance = (config or {}).get("appearance", {})
    if "animations_enabled" not in appearance:
        return False
    AnimationManager.set_enabled(bool(appearance["animations_enabled"]))
    return True
