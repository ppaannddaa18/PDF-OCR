# app/ui/theme_manager.py
import types
import weakref

from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget


class ThemeManager:
    """主题管理器 - 集中管理所有视觉常量

    Task 15 增强：
    - 刷新回调注册表：组件在 __init__ 时注册 apply_theme（弱引用），
      set_theme 切换主题后自动调用全部回调，使构造时烘焙进 QSS 字符串的
      颜色重新生成（unpolish/polish 不足以刷新内嵌样式表）
    - detect_system_theme / resolve_theme：'auto' 模式跟随系统主题
      （Qt 6.5+ QStyleHints.colorScheme()，已验证 PyQt6 6.11 可用）

    Task P2 增强（双设计 token 管道）：
    - 新增 design 维度：'default' | 'gguf'（固定深色科技）| 'rapid'（固定浅色简洁）
    - COLORS 按 design 嵌套；design 非 default 时 get_color 忽略 _current_theme，
      直接取该设计唯一调色板（gguf 仅 dark / rapid 仅 light）；default 行为不变
    - set_design 切换同样触发 _invoke_refresh_callbacks（复用弱引用注册表），
      已注册 apply_theme 的组件零代码改动自动换色
    - apply_card_shadow：Rapid 卡片阴影（QSS 不支持 box-shadow 的替代方案）
    - FONTS 新增 mono 家族（数字指标），QFontDatabase 按 family 查找，
      缺省回退 'Courier New'
    """

    _current_theme = 'light'
    _current_design = 'default'
    _refresh_callbacks = []  # weakref.WeakMethod / weakref.ref 列表（组件销毁后自动失效）
    _mono_family_cache = {}  # (preferred, fallback) -> family，避免每次 get_font 枚举系统字体

    _THEMES = ('light', 'dark')

    COLORS = {
        # ── default：与改造前完全一致（light/dark 双主题） ─────────
        'default': {
            'light': {
                'bg_primary': '#f8f9fa',
                'bg_surface': '#ffffff',
                'bg_hover': '#f3f4f6',
                'bg_selected': '#eff6ff',
                'primary': '#2563eb',
                'primary_hover': '#1d4ed8',
                'white': '#ffffff',
                'on_accent': '#ffffff',
                'success_bg': '#E7F5E9',
                'warning_bg': '#FFF8E1',
                'error_bg': '#FDE8E8',
                'success': '#16a34a',
                'warning': '#f59e0b',
                'warning_text': '#b45309',
                'error': '#dc2626',
                'text_primary': '#1f2937',
                'text_secondary': '#6b7280',
                'text_disabled': '#9ca3af',
                'border': '#e5e7eb',
                'border_focus': '#2563eb',
                'match_alt_bg': '#FFF0E5',   # 三级匹配（关键词兜底）底色
                'edited_bg': '#E5F3FF',      # 手动编辑单元格底色
            },
            'dark': {
                'bg_primary': '#111827',
                'bg_surface': '#1f2937',
                'bg_hover': '#374151',
                'bg_selected': '#1e3a5f',
                'primary': '#3b82f6',
                'primary_hover': '#2563eb',
                'white': '#ffffff',
                'on_accent': '#ffffff',
                'success_bg': '#12301B',
                'warning_bg': '#3A2F14',
                'error_bg': '#3A1518',
                'success': '#22c55e',
                'warning': '#fbbf24',
                'warning_text': '#fbbf24',
                'error': '#ef4444',
                'text_primary': '#f9fafb',
                'text_secondary': '#d1d5db',
                'text_disabled': '#9ca3af',
                'border': '#374151',
                'border_focus': '#3b82f6',
                'match_alt_bg': '#3A2414',   # 三级匹配（关键词兜底）底色
                'edited_bg': '#1E3A5F',      # 手动编辑单元格底色
            },
        },
        # ── gguf：暗松绿 × 黄铜金「信号台」（重设计，固定深色） ────
        # 设计方向：本地推理是"看机器工作"——信号台/老式仪表盘的语言。
        # 深松绿黑底（区别于旧版海军蓝）、黄铜金动作色、鼠尾草绿状态色；
        # 大胆度花在黄铜发光带与等宽读数上，其余保持安静。
        'gguf': {
            'dark': {
                'bg_primary': '#10150F',          # 深松绿黑
                'bg_surface': '#171E16',          # 面板松绿
                'surface_2': '#202A1E',           # 浮起
                'bg_hover': '#202A1E',            # = surface_2
                'bg_selected': '#2A3526',         # 选中底
                'primary': '#C9A227',             # 黄铜金
                'primary_hover': '#A9881E',       # 黄铜压暗
                'white': '#ffffff',
                'on_accent': '#10150F',           # 黄铜底上的深松绿黑文字（对比度达标）
                'success_bg': '#172616',
                'warning_bg': '#332B14',
                'error_bg': '#331A16',
                'success': '#8FB573',             # 鼠尾草绿
                'warning': '#E0B23C',
                'warning_text': '#E0B23C',
                'error': '#E2574C',               # 信号红
                'text_primary': '#E9E7D9',        # 骨白
                'text_secondary': '#A5AC97',
                'text_disabled': '#6C725E',
                'border': '#2F3B2C',
                'border_focus': '#C9A227',        # = accent
                'accent': '#C9A227',              # 黄铜金
                'accent_alt': '#8FB573',          # 鼠尾草绿（状态/数据）
                'match_alt_bg': '#33260F',        # 关键词兜底（琥珀压暗）
                'edited_bg': '#20303F',           # 手动编辑（冷蓝压暗）
            },
        },
        # ── rapid：暖纸 × 墨色 × 档案绿「文具档案室」（重设计，固定浅色） ──
        # 设计方向：文档处理是"桌面上的纸活"——暖纸底 + 墨色文字 +
        # 深档案绿主色；荧光笔框选签名保留（黄与绿互补），卡片阴影延续。
        'rapid': {
            'light': {
                'bg_primary': '#F6F3ED',          # 暖纸
                'bg_surface': '#FFFFFF',          # 卡片
                'surface_2': '#EFEAE2',           # 悬停
                'bg_hover': '#EFEAE2',
                'bg_selected': '#E4F0E8',         # 浅档案绿底
                'primary': '#1E7B5C',             # 档案绿
                'primary_hover': '#186347',       # 压暗
                'white': '#ffffff',
                'on_accent': '#ffffff',
                'success_bg': '#E4F0E8',
                'warning_bg': '#F7ECD8',
                'error_bg': '#F8E3E1',
                'success': '#1E7B5C',
                'warning': '#C77F1D',
                'warning_text': '#A35E12',
                'error': '#C2423C',
                'text_primary': '#2A2724',        # 墨色
                'text_secondary': '#6E675E',
                'text_disabled': '#A39B8E',
                'border': '#E0DACD',
                'border_focus': '#1E7B5C',        # = accent
                'accent': '#1E7B5C',              # 档案绿
                'accent_alt': '#0E7490',          # 汽油蓝（次级数据色）
                'match_alt_bg': '#F3E3C8',        # 关键词兜底（暖橙浅底）
                'edited_bg': '#E4EEF7',           # 手动编辑（浅蓝底）
            },
        },
    }

    FONTS = {
        'heading': {'size': 18, 'weight': 600, 'line_height': 1.4},
        'subheading': {'size': 14, 'weight': 500, 'line_height': 1.4},
        'body': {'size': 13, 'weight': 400, 'line_height': 1.5},
        'caption': {'size': 11, 'weight': 400, 'line_height': 1.4},
        'button': {'size': 13, 'weight': 500, 'line_height': 1.0},
        # P2 新增 mono 家族：数字指标用（Consolas 优先，缺省回退 Courier New）
        'mono': {'size': 13, 'weight': 400, 'line_height': 1.4,
                 'family': 'Consolas', 'fallback_family': 'Courier New'},
    }

    SPACING = {
        'xs': 4,
        'sm': 8,
        'md': 12,
        'lg': 16,
        'xl': 24,
        '2xl': 32,
    }

    RADIUS = {
        # P2：gguf 更锐利（科技感）、rapid 更圆润（简洁风）
        'default': {'sm': 4, 'md': 8, 'lg': 12, 'full': 9999},
        'gguf': {'sm': 2, 'md': 4, 'lg': 6, 'full': 9999},
        'rapid': {'sm': 4, 'md': 8, 'lg': 12, 'full': 9999},
    }

    @classmethod
    def _active_palette(cls) -> dict:
        """当前 design 生效的颜色表

        design 非 default 时忽略 _current_theme，直接取该设计唯一调色板
        （gguf→dark / rapid→light，显式映射而非 next(iter())，未来某设计
        增加第二调色板时不会静默任选）；default 时取当前主题表（与改造前一致）。
        """
        design = cls._current_design
        if design == 'default':
            return cls.COLORS['default'][cls._current_theme]
        palette_key = {'gguf': 'dark', 'rapid': 'light'}[design]
        return cls.COLORS[design][palette_key]

    @classmethod
    def get_color(cls, role: str) -> str:
        """获取当前主题下的颜色值（design 感知）"""
        palette = cls._active_palette()
        if role not in palette:
            raise ValueError(f"Unknown color role: {role}")
        return palette[role]

    @classmethod
    def get_font(cls, level: str) -> QFont:
        """获取指定层级的字体

        FONTS 目前与 design/theme 无关（P2 简报未定义设计专属字体规格）；
        'mono' 层级带 family 解析：QFontDatabase 按 family 查找，
        缺省回退 'Courier New'。
        """
        if level not in cls.FONTS:
            raise ValueError(f"Unknown font level: {level}")
        config = cls.FONTS[level]
        font = QFont()
        family = config.get('family')
        if family:
            font.setFamily(cls._resolve_mono_family(
                family, config.get('fallback_family')))
        font.setPointSize(config['size'])
        font.setWeight(config['weight'])
        return font

    @classmethod
    def _resolve_mono_family(cls, preferred: str, fallback: str = None) -> str:
        """按 QFontDatabase 查找字体族，系统缺失时回退；结果按 (preferred, fallback) 缓存"""
        key = (preferred, fallback)
        cached = cls._mono_family_cache.get(key)
        if cached is not None:
            return cached
        try:
            from PyQt6.QtGui import QFontDatabase
            families = QFontDatabase.families()
            resolved = preferred if preferred in families else (fallback or preferred)
        except (ImportError, RuntimeError):
            resolved = fallback or preferred
        cls._mono_family_cache[key] = resolved
        return resolved

    @classmethod
    def get_spacing(cls, name: str) -> int:
        """获取间距值（SPACING 与 design 无关，简报未定义设计专属间距）"""
        if name not in cls.SPACING:
            raise ValueError(f"Unknown spacing name: {name}")
        return cls.SPACING[name]

    @classmethod
    def get_radius(cls, name: str) -> int:
        """获取圆角值（design 感知：gguf 锐利 / rapid 圆润 / default 现状）"""
        if cls._current_design == 'default':
            table = cls.RADIUS['default']
        else:
            table = cls.RADIUS[cls._current_design]
        if name not in table:
            raise ValueError(f"Unknown radius name: {name}")
        return table[name]

    @classmethod
    def current_theme(cls) -> str:
        """获取当前主题名称"""
        return cls._current_theme

    @classmethod
    def current_design(cls) -> str:
        """获取当前设计名称（'default' | 'gguf' | 'rapid'）"""
        return cls._current_design

    # ── 设计/主题切换与全局刷新 ────────────────────────────────

    @classmethod
    def register_refresh_callback(cls, callback) -> None:
        """注册主题刷新回调：set_theme / set_design 后自动调用

        回调以弱引用持有（WeakMethod/ref），组件被 GC 后自动失效，
        无需显式注销。典型用法：组件 __init__ 末尾
        ``ThemeManager.register_refresh_callback(self.apply_theme)``。
        """
        if callback is None:
            return
        if isinstance(callback, types.MethodType):
            ref = weakref.WeakMethod(callback)
        else:
            ref = weakref.ref(callback)
        cls._refresh_callbacks.append(ref)

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """设置当前主题，并触发全部已注册的刷新回调

        相同主题重复调用为 no-op（组件构造/刷新后状态已一致，
        避免启动双接线时重复刷新）。
        design 非 default（gguf/rapid 固定单色调板）时 no-op：
        主题切换不生效，get_color 不受 _current_theme 影响。
        """
        if theme not in cls._THEMES:
            raise ValueError(f"Unknown theme: {theme}")
        if cls._current_design != 'default':
            return
        if theme == cls._current_theme:
            return
        cls._current_theme = theme
        cls._invoke_refresh_callbacks()

    @classmethod
    def set_design(cls, design: str) -> None:
        """设置设计（'default' | 'gguf' | 'rapid'），变化时触发刷新回调

        gguf/rapid 为固定单色调板设计，切换后 get_color/get_radius 等
        token 立即按新设计解析（已注册组件经回调自动重建 QSS）。
        """
        if design not in cls.COLORS:
            raise ValueError(f"Unknown design: {design}")
        if design == cls._current_design:
            return
        cls._current_design = design
        cls._invoke_refresh_callbacks()

    @classmethod
    def _invoke_refresh_callbacks(cls) -> None:
        """调用全部刷新回调；失效（已销毁）回调在本轮清理"""
        dead = []
        for ref in cls._refresh_callbacks:
            callback = ref()
            if callback is None:
                dead.append(ref)
                continue
            try:
                callback()
            except RuntimeError:
                # 组件 C++ 对象已销毁，标记清理
                dead.append(ref)
            except Exception:
                # 单个组件刷新失败不应阻断其余组件
                pass
        for ref in dead:
            try:
                cls._refresh_callbacks.remove(ref)
            except ValueError:
                pass

    # ── 系统主题检测（'auto' 跟随系统） ─────────────────────────

    @classmethod
    def detect_system_theme(cls) -> str:
        """检测系统主题（'light' | 'dark'）

        Qt 6.5+：QApplication.styleHints().colorScheme() 返回
        Qt.ColorScheme（Unknown/Light/Dark）——已验证 PyQt6 6.11 可用。
        API 不可用或检测失败时回退 'light'（与旧行为一致）。
        """
        try:
            from PyQt6.QtCore import Qt
            from PyQt6.QtWidgets import QApplication
            app = QApplication.instance()
            if app is None:
                return 'light'
            scheme = app.styleHints().colorScheme()
            if scheme == Qt.ColorScheme.Dark:
                return 'dark'
            return 'light'
        except Exception:
            return 'light'

    @classmethod
    def resolve_theme(cls, mode: str) -> str:
        """解析主题模式 → 实际生效主题

        'auto' → 跟随系统（detect_system_theme）；
        'light'/'dark' → 原样返回。
        """
        if mode == 'auto':
            return cls.detect_system_theme()
        if mode not in cls._THEMES:
            raise ValueError(f"Unknown theme: {mode}")
        return mode

    @classmethod
    def apply_stylesheet(cls, widget: QWidget, styles: dict) -> None:
        """应用样式到控件

        Args:
            widget: 目标控件
            styles: 样式字典，如 {'background': 'bg_primary', 'color': 'text_primary'}
                   值如果是颜色角色名，会自动解析为实际颜色值
        """
        style_parts = []
        palette = cls._active_palette()
        for prop, value in styles.items():
            # 如果值是颜色角色名，解析为实际颜色
            if value in palette:
                value = cls.get_color(value)
            style_parts.append(f"{prop}: {value};")
        widget.setStyleSheet("".join(style_parts))

    # ── 卡片阴影（Rapid 用，QSS 无 box-shadow 的替代方案） ──────

    @classmethod
    def apply_card_shadow(cls, widget: QWidget) -> 'QGraphicsDropShadowEffect':
        """给控件挂载卡片阴影

        blur ~12、轻微下投偏移 (0, 2)、rgba(15,23,42,0.06)（alpha=0.06*255≈15）。
        """
        from PyQt6.QtGui import QColor
        from PyQt6.QtWidgets import QGraphicsDropShadowEffect
        effect = QGraphicsDropShadowEffect(widget)
        effect.setBlurRadius(12)
        effect.setOffset(0, 2)
        effect.setColor(QColor(15, 23, 42, round(0.06 * 255)))
        widget.setGraphicsEffect(effect)
        return effect
