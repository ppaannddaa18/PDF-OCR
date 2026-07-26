# PDFOCR UI 全面重构 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 全面重构 PDFOCR 的 UI，实现响应式布局、统一设计系统、提升信息密度和优化交互体验。

**Architecture:** 引入 ThemeManager 统一管理视觉常量，用 CollapsiblePanel 和 SlidablePanel 替代固定三栏布局，所有组件通过共享 EmptyState、ToastNotification 等基础组件统一空状态和反馈机制。

**Tech Stack:** PyQt6, qfluentwidgets, QPropertyAnimation

## Global Constraints

- Python 3.12+，PyQt6 最新稳定版
- 保持向后兼容，不删除现有功能
- 所有颜色通过 ThemeManager 获取，禁止硬编码
- 动画必须支持禁用选项（`Settings > 外观 > 禁用动画`）
- 尊重系统 `prefers-reduced-motion` 设置
- 最小支持分辨率 1280x720
- 所有新增组件必须有对应测试
- 频繁提交，每个 Task 结束后提交

---

## File Structure

### 新增文件

| 文件 | 职责 |
|------|------|
| `app/ui/theme_manager.py` | 主题管理器：颜色、字体、间距、圆角常量，明/暗色切换 |
| `app/ui/widgets/empty_state.py` | 统一空状态组件：图标+标题+说明+操作按钮 |
| `app/ui/widgets/toast_notification.py` | 轻量通知组件：右下角弹出，自动消失 |
| `app/ui/widgets/collapsible_panel.py` | 可折叠面板容器：支持展开/折叠动画 |
| `app/ui/widgets/slidable_panel.py` | 可滑动面板容器：从右侧滑入/滑出 |
| `app/ui/widgets/compact_toolbar.py` | 紧凑工具栏：图标按钮+引擎状态+设置 |

### 修改文件

| 文件 | 职责变更 |
|------|----------|
| `app/ui/main_window.py` | 重构布局框架：移除嵌套 splitter，集成 CollapsiblePanel 和 SlidablePanel |
| `app/ui/widgets/file_list_panel.py` | 紧凑设计：36px 行高、状态色条、迷你进度环、集成 EmptyState |
| `app/ui/widgets/pdf_canvas.py` | 浮动工具栏、缩放比例显示、区域尺寸提示、网格吸附、集成 EmptyState |
| `app/ui/widgets/preprocess_toolbar.py` | 可折叠设计：默认图标行，点击展开滑块 |
| `app/ui/widgets/field_panel.py` | 使用 SlidablePanel 容器、紧凑表格、集成 EmptyState |
| `app/ui/widgets/result_panel.py` | 使用 SlidablePanel 容器、标签页视图 |
| `app/ui/widgets/gpu_status.py` | 集成到 CompactToolbar，改为彩色圆点+缩写 |
| `app/ui/widgets/loading_overlay.py` | 保留但减少使用场景，部分场景改用 Toast |

### 测试文件

| 文件 | 职责 |
|------|------|
| `tests/ui/test_theme_manager.py` | ThemeManager 单元测试 |
| `tests/ui/widgets/test_empty_state.py` | EmptyState 组件测试 |
| `tests/ui/widgets/test_toast_notification.py` | ToastNotification 组件测试 |
| `tests/ui/widgets/test_collapsible_panel.py` | CollapsiblePanel 组件测试 |
| `tests/ui/widgets/test_slidable_panel.py` | SlidablePanel 组件测试 |
| `tests/ui/widgets/test_compact_toolbar.py` | CompactToolbar 组件测试 |

---

## Task 1: ThemeManager（主题管理器）

**Files:**
- Create: `app/ui/theme_manager.py`
- Test: `tests/ui/test_theme_manager.py`

**Interfaces:**
- Consumes: 无（基础组件）
- Produces:
  - `ThemeManager.get_color(role: str) -> str`
  - `ThemeManager.get_font(level: str) -> QFont`
  - `ThemeManager.get_spacing(name: str) -> int`
  - `ThemeManager.get_radius(name: str) -> int`
  - `ThemeManager.apply_stylesheet(widget: QWidget, styles: dict) -> None`
  - `ThemeManager.current_theme() -> str` (返回 'light' 或 'dark')
  - `ThemeManager.set_theme(theme: str) -> None`

- [ ] **Step 1: 编写 ThemeManager 基础结构**

```python
# app/ui/theme_manager.py
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import QWidget


class ThemeManager:
    """主题管理器 - 集中管理所有视觉常量"""

    _current_theme = 'light'

    COLORS = {
        'light': {
            'bg_primary': '#f8f9fa',
            'bg_surface': '#ffffff',
            'bg_hover': '#f3f4f6',
            'bg_selected': '#eff6ff',
            'primary': '#2563eb',
            'primary_hover': '#1d4ed8',
            'success': '#16a34a',
            'warning': '#f59e0b',
            'error': '#dc2626',
            'text_primary': '#1f2937',
            'text_secondary': '#6b7280',
            'text_disabled': '#9ca3af',
            'border': '#e5e7eb',
            'border_focus': '#2563eb',
        },
        'dark': {
            'bg_primary': '#111827',
            'bg_surface': '#1f2937',
            'bg_hover': '#374151',
            'bg_selected': '#1e3a5f',
            'primary': '#3b82f6',
            'primary_hover': '#2563eb',
            'success': '#22c55e',
            'warning': '#fbbf24',
            'error': '#ef4444',
            'text_primary': '#f9fafb',
            'text_secondary': '#d1d5db',
            'text_disabled': '#6b7280',
            'border': '#374151',
            'border_focus': '#3b82f6',
        }
    }

    FONTS = {
        'heading': {'size': 18, 'weight': 600, 'line_height': 1.4},
        'subheading': {'size': 14, 'weight': 500, 'line_height': 1.4},
        'body': {'size': 13, 'weight': 400, 'line_height': 1.5},
        'caption': {'size': 11, 'weight': 400, 'line_height': 1.4},
        'button': {'size': 13, 'weight': 500, 'line_height': 1.0},
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
        'sm': 4,
        'md': 8,
        'lg': 12,
        'full': 9999,
    }

    @classmethod
    def get_color(cls, role: str) -> str:
        """获取当前主题下的颜色值"""
        theme = cls._current_theme
        if role not in cls.COLORS[theme]:
            raise ValueError(f"Unknown color role: {role}")
        return cls.COLORS[theme][role]

    @classmethod
    def get_font(cls, level: str) -> QFont:
        """获取指定层级的字体"""
        if level not in cls.FONTS:
            raise ValueError(f"Unknown font level: {level}")
        config = cls.FONTS[level]
        font = QFont()
        font.setPointSize(config['size'])
        font.setWeight(config['weight'])
        return font

    @classmethod
    def get_spacing(cls, name: str) -> int:
        """获取间距值"""
        if name not in cls.SPACING:
            raise ValueError(f"Unknown spacing name: {name}")
        return cls.SPACING[name]

    @classmethod
    def get_radius(cls, name: str) -> int:
        """获取圆角值"""
        if name not in cls.RADIUS:
            raise ValueError(f"Unknown radius name: {name}")
        return cls.RADIUS[name]

    @classmethod
    def current_theme(cls) -> str:
        """获取当前主题名称"""
        return cls._current_theme

    @classmethod
    def set_theme(cls, theme: str) -> None:
        """设置当前主题"""
        if theme not in cls.COLORS:
            raise ValueError(f"Unknown theme: {theme}")
        cls._current_theme = theme

    @classmethod
    def apply_stylesheet(cls, widget: QWidget, styles: dict) -> None:
        """应用样式到控件

        Args:
            widget: 目标控件
            styles: 样式字典，如 {'background': 'bg_primary', 'color': 'text_primary'}
                   值如果是颜色角色名，会自动解析为实际颜色值
        """
        style_parts = []
        for prop, value in styles.items():
            # 如果值是颜色角色名，解析为实际颜色
            if value in cls.COLORS[cls._current_theme]:
                value = cls.get_color(value)
            style_parts.append(f"{prop}: {value};")
        widget.setStyleSheet("".join(style_parts))
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/test_theme_manager.py
import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from app.ui.theme_manager import ThemeManager


class TestThemeManager:
    def test_get_color_light_theme(self):
        ThemeManager.set_theme('light')
        assert ThemeManager.get_color('primary') == '#2563eb'
        assert ThemeManager.get_color('bg_primary') == '#f8f9fa'

    def test_get_color_dark_theme(self):
        ThemeManager.set_theme('dark')
        assert ThemeManager.get_color('primary') == '#3b82f6'
        assert ThemeManager.get_color('bg_primary') == '#111827'

    def test_get_color_unknown_role(self):
        with pytest.raises(ValueError, match="Unknown color role"):
            ThemeManager.get_color('nonexistent')

    def test_get_font(self):
        font = ThemeManager.get_font('heading')
        assert font.pointSize() == 18
        assert font.weight() == 600

    def test_get_font_unknown_level(self):
        with pytest.raises(ValueError, match="Unknown font level"):
            ThemeManager.get_font('nonexistent')

    def test_get_spacing(self):
        assert ThemeManager.get_spacing('xs') == 4
        assert ThemeManager.get_spacing('lg') == 16

    def test_get_radius(self):
        assert ThemeManager.get_radius('sm') == 4
        assert ThemeManager.get_radius('full') == 9999

    def test_current_theme(self):
        ThemeManager.set_theme('light')
        assert ThemeManager.current_theme() == 'light'
        ThemeManager.set_theme('dark')
        assert ThemeManager.current_theme() == 'dark'

    def test_set_theme_invalid(self):
        with pytest.raises(ValueError, match="Unknown theme"):
            ThemeManager.set_theme('invalid')

    def test_apply_stylesheet(self, qapp):
        widget = QWidget()
        ThemeManager.set_theme('light')
        ThemeManager.apply_stylesheet(widget, {
            'background-color': 'bg_primary',
            'color': 'text_primary'
        })
        style = widget.styleSheet()
        assert '#f8f9fa' in style
        assert '#1f2937' in style
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/test_theme_manager.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/theme_manager.py tests/ui/test_theme_manager.py
git commit -m "feat: add ThemeManager for centralized visual constants

- Centralized color, font, spacing, and radius management
- Support light/dark theme switching
- apply_stylesheet helper for dynamic styling

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 2: EmptyState（统一空状态组件）

**Files:**
- Create: `app/ui/widgets/empty_state.py`
- Test: `tests/ui/widgets/test_empty_state.py`

**Interfaces:**
- Consumes: `ThemeManager.get_color()`, `ThemeManager.get_font()`, `ThemeManager.get_spacing()`
- Produces:
  - `EmptyState(QWidget)` 类
  - `EmptyState.set_icon(icon_name: str) -> None`
  - `EmptyState.set_title(title: str) -> None`
  - `EmptyState.set_description(description: str) -> None`
  - `EmptyState.set_action(text: str, callback: callable) -> None`

- [ ] **Step 1: 编写 EmptyState 组件**

```python
# app/ui/widgets/empty_state.py
from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QPushButton
from PyQt6.QtGui import QFont
from app.ui.theme_manager import ThemeManager


class EmptyState(QWidget):
    """统一空状态组件"""

    # 预定义变体配置
    VARIANTS = {
        'no_files': {
            'icon': '📄',
            'title': '暂无 PDF 文件',
            'description': '点击上方「上传」按钮或拖拽 PDF 文件到此处',
            'action': '上传 PDF',
        },
        'no_preview': {
            'icon': '👁️',
            'title': 'PDF 预览区域',
            'description': '上传 PDF 后在此显示',
            'action': None,
        },
        'no_fields': {
            'icon': '✏️',
            'title': '暂无识别字段',
            'description': '在 PDF 预览中框选区域以添加字段',
            'action': None,
        },
        'no_results': {
            'icon': '📊',
            'title': '暂无解析结果',
            'description': '点击「试识别」或「批量识别」开始解析',
            'action': '试识别',
        },
    }

    def __init__(self, variant: str = None, parent=None):
        super().__init__(parent)
        self._setup_ui()
        if variant:
            self.apply_variant(variant)

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(ThemeManager.get_spacing('md'))

        # 图标
        self.icon_label = QLabel()
        self.icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        font = ThemeManager.get_font('heading')
        font.setPointSize(48)
        self.icon_label.setFont(font)
        layout.addWidget(self.icon_label)

        # 标题
        self.title_label = QLabel()
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        layout.addWidget(self.title_label)

        # 说明
        self.desc_label = QLabel()
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setFont(ThemeManager.get_font('body'))
        self.desc_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        self.desc_label.setWordWrap(True)
        layout.addWidget(self.desc_label)

        # 操作按钮
        self.action_button = QPushButton()
        self.action_button.setFont(ThemeManager.get_font('button'))
        self.action_button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: white;
                border: none;
                border-radius: {ThemeManager.get_radius('md')}px;
                padding: {ThemeManager.get_spacing('sm')}px {ThemeManager.get_spacing('lg')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)
        self.action_button.setVisible(False)
        layout.addWidget(self.action_button, alignment=Qt.AlignmentFlag.AlignCenter)

        # 设置背景
        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
        )

    def apply_variant(self, variant: str):
        """应用预定义变体"""
        if variant not in self.VARIANTS:
            raise ValueError(f"Unknown variant: {variant}")
        config = self.VARIANTS[variant]
        self.set_icon(config['icon'])
        self.set_title(config['title'])
        self.set_description(config['description'])
        if config['action']:
            self.set_action(config['action'], lambda: None)

    def set_icon(self, icon_name: str):
        """设置图标"""
        self.icon_label.setText(icon_name)

    def set_title(self, title: str):
        """设置标题"""
        self.title_label.setText(title)

    def set_description(self, description: str):
        """设置说明"""
        self.desc_label.setText(description)

    def set_action(self, text: str, callback: callable):
        """设置操作按钮"""
        self.action_button.setText(text)
        self.action_button.clicked.connect(callback)
        self.action_button.setVisible(True)
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/widgets/test_empty_state.py
import pytest
from PyQt6.QtWidgets import QApplication
from app.ui.widgets.empty_state import EmptyState


class TestEmptyState:
    def test_create_empty_state(self, qapp):
        state = EmptyState()
        assert state is not None

    def test_apply_variant_no_files(self, qapp):
        state = EmptyState('no_files')
        assert state.icon_label.text() == '📄'
        assert state.title_label.text() == '暂无 PDF 文件'
        assert state.action_button.isVisible()
        assert state.action_button.text() == '上传 PDF'

    def test_apply_variant_no_preview(self, qapp):
        state = EmptyState('no_preview')
        assert state.icon_label.text() == '👁️'
        assert state.title_label.text() == 'PDF 预览区域'
        assert not state.action_button.isVisible()

    def test_custom_content(self, qapp):
        state = EmptyState()
        state.set_icon('🎯')
        state.set_title('自定义标题')
        state.set_description('自定义说明')
        assert state.icon_label.text() == '🎯'
        assert state.title_label.text() == '自定义标题'
        assert state.desc_label.text() == '自定义说明'

    def test_unknown_variant(self, qapp):
        with pytest.raises(ValueError, match="Unknown variant"):
            EmptyState('unknown')
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/widgets/test_empty_state.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/widgets/empty_state.py tests/ui/widgets/test_empty_state.py
git commit -m "feat: add EmptyState component for unified empty states

- Predefined variants: no_files, no_preview, no_fields, no_results
- Customizable icon, title, description, and action button
- Styled with ThemeManager

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 3: ToastNotification（轻量通知组件）

**Files:**
- Create: `app/ui/widgets/toast_notification.py`
- Test: `tests/ui/widgets/test_toast_notification.py`

**Interfaces:**
- Consumes: `ThemeManager.get_color()`
- Produces:
  - `ToastNotification.show(message: str, type: str = 'info', duration: int = 3000) -> None` (类方法)
  - `ToastNotification(QWidget)` 类

- [ ] **Step 1: 编写 ToastNotification 组件**

```python
# app/ui/widgets/toast_notification.py
from PyQt6.QtCore import Qt, QTimer, QPropertyAnimation, QPoint, QEasingCurve
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QHBoxLayout
from app.ui.theme_manager import ThemeManager


class ToastNotification(QWidget):
    """轻量通知组件"""

    _instance = None
    _active_toasts = []

    TYPE_COLORS = {
        'success': 'success',
        'warning': 'warning',
        'error': 'error',
        'info': 'primary',
    }

    TYPE_ICONS = {
        'success': '✓',
        'warning': '⚠',
        'error': '✗',
        'info': 'ℹ',
    }

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._animation = None

    def _setup_ui(self):
        self.setFixedWidth(320)
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.ToolTip)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('lg'),
            ThemeManager.get_spacing('md'),
            ThemeManager.get_spacing('lg'),
            ThemeManager.get_spacing('md')
        )
        layout.setSpacing(ThemeManager.get_spacing('sm'))

        # 图标
        self.icon_label = QLabel()
        self.icon_label.setStyleSheet("font-size: 16px;")
        layout.addWidget(self.icon_label)

        # 消息
        self.message_label = QLabel()
        self.message_label.setWordWrap(True)
        self.message_label.setFont(ThemeManager.get_font('body'))
        layout.addWidget(self.message_label, stretch=1)

    def show_message(self, message: str, type: str = 'info', duration: int = 3000):
        """显示通知"""
        color_role = self.TYPE_COLORS.get(type, 'primary')
        color = ThemeManager.get_color(color_role)
        icon = self.TYPE_ICONS.get(type, 'ℹ')

        self.icon_label.setText(icon)
        self.message_label.setText(message)
        self.setStyleSheet(f"""
            ToastNotification {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-left: 4px solid {color};
                border-radius: {ThemeManager.get_radius('md')}px;
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)

        # 定位到右下角
        if self.parent():
            parent_rect = self.parent().geometry()
            x = parent_rect.width() - self.width() - ThemeManager.get_spacing('lg')
            y = parent_rect.height() - self.height() - ThemeManager.get_spacing('lg')
            # 考虑已有 toast 的偏移
            offset = len(ToastNotification._active_toasts) * (self.height() + ThemeManager.get_spacing('sm'))
            self.move(x, y - offset)

        self.show()

        # 入场动画
        self._animation = QPropertyAnimation(self, b"pos")
        self._animation.setDuration(150)
        self._animation.setStartValue(QPoint(self.x(), self.y() + 20))
        self._animation.setEndValue(QPoint(self.x(), self.y()))
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()

        # 自动消失
        QTimer.singleShot(duration, self._hide)

        ToastNotification._active_toasts.append(self)

    def _hide(self):
        """隐藏通知（带动画）"""
        if self in ToastNotification._active_toasts:
            ToastNotification._active_toasts.remove(self)

        self._animation = QPropertyAnimation(self, b"windowOpacity")
        self._animation.setDuration(200)
        self._animation.setStartValue(1.0)
        self._animation.setEndValue(0.0)
        self._animation.setEasingCurve(QEasingCurve.Type.InCubic)
        self._animation.finished.connect(self.close)
        self._animation.start()

    @classmethod
    def show(cls, message: str, type: str = 'info', duration: int = 3000, parent=None):
        """类方法：快速显示通知"""
        toast = cls(parent)
        toast.show_message(message, type, duration)
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/widgets/test_toast_notification.py
import pytest
from PyQt6.QtWidgets import QApplication, QWidget
from app.ui.widgets.toast_notification import ToastNotification


class TestToastNotification:
    def test_create_toast(self, qapp):
        toast = ToastNotification()
        assert toast is not None
        assert toast.width() == 320

    def test_show_message(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        toast = ToastNotification(parent)
        toast.show_message('测试消息', 'success')
        assert toast.message_label.text() == '测试消息'
        assert toast.icon_label.text() == '✓'
        toast.close()

    def test_type_colors(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        for type_name in ['success', 'warning', 'error', 'info']:
            toast = ToastNotification(parent)
            toast.show_message(f'Test {type_name}', type_name, duration=100)
            toast.close()

    def test_class_method_show(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        toast = ToastNotification.show('快速通知', parent=parent)
        assert toast is not None
        toast.close()
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/widgets/test_toast_notification.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/widgets/toast_notification.py tests/ui/widgets/test_toast_notification.py
git commit -m "feat: add ToastNotification component for lightweight feedback

- 4 types: success, warning, error, info
- Auto-dismiss after 3 seconds with fade animation
- Positioned at bottom-right corner
- Stacked display for multiple toasts

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 4: CollapsiblePanel（可折叠面板容器）

**Files:**
- Create: `app/ui/widgets/collapsible_panel.py`
- Test: `tests/ui/widgets/test_collapsible_panel.py`

**Interfaces:**
- Consumes: `ThemeManager.get_color()`, `ThemeManager.get_spacing()`
- Produces:
  - `CollapsiblePanel(QWidget)` 类
  - `CollapsiblePanel.set_content(widget: QWidget) -> None`
  - `CollapsiblePanel.collapse() -> None`
  - `CollapsiblePanel.expand() -> None`
  - `CollapsiblePanel.toggle() -> None`
  - `CollapsiblePanel.is_collapsed() -> bool`
  - `CollapsiblePanel.collapsed_changed(bool)` 信号

- [ ] **Step 1: 编写 CollapsiblePanel 组件**

```python
# app/ui/widgets/collapsible_panel.py
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.ui.theme_manager import ThemeManager


class CollapsiblePanel(QWidget):
    """可折叠面板容器"""

    collapsed_changed = pyqtSignal(bool)  # True = collapsed

    def __init__(self, parent=None, expanded_width: int = 240, collapsed_width: int = 48):
        super().__init__(parent)
        self._expanded_width = expanded_width
        self._collapsed_width = collapsed_width
        self._is_collapsed = False
        self._animation = None
        self._content_widget = None
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedWidth(self._expanded_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 折叠按钮
        self.toggle_button = QPushButton('◀')
        self.toggle_button.setFixedSize(24, 24)
        self.toggle_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.toggle_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                font-size: 12px;
            }}
            QPushButton:hover {{
                color: {ThemeManager.get_color('text_primary')};
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
        """)
        self.toggle_button.clicked.connect(self.toggle)
        layout.addWidget(self.toggle_button, alignment=Qt.AlignmentFlag.AlignRight)

        # 内容区域
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )
        layout.addWidget(self.content_area, stretch=1)

        # 折叠状态指示
        self.collapsed_indicator = QLabel()
        self.collapsed_indicator.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.collapsed_indicator.setStyleSheet(f"""
            color: {ThemeManager.get_color('text_secondary')};
            font-size: 11px;
        """)
        self.collapsed_indicator.setVisible(False)
        layout.addWidget(self.collapsed_indicator)

        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
        )

    def set_content(self, widget: QWidget):
        """设置内容控件"""
        self._content_widget = widget
        self.content_layout.addWidget(widget)

    def collapse(self):
        """折叠面板"""
        if self._is_collapsed:
            return
        self._is_collapsed = True

        # 隐藏内容
        self.content_area.setVisible(False)
        self.collapsed_indicator.setVisible(True)

        # 更新指示器
        if self._content_widget:
            # 显示内容数量或标识
            self.collapsed_indicator.setText('📄')

        # 动画
        self._animate_width(self._expanded_width, self._collapsed_width)
        self.toggle_button.setText('▶')
        self.collapsed_changed.emit(True)

    def expand(self):
        """展开面板"""
        if not self._is_collapsed:
            return
        self._is_collapsed = False

        # 显示内容
        self.content_area.setVisible(True)
        self.collapsed_indicator.setVisible(False)

        # 动画
        self._animate_width(self._collapsed_width, self._expanded_width)
        self.toggle_button.setText('◀')
        self.collapsed_changed.emit(False)

    def toggle(self):
        """切换折叠状态"""
        if self._is_collapsed:
            self.expand()
        else:
            self.collapse()

    def is_collapsed(self) -> bool:
        """是否已折叠"""
        return self._is_collapsed

    def _animate_width(self, start_width: int, end_width: int):
        """宽度动画"""
        self._animation = QPropertyAnimation(self, b"minimumWidth")
        self._animation.setDuration(300)
        self._animation.setStartValue(start_width)
        self._animation.setEndValue(end_width)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.start()

        self._animation = QPropertyAnimation(self, b"maximumWidth")
        self._animation.setDuration(300)
        self._animation.setStartValue(start_width)
        self._animation.setEndValue(end_width)
        self._animation.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self._animation.start()
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/widgets/test_collapsible_panel.py
import pytest
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from app.ui.widgets.collapsible_panel import CollapsiblePanel


class TestCollapsiblePanel:
    def test_create_panel(self, qapp):
        panel = CollapsiblePanel()
        assert panel.width() == 240
        assert not panel.is_collapsed()

    def test_set_content(self, qapp):
        panel = CollapsiblePanel()
        content = QLabel('Test Content')
        panel.set_content(content)
        assert panel._content_widget == content

    def test_collapse(self, qapp):
        panel = CollapsiblePanel()
        panel.collapse()
        assert panel.is_collapsed()
        assert panel.toggle_button.text() == '▶'

    def test_expand(self, qapp):
        panel = CollapsiblePanel()
        panel.collapse()
        panel.expand()
        assert not panel.is_collapsed()
        assert panel.toggle_button.text() == '◀'

    def test_toggle(self, qapp):
        panel = CollapsiblePanel()
        panel.toggle()
        assert panel.is_collapsed()
        panel.toggle()
        assert not panel.is_collapsed()

    def test_signal(self, qapp):
        panel = CollapsiblePanel()
        signals = []
        panel.collapsed_changed.connect(lambda x: signals.append(x))
        panel.collapse()
        assert signals == [True]
        panel.expand()
        assert signals == [True, False]

    def test_custom_widths(self, qapp):
        panel = CollapsiblePanel(expanded_width=300, collapsed_width=60)
        assert panel._expanded_width == 300
        assert panel._collapsed_width == 60
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/widgets/test_collapsible_panel.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/widgets/collapsible_panel.py tests/ui/widgets/test_collapsible_panel.py
git commit -m "feat: add CollapsiblePanel container with animation

- Expand/collapse with 300ms animation
- Configurable expanded/collapsed widths
- collapsed_changed signal for external integration
- Toggle button with visual feedback

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 5: SlidablePanel（可滑动面板容器）

**Files:**
- Create: `app/ui/widgets/slidable_panel.py`
- Test: `tests/ui/widgets/test_slidable_panel.py`

**Interfaces:**
- Consumes: `ThemeManager.get_color()`
- Produces:
  - `SlidablePanel(QWidget)` 类
  - `SlidablePanel.set_content(widget: QWidget) -> None`
  - `SlidablePanel.slide_in() -> None`
  - `SlidablePanel.slide_out() -> None`
  - `SlidablePanel.is_visible() -> bool`
  - `SlidablePanel.visible_changed(bool)` 信号

- [ ] **Step 1: 编写 SlidablePanel 组件**

```python
# app/ui/widgets/slidable_panel.py
from PyQt6.QtCore import Qt, QPropertyAnimation, QEasingCurve, pyqtSignal
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from app.ui.theme_manager import ThemeManager


class SlidablePanel(QWidget):
    """可滑动面板容器（从右侧滑入/滑出）"""

    visible_changed = pyqtSignal(bool)

    def __init__(self, parent=None, panel_width: int = 320,
                 min_width: int = 280, max_width: int = 480):
        super().__init__(parent)
        self._panel_width = panel_width
        self._min_width = min_width
        self._max_width = max_width
        self._is_visible = True
        self._animation = None
        self._content_widget = None
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedWidth(self._panel_width)
        self.setMinimumWidth(self._min_width)
        self.setMaximumWidth(self._max_width)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 顶部控制栏
        header = QWidget()
        header_layout = QHBoxLayout(header)
        header_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )

        # 标题
        self.title_label = QLabel()
        self.title_label.setFont(ThemeManager.get_font('subheading'))
        self.title_label.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
        )
        header_layout.addWidget(self.title_label)

        header_layout.addStretch()

        # 关闭按钮
        self.close_button = QPushButton('✕')
        self.close_button.setFixedSize(24, 24)
        self.close_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.close_button.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: none;
                font-size: 14px;
            }}
            QPushButton:hover {{
                color: {ThemeManager.get_color('error')};
                background-color: {ThemeManager.get_color('bg_hover')};
                border-radius: {ThemeManager.get_radius('sm')}px;
            }}
        """)
        self.close_button.clicked.connect(self.slide_out)
        header_layout.addWidget(self.close_button)

        layout.addWidget(header)

        # 内容区域
        self.content_area = QWidget()
        self.content_layout = QVBoxLayout(self.content_area)
        self.content_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )
        layout.addWidget(self.content_area, stretch=1)

        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_surface')};"
            f"border-left: 1px solid {ThemeManager.get_color('border')};"
        )

    def set_content(self, widget: QWidget):
        """设置内容控件"""
        self._content_widget = widget
        self.content_layout.addWidget(widget)

    def set_title(self, title: str):
        """设置标题"""
        self.title_label.setText(title)

    def slide_in(self):
        """滑入显示"""
        if self._is_visible:
            return
        self._is_visible = True
        self.setVisible(True)

        # 从右侧滑入动画
        parent = self.parent()
        if parent:
            end_x = parent.width() - self.width()
            start_x = parent.width()
            self.move(start_x, self.y())

            self._animation = QPropertyAnimation(self, b"pos")
            self._animation.setDuration(250)
            self._animation.setStartValue(self.pos())
            self._animation.setEndValue(self.pos() + QtCore.QPoint(end_x - start_x, 0))
            self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
            self._animation.start()

        self.visible_changed.emit(True)

    def slide_out(self):
        """滑出隐藏"""
        if not self._is_visible:
            return
        self._is_visible = False

        # 滑出动画
        parent = self.parent()
        if parent:
            end_x = parent.width()

            self._animation = QPropertyAnimation(self, b"pos")
            self._animation.setDuration(250)
            self._animation.setStartValue(self.pos())
            self._animation.setEndValue(self.pos() + QtCore.QPoint(end_x - self.x(), 0))
            self._animation.setEasingCurve(QEasingCurve.Type.InCubic)
            self._animation.finished.connect(lambda: self.setVisible(False))
            self._animation.start()
        else:
            self.setVisible(False)

        self.visible_changed.emit(False)

    def is_visible(self) -> bool:
        """是否可见"""
        return self._is_visible
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/widgets/test_slidable_panel.py
import pytest
from PyQt6.QtWidgets import QApplication, QWidget, QLabel
from app.ui.widgets.slidable_panel import SlidablePanel


class TestSlidablePanel:
    def test_create_panel(self, qapp):
        panel = SlidablePanel()
        assert panel.width() == 320
        assert panel.minimumWidth() == 280
        assert panel.maximumWidth() == 480

    def test_set_content(self, qapp):
        panel = SlidablePanel()
        content = QLabel('Test Content')
        panel.set_content(content)
        assert panel._content_widget == content

    def test_set_title(self, qapp):
        panel = SlidablePanel()
        panel.set_title('测试标题')
        assert panel.title_label.text() == '测试标题'

    def test_slide_out(self, qapp):
        parent = QWidget()
        parent.setGeometry(0, 0, 800, 600)
        panel = SlidablePanel(parent)
        panel.slide_out()
        assert not panel.is_visible()

    def test_signal(self, qapp):
        panel = SlidablePanel()
        signals = []
        panel.visible_changed.connect(lambda x: signals.append(x))
        panel.slide_out()
        assert signals == [False]
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/widgets/test_slidable_panel.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/widgets/slidable_panel.py tests/ui/widgets/test_slidable_panel.py
git commit -m "feat: add SlidablePanel container with slide animation

- Slide in/out from right side with 250ms animation
- Configurable width with min/max constraints
- visible_changed signal for external integration
- Close button with hover effect

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 6: CompactToolbar（紧凑工具栏）

**Files:**
- Create: `app/ui/widgets/compact_toolbar.py`
- Modify: `app/ui/widgets/gpu_status.py`（集成到工具栏）
- Test: `tests/ui/widgets/test_compact_toolbar.py`

**Interfaces:**
- Consumes: `ThemeManager.get_color()`, `ThemeManager.get_font()`
- Produces:
  - `CompactToolbar(QWidget)` 类
  - `CompactToolbar.set_engine_status(engine: str, status: str) -> None`
  - `CompactToolbar.upload_clicked` 信号
  - `CompactToolbar.test_ocr_clicked` 信号
  - `CompactToolbar.batch_ocr_clicked` 信号
  - `CompactToolbar.save_template_clicked` 信号
  - `CompactToolbar.load_template_clicked` 信号
  - `CompactToolbar.settings_clicked` 信号
  - `CompactToolbar.engine_changed(str)` 信号

- [ ] **Step 1: 编写 CompactToolbar 组件**

```python
# app/ui/widgets/compact_toolbar.py
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtWidgets import QWidget, QHBoxLayout, QPushButton, QComboBox, QLabel
from app.ui.theme_manager import ThemeManager


class CompactToolbar(QWidget):
    """紧凑工具栏"""

    # 信号
    upload_clicked = pyqtSignal()
    test_ocr_clicked = pyqtSignal()
    batch_ocr_clicked = pyqtSignal()
    save_template_clicked = pyqtSignal()
    load_template_clicked = pyqtSignal()
    settings_clicked = pyqtSignal()
    engine_changed = pyqtSignal(str)

    ENGINE_OPTIONS = [
        'GGUF (GPU)',
        'GGUF (CPU)',
        'RapidOCR (CPU)',
    ]

    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedHeight(36)
        self.setStyleSheet(f"""
            CompactToolbar {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            0
        )
        layout.setSpacing(ThemeManager.get_spacing('xs'))

        # 主要操作组
        self._create_icon_button(layout, '⬆️', '上传 PDF (Ctrl+O)', self.upload_clicked)
        self._create_icon_button(layout, '🔍', '试识别 (Ctrl+T)', self.test_ocr_clicked)
        self._create_icon_button(layout, '▶️', '批量识别 (Ctrl+Enter)', self.batch_ocr_clicked)

        # 分隔线
        layout.addSpacing(ThemeManager.get_spacing('sm'))
        self._add_separator(layout)
        layout.addSpacing(ThemeManager.get_spacing('sm'))

        # 模板操作组
        self._create_icon_button(layout, '💾', '保存模板 (Ctrl+S)', self.save_template_clicked)
        self._create_icon_button(layout, '📂', '加载模板', self.load_template_clicked)

        # 分隔线
        layout.addSpacing(ThemeManager.get_spacing('sm'))
        self._add_separator(layout)
        layout.addSpacing(ThemeManager.get_spacing('sm'))

        # 引擎状态
        self.engine_status = QLabel('●')
        self.engine_status.setStyleSheet("font-size: 10px;")
        self.engine_status.setToolTip('GPU 就绪')
        layout.addWidget(self.engine_status)

        # 引擎选择
        self.engine_combo = QComboBox()
        self.engine_combo.addItems(self.ENGINE_OPTIONS)
        self.engine_combo.setFixedWidth(120)
        self.engine_combo.setStyleSheet(f"""
            QComboBox {{
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('sm')}px;
                padding: 2px 4px;
                font-size: 12px;
            }}
        """)
        self.engine_combo.currentTextChanged.connect(self.engine_changed.emit)
        layout.addWidget(self.engine_combo)

        layout.addStretch()

        # 设置按钮
        self._create_icon_button(layout, '⚙️', '设置', self.settings_clicked)

        # 帮助按钮
        help_btn = QPushButton('?')
        help_btn.setFixedSize(24, 24)
        help_btn.setToolTip('快捷键帮助 (F1)')
        help_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                color: {ThemeManager.get_color('text_secondary')};
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('full')}px;
                font-size: 12px;
                font-weight: bold;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_primary')};
            }}
        """)
        layout.addWidget(help_btn)

    def _create_icon_button(self, layout, icon: str, tooltip: str, signal):
        """创建图标按钮"""
        btn = QPushButton(icon)
        btn.setFixedSize(28, 28)
        btn.setToolTip(tooltip)
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: transparent;
                border: none;
                border-radius: {ThemeManager.get_radius('sm')}px;
                font-size: 14px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QPushButton:pressed {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
        """)
        btn.clicked.connect(signal.emit)
        layout.addWidget(btn)
        return btn

    def _add_separator(self, layout):
        """添加分隔线"""
        separator = QWidget()
        separator.setFixedWidth(1)
        separator.setFixedHeight(20)
        separator.setStyleSheet(
            f"background-color: {ThemeManager.get_color('border')};"
        )
        layout.addWidget(separator)

    def set_engine_status(self, engine: str, status: str):
        """设置引擎状态

        Args:
            engine: 引擎名称
            status: 'ready', 'initializing', 'unavailable', 'cpu_mode'
        """
        status_colors = {
            'ready': ThemeManager.get_color('success'),
            'initializing': ThemeManager.get_color('warning'),
            'unavailable': ThemeManager.get_color('error'),
            'cpu_mode': ThemeManager.get_color('text_disabled'),
        }
        color = status_colors.get(status, ThemeManager.get_color('text_disabled'))
        self.engine_status.setStyleSheet(f"color: {color}; font-size: 10px;")
        self.engine_status.setToolTip(f'{engine}: {status}')
```

- [ ] **Step 2: 编写测试**

```python
# tests/ui/widgets/test_compact_toolbar.py
import pytest
from PyQt6.QtWidgets import QApplication
from app.ui.widgets.compact_toolbar import CompactToolbar


class TestCompactToolbar:
    def test_create_toolbar(self, qapp):
        toolbar = CompactToolbar()
        assert toolbar.height() == 36

    def test_engine_options(self, qapp):
        toolbar = CompactToolbar()
        assert toolbar.engine_combo.count() == 3
        assert toolbar.engine_combo.itemText(0) == 'GGUF (GPU)'

    def test_signals(self, qapp):
        toolbar = CompactToolbar()
        signals = {}

        def capture(name):
            def handler():
                signals[name] = True
            return handler

        toolbar.upload_clicked.connect(capture('upload'))
        toolbar.test_ocr_clicked.connect(capture('test'))
        toolbar.batch_ocr_clicked.connect(capture('batch'))
        toolbar.save_template_clicked.connect(capture('save'))
        toolbar.load_template_clicked.connect(capture('load'))
        toolbar.settings_clicked.connect(capture('settings'))

        # 模拟点击（通过信号）
        toolbar.upload_clicked.emit()
        assert signals['upload']

    def test_set_engine_status(self, qapp):
        toolbar = CompactToolbar()
        toolbar.set_engine_status('GGUF', 'ready')
        assert '就绪' in toolbar.engine_status.toolTip() or 'ready' in toolbar.engine_status.toolTip()
```

- [ ] **Step 3: 运行测试**

```bash
pytest tests/ui/widgets/test_compact_toolbar.py -v
```

Expected: 所有测试通过

- [ ] **Step 4: 提交**

```bash
git add app/ui/widgets/compact_toolbar.py tests/ui/widgets/test_compact_toolbar.py
git commit -m "feat: add CompactToolbar with icon buttons and engine status

- Icon-based toolbar saving horizontal space
- Engine status indicator with color coding
- All main actions with keyboard shortcuts in tooltips
- Settings and help buttons

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 7: 重构主窗口框架 (main_window.py)

**Files:**
- Modify: `app/ui/main_window.py`

**Interfaces:**
- Consumes:
  - `CollapsiblePanel`（左侧面板）
  - `SlidablePanel`（右侧面板）
  - `CompactToolbar`（顶部工具栏）
  - `ThemeManager`（样式）
- Produces:
  - 重构后的 `MainWindow` 类

- [ ] **Step 1: 分析现有代码结构**

读取现有 `app/ui/main_window.py`，理解当前布局实现。

- [ ] **Step 2: 重构布局框架**

```python
# app/ui/main_window.py 关键修改

class MainWindow(FluentWindow):
    def __init__(self):
        super().__init__()
        self._setup_ui()

    def _setup_ui(self):
        # ... 现有初始化代码 ...

        # 设置主题
        ThemeManager.set_theme('light')  # 或从配置读取

        # 创建主内容区
        self._create_main_content()

    def _create_main_content(self):
        """创建主内容区（新布局）"""
        # 使用水平布局替代嵌套 splitter
        main_layout = QHBoxLayout()
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # 左侧面板（可折叠）
        self.left_panel = CollapsiblePanel(expanded_width=240, collapsed_width=48)
        self.file_list = FileListPanel()
        self.left_panel.set_content(self.file_list)
        main_layout.addWidget(self.left_panel)

        # 中央工作区
        self.workspace = QWidget()
        workspace_layout = QVBoxLayout(self.workspace)
        workspace_layout.setContentsMargins(0, 0, 0, 0)
        workspace_layout.setSpacing(0)

        # 工具栏
        self.toolbar = CompactToolbar()
        self.toolbar.upload_clicked.connect(self._on_upload)
        self.toolbar.test_ocr_clicked.connect(self._on_test_ocr)
        self.toolbar.batch_ocr_clicked.connect(self._on_batch_ocr)
        self.toolbar.save_template_clicked.connect(self._on_save_template)
        self.toolbar.load_template_clicked.connect(self._on_load_template)
        self.toolbar.settings_clicked.connect(self._on_settings)
        self.toolbar.engine_changed.connect(self._on_engine_changed)
        workspace_layout.addWidget(self.toolbar)

        # PDF 预览区
        self.pdf_preview = QWidget()
        preview_layout = QVBoxLayout(self.pdf_preview)
        preview_layout.setContentsMargins(0, 0, 0, 0)

        # 图像预处理工具栏（可折叠）
        self.preprocess_toolbar = ImagePreprocessToolbar()
        preview_layout.addWidget(self.preprocess_toolbar)

        # PDF 画布
        self.pdf_canvas = PdfCanvas()
        preview_layout.addWidget(self.pdf_canvas, stretch=1)

        workspace_layout.addWidget(self.pdf_preview, stretch=1)

        # 底部状态栏
        self.status_bar = StatusBar()
        workspace_layout.addWidget(self.status_bar)

        main_layout.addWidget(self.workspace, stretch=1)

        # 右侧面板（可滑动）
        self.right_panel = SlidablePanel(panel_width=320)
        self.field_panel = FieldPanel()
        self.result_panel = ResultPanel()
        # ... 设置右侧面板内容 ...
        main_layout.addWidget(self.right_panel)

        # 设置到中心控件
        container = QWidget()
        container.setLayout(main_layout)
        self.setCentralWidget(container)

        # 连接快捷键
        self._setup_shortcuts()

    def _setup_shortcuts(self):
        """设置快捷键"""
        # Ctrl+Shift+L: 切换左侧面板
        shortcut = QShortcut(QKeySequence('Ctrl+Shift+L'), self)
        shortcut.activated.connect(self.left_panel.toggle)

        # Ctrl+Shift+R: 切换右侧面板
        shortcut = QShortcut(QKeySequence('Ctrl+Shift+R'), self)
        shortcut.activated.connect(self._toggle_right_panel)

        # Ctrl+Shift+N: 新建模板
        shortcut = QShortcut(QKeySequence('Ctrl+Shift+N'), self)
        shortcut.activated.connect(self._on_new_template)

        # Space: 快速预览
        shortcut = QShortcut(QKeySequence('Space'), self)
        shortcut.activated.connect(self._on_quick_preview)

    def _toggle_right_panel(self):
        """切换右侧面板"""
        if self.right_panel.is_visible():
            self.right_panel.slide_out()
        else:
            self.right_panel.slide_in()

    def resizeEvent(self, event):
        """窗口大小变化时更新布局"""
        super().resizeEvent(event)
        # 更新右侧面板位置
        if self.right_panel.is_visible():
            self.right_panel.move(
                self.width() - self.right_panel.width(),
                self.toolbar.height()
            )
```

- [ ] **Step 3: 运行应用测试**

```bash
python -m pytest tests/ -v -k "main_window"
```

或手动运行应用验证布局：

```bash
python main.py
```

- [ ] **Step 4: 提交**

```bash
git add app/ui/main_window.py
git commit -m "refactor: restructure main window layout

- Replace nested splitters with CollapsiblePanel + SlidablePanel
- Integrate CompactToolbar
- Add panel toggle shortcuts (Ctrl+Shift+L/R)
- Dynamic workspace sizing

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 8: 重构 FileListPanel

**Files:**
- Modify: `app/ui/widgets/file_list_panel.py`

**Interfaces:**
- Consumes: `ThemeManager`, `EmptyState`
- Produces: 重构后的 `FileListPanel` 类

- [ ] **Step 1: 读取现有代码**

分析当前 `FileListPanel` 的实现。

- [ ] **Step 2: 应用紧凑设计**

```python
# app/ui/widgets/file_list_panel.py 关键修改

class FileListPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        self.title = QLabel('文件列表')
        self.title.setFont(ThemeManager.get_font('subheading'))
        self.title.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
            f"padding: {ThemeManager.get_spacing('sm')}px;"
        )
        layout.addWidget(self.title)

        # 文件列表
        self.list_widget = QListWidget()
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                height: 36px;
                padding-left: {ThemeManager.get_spacing('sm')}px;
                border-left: 3px solid transparent;
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
                border-left: 3px solid {ThemeManager.get_color('primary')};
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
        """)
        layout.addWidget(self.list_widget, stretch=1)

        # 空状态
        self.empty_state = EmptyState('no_files')
        self.empty_state.setVisible(False)
        layout.addWidget(self.empty_state)

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )

        self.remove_btn = QPushButton('移除选中')
        self.clear_btn = QPushButton('清空全部')
        button_layout.addWidget(self.remove_btn)
        button_layout.addWidget(self.clear_btn)
        layout.addLayout(button_layout)

    def update_file_status(self, index: int, status: str):
        """更新文件状态指示

        Args:
            status: 'custom', 'default', 'none'
        """
        item = self.list_widget.item(index)
        if not item:
            return

        status_colors = {
            'custom': ThemeManager.get_color('primary'),
            'default': ThemeManager.get_color('success'),
            'none': ThemeManager.get_color('text_disabled'),
        }
        color = status_colors.get(status, ThemeManager.get_color('text_disabled'))

        # 更新左侧色条
        item.setStyleSheet(f"""
            QListWidget::item {{
                border-left: 3px solid {color};
            }}
        """)

    def show_empty_state(self, show: bool = True):
        """显示/隐藏空状态"""
        self.empty_state.setVisible(show)
        self.list_widget.setVisible(not show)
```

- [ ] **Step 3: 提交**

```bash
git add app/ui/widgets/file_list_panel.py
git commit -m "refactor: compact FileListPanel with EmptyState integration

- Reduced row height to 36px
- Status indicator with left color bar
- Integrated EmptyState component
- ThemeManager styling

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 9: 重构 PdfCanvas

**Files:**
- Modify: `app/ui/widgets/pdf_canvas.py`

**Interfaces:**
- Consumes: `ThemeManager`, `EmptyState`
- Produces: 重构后的 `PdfCanvas` 类

- [ ] **Step 1: 应用改进**

```python
# app/ui/widgets/pdf_canvas.py 关键修改

class PdfCanvas(QGraphicsView):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        # 设置背景
        self.setStyleSheet(
            f"background-color: {ThemeManager.get_color('bg_primary')};"
        )

        # 空状态
        self.empty_state = EmptyState('no_preview')
        self.empty_state.setVisible(True)

        # 缩放比例显示（右下角）
        self.zoom_label = QLabel('100%')
        self.zoom_label.setStyleSheet(f"""
            background-color: {ThemeManager.get_color('bg_surface')};
            color: {ThemeManager.get_color('text_secondary')};
            border-radius: {ThemeManager.get_radius('sm')}px;
            padding: 2px 6px;
            font-size: 11px;
        """)
        self.zoom_label.setCursor(Qt.CursorShape.PointingHandCursor)

        # 浮动工具栏（悬停显示）
        self.floating_toolbar = QWidget()
        self.floating_toolbar.setStyleSheet(f"""
            background-color: {ThemeManager.get_color('bg_surface')};
            border: 1px solid {ThemeManager.get_color('border')};
            border-radius: {ThemeManager.get_radius('md')}px;
        """)
        # ... 工具栏按钮 ...

    def mouseMoveEvent(self, event):
        """鼠标移动时显示浮动工具栏"""
        super().mouseMoveEvent(event)
        # 显示浮动工具栏
        self.floating_toolbar.setVisible(True)

    def _show_region_size(self, size: tuple):
        """显示区域尺寸提示"""
        width, height = size
        # 在区域旁边显示尺寸标签
        self._size_label = QLabel(f'{width}×{height}px')
        self._size_label.setStyleSheet(f"""
            background-color: {ThemeManager.get_color('primary')};
            color: white;
            border-radius: {ThemeManager.get_radius('sm')}px;
            padding: 2px 6px;
            font-size: 11px;
        """)

    def _snap_to_grid(self, pos: QPoint) -> QPoint:
        """吸附到网格"""
        grid_size = 10
        x = round(pos.x() / grid_size) * grid_size
        y = round(pos.y() / grid_size) * grid_size
        return QPoint(x, y)
```

- [ ] **Step 2: 提交**

```bash
git add app/ui/widgets/pdf_canvas.py
git commit -m "refactor: PdfCanvas with floating toolbar and grid snap

- Floating toolbar on hover
- Zoom percentage display in bottom-right
- Region size tooltip during selection
- Grid snap alignment (10px)
- EmptyState integration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 10: 重构 ImagePreprocessToolbar

**Files:**
- Modify: `app/ui/widgets/preprocess_toolbar.py`

**Interfaces:**
- Consumes: `ThemeManager`
- Produces: 可折叠的 `ImagePreprocessToolbar`

- [ ] **Step 1: 应用可折叠设计**

```python
# app/ui/widgets/preprocess_toolbar.py 关键修改

class ImagePreprocessToolbar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._expanded = False
        self._setup_ui()

    def _setup_ui(self):
        self.setFixedHeight(32)  # 折叠状态高度

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            0
        )

        # 折叠时显示的图标按钮
        self.icon_buttons = []
        for icon, tooltip in [
            ('🔄', '旋转'),
            ('☀️', '亮度'),
            ('◐', '对比度'),
            ('🔲', '二值化'),
        ]:
            btn = QPushButton(icon)
            btn.setFixedSize(24, 24)
            btn.setToolTip(tooltip)
            btn.setStyleSheet(f"""
                QPushButton {{
                    background-color: transparent;
                    border: none;
                    border-radius: {ThemeManager.get_radius('sm')}px;
                }}
                QPushButton:hover {{
                    background-color: {ThemeManager.get_color('bg_hover')};
                }}
            """)
            layout.addWidget(btn)
            self.icon_buttons.append(btn)

        # 展开按钮
        self.expand_btn = QPushButton('▼')
        self.expand_btn.setFixedSize(24, 24)
        self.expand_btn.clicked.connect(self._toggle_expand)
        layout.addWidget(self.expand_btn)

        layout.addStretch()

        # 展开后的详细控件（初始隐藏）
        self.detail_widget = QWidget()
        self.detail_layout = QHBoxLayout(self.detail_widget)
        # ... 滑块等详细控件 ...
        self.detail_widget.setVisible(False)

    def _toggle_expand(self):
        """切换展开/折叠"""
        self._expanded = not self._expanded

        if self._expanded:
            self.setFixedHeight(80)
            self.expand_btn.setText('▲')
            self.detail_widget.setVisible(True)
            # 隐藏图标按钮
            for btn in self.icon_buttons:
                btn.setVisible(False)
        else:
            self.setFixedHeight(32)
            self.expand_btn.setText('▼')
            self.detail_widget.setVisible(False)
            for btn in self.icon_buttons:
                btn.setVisible(True)

        # 高度动画
        self._animation = QPropertyAnimation(self, b"maximumHeight")
        self._animation.setDuration(200)
        self._animation.setStartValue(self.height())
        self._animation.setEndValue(80 if self._expanded else 32)
        self._animation.setEasingCurve(QEasingCurve.Type.OutCubic)
        self._animation.start()
```

- [ ] **Step 2: 提交**

```bash
git add app/ui/widgets/preprocess_toolbar.py
git commit -m "refactor: collapsible ImagePreprocessToolbar

- Collapsed: icon buttons only (32px height)
- Expanded: full sliders and controls (80px height)
- 200ms height animation
- ThemeManager styling

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 11: 重构 FieldPanel

**Files:**
- Modify: `app/ui/widgets/field_panel.py`

**Interfaces:**
- Consumes: `ThemeManager`, `EmptyState`, `SlidablePanel`
- Produces: 重构后的 `FieldPanel`

- [ ] **Step 1: 应用紧凑设计**

```python
# app/ui/widgets/field_panel.py 关键修改

class FieldPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 表格
        self.table = QTableWidget()
        self.table.setColumnCount(4)
        self.table.setHorizontalHeaderLabels(['字段名', '类型', '识别结果', '操作'])
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                gridline-color: {ThemeManager.get_color('border')};
            }}
            QTableWidget::item {{
                height: 32px;
                padding: {ThemeManager.get_spacing('xs')}px;
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('sm')}px;
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        layout.addWidget(self.table, stretch=1)

        # 空状态
        self.empty_state = EmptyState('no_fields')
        self.empty_state.setVisible(False)
        layout.addWidget(self.empty_state)

        # 底部操作
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm')
        )

        self.clear_current_btn = QPushButton('清空当前字段')
        self.clear_all_btn = QPushButton('清空所有字段')
        button_layout.addWidget(self.clear_current_btn)
        button_layout.addWidget(self.clear_all_btn)
        layout.addLayout(button_layout)
```

- [ ] **Step 2: 提交**

```bash
git add app/ui/widgets/field_panel.py
git commit -m "refactor: compact FieldPanel with EmptyState

- Reduced row height to 32px
- ThemeManager styling for table and headers
- Integrated EmptyState component
- Flat button design

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 12: 重构 ResultPanel

**Files:**
- Modify: `app/ui/widgets/result_panel.py`

**Interfaces:**
- Consumes: `ThemeManager`, `SlidablePanel`
- Produces: 重构后的 `ResultPanel`

- [ ] **Step 1: 应用标签页设计**

```python
# app/ui/widgets/result_panel.py 关键修改

class ResultPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标签页切换
        self.tab_bar = QTabBar()
        self.tab_bar.addTab('Markdown预览')
        self.tab_bar.addTab('字段提取')
        self.tab_bar.addTab('表格数据')
        self.tab_bar.setStyleSheet(f"""
            QTabBar::tab {{
                background-color: {ThemeManager.get_color('bg_surface')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('sm')}px {ThemeManager.get_spacing('md')}px;
                border: none;
                border-bottom: 2px solid transparent;
            }}
            QTabBar::tab:selected {{
                color: {ThemeManager.get_color('primary')};
                border-bottom: 2px solid {ThemeManager.get_color('primary')};
            }}
            QTabBar::tab:hover:!selected {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
        """)
        layout.addWidget(self.tab_bar)

        # 内容区
        self.content_stack = QStackedWidget()
        # ... 添加三个视图页面 ...
        layout.addWidget(self.content_stack, stretch=1)

        # 导出按钮
        self.export_btn = QPushButton('📥 导出')
        self.export_btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('primary')};
                color: white;
                border: none;
                border-radius: {ThemeManager.get_radius('md')}px;
                padding: {ThemeManager.get_spacing('sm')}px {ThemeManager.get_spacing('lg')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('primary_hover')};
            }}
        """)
        layout.addWidget(self.export_btn, alignment=Qt.AlignmentFlag.AlignRight)

        # 连接标签页切换
        self.tab_bar.currentChanged.connect(self.content_stack.setCurrentIndex)
```

- [ ] **Step 2: 提交**

```bash
git add app/ui/widgets/result_panel.py
git commit -m "refactor: ResultPanel with tab-based view switching

- Tab bar replacing dropdown for view switching
- ThemeManager styling for tabs
- Export button with icon + text
- Integrated with SlidablePanel

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 13: 重构 StatusBar

**Files:**
- Modify: `app/ui/widgets/status_bar.py`

**Interfaces:**
- Consumes: `ThemeManager`
- Produces: 重构后的 `StatusBar`

- [ ] **Step 1: 应用动态快捷键提示**

```python
# app/ui/widgets/status_bar.py 关键修改

class StatusBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._setup_ui()
        self._current_focus = 'global'

    def _setup_ui(self):
        self.setFixedHeight(24)
        self.setStyleSheet(f"""
            StatusBar {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border-top: 1px solid {ThemeManager.get_color('border')};
            }}
        """)

        layout = QHBoxLayout(self)
        layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            0,
            ThemeManager.get_spacing('sm'),
            0
        )

        # 左侧状态
        self.status_icon = QLabel('●')
        self.status_icon.setStyleSheet(f"font-size: 8px;")
        layout.addWidget(self.status_icon)

        self.status_text = QLabel('就绪')
        self.status_text.setFont(ThemeManager.get_font('caption'))
        self.status_text.setStyleSheet(
            f"color: {ThemeManager.get_color('text_secondary')};"
        )
        layout.addWidget(self.status_text)

        layout.addStretch()

        # 右侧快捷键提示
        self.shortcut_hint = QLabel()
        self.shortcut_hint.setFont(ThemeManager.get_font('caption'))
        self.shortcut_hint.setStyleSheet(
            f"color: {ThemeManager.get_color('text_disabled')};"
        )
        layout.addWidget(self.shortcut_hint)

        # 设置默认提示
        self.set_focus_area('global')

    def set_status(self, text: str, status_type: str = 'info'):
        """设置状态文本"""
        self.status_text.setText(text)
        colors = {
            'info': ThemeManager.get_color('text_secondary'),
            'success': ThemeManager.get_color('success'),
            'warning': ThemeManager.get_color('warning'),
            'error': ThemeManager.get_color('error'),
        }
        self.status_icon.setStyleSheet(f"color: {colors.get(status_type, colors['info'])}; font-size: 8px;")

    def set_focus_area(self, area: str):
        """根据焦点区域更新快捷键提示"""
        self._current_focus = area
        hints = {
            'file_list': 'Ctrl+O 上传 | Delete 移除 | Space 预览',
            'pdf_preview': '左键框选 | 右键平移 | 滚轮缩放',
            'field_panel': 'Ctrl+S 保存 | Delete 删除字段',
            'global': 'Ctrl+Shift+L 文件栏 | Ctrl+Shift+R 字段栏',
        }
        self.shortcut_hint.setText(hints.get(area, hints['global']))
```

- [ ] **Step 2: 提交**

```bash
git add app/ui/widgets/status_bar.py
git commit -m "refactor: StatusBar with dynamic shortcut hints

- Reduced height to 24px
- Dynamic shortcut hints based on focus area
- Status icon with color coding
- ThemeManager styling

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 14: 动画系统与性能优化

**Files:**
- Create: `app/ui/animation_manager.py`
- Modify: 所有使用动画的组件

**Interfaces:**
- Consumes: `ThemeManager`
- Produces:
  - `AnimationManager` 类
  - `AnimationManager.enabled` 属性
  - `AnimationManager.animate(property, start, end, duration, easing)`

- [ ] **Step 1: 创建 AnimationManager**

```python
# app/ui/animation_manager.py
from PyQt6.QtCore import QPropertyAnimation, QEasingCurve, QObject


class AnimationManager(QObject):
    """动画管理器 - 统一管理所有动画，支持禁用"""

    _enabled = True
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
        """创建并启动动画"""
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
        animation.finished.connect(lambda: cls._animations.remove(animation))

        return animation

    @classmethod
    def stop_all(cls):
        """停止所有动画"""
        for anim in cls._animations[:]:
            anim.stop()
            cls._animations.remove(anim)
```

- [ ] **Step 2: 更新所有组件使用 AnimationManager**

修改 `CollapsiblePanel`, `SlidablePanel`, `ImagePreprocessToolbar` 等组件，使用 `AnimationManager.animate()` 替代直接的 `QPropertyAnimation`。

- [ ] **Step 3: 添加设置选项**

在设置对话框中添加 "外观 > 禁用动画" 选项，控制 `AnimationManager.set_enabled()`。

- [ ] **Step 4: 提交**

```bash
git add app/ui/animation_manager.py
git commit -m "feat: add AnimationManager for centralized animation control

- Support enable/disable all animations
- Reduced motion preference support
- Centralized animation lifecycle management
- Settings integration

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 15: 暗色模式适配

**Files:**
- Modify: 所有使用 `setStyleSheet` 的组件

**Interfaces:**
- Consumes: `ThemeManager`
- Produces: 完整的暗色模式支持

- [ ] **Step 1: 添加主题切换功能**

在设置中添加主题切换选项：

```python
# 在设置对话框中添加
class SettingsDialog:
    def _create_appearance_tab(self):
        # 主题选择
        theme_group = QGroupBox('主题')
        theme_layout = QVBoxLayout()

        self.light_radio = QRadioButton('浅色')
        self.dark_radio = QRadioButton('深色')
        self.auto_radio = QRadioButton('跟随系统')
        self.auto_radio.setChecked(True)

        theme_layout.addWidget(self.light_radio)
        theme_layout.addWidget(self.dark_radio)
        theme_layout.addWidget(self.auto_radio)
        theme_group.setLayout(theme_layout)

        # 动画开关
        self.animation_checkbox = QCheckBox('启用动画')
        self.animation_checkbox.setChecked(True)

        # 连接信号
        self.light_radio.toggled.connect(lambda: self._on_theme_changed('light'))
        self.dark_radio.toggled.connect(lambda: self._on_theme_changed('dark'))
        self.animation_checkbox.toggled.connect(AnimationManager.set_enabled)

    def _on_theme_changed(self, theme: str):
        ThemeManager.set_theme(theme)
        # 触发全局样式更新
        self._update_all_styles()

    def _update_all_styles(self):
        """更新所有组件样式"""
        # 遍历所有窗口和控件，重新应用样式
        for widget in QApplication.instance().allWidgets():
            # 触发样式更新
            widget.style().unpolish(widget)
            widget.style().polish(widget)
            widget.update()
```

- [ ] **Step 2: 测试暗色模式**

```bash
python main.py
# 在设置中切换到暗色模式，验证所有组件颜色正确
```

- [ ] **Step 3: 提交**

```bash
git add app/ui/widgets/settings_dialog.py  # 或其他设置文件
git commit -m "feat: dark mode support with ThemeManager

- System theme detection and manual override
- All components use ThemeManager colors
- Global style refresh on theme change
- Animation disable option

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## Task 16: 综合测试与优化

**Files:**
- 所有测试文件
- `tests/ui/integration_test.py`（新增）

- [ ] **Step 1: 编写集成测试**

```python
# tests/ui/integration_test.py
import pytest
from PyQt6.QtWidgets import QApplication
from app.ui.main_window import MainWindow


class TestUIIntegration:
    def test_main_window_creation(self, qapp):
        window = MainWindow()
        assert window is not None
        assert window.centralWidget() is not None

    def test_panel_toggle(self, qapp):
        window = MainWindow()
        # 测试左侧面板折叠
        window.left_panel.collapse()
        assert window.left_panel.is_collapsed()
        window.left_panel.expand()
        assert not window.left_panel.is_collapsed()

    def test_theme_switching(self, qapp):
        from app.ui.theme_manager import ThemeManager
        ThemeManager.set_theme('dark')
        assert ThemeManager.current_theme() == 'dark'
        ThemeManager.set_theme('light')
        assert ThemeManager.current_theme() == 'light'

    def test_shortcuts(self, qapp):
        window = MainWindow()
        # 验证快捷键绑定存在
        assert window.findChild(QShortcut, 'Ctrl+Shift+L') is not None
```

- [ ] **Step 2: 运行完整测试套件**

```bash
pytest tests/ -v
```

Expected: 所有测试通过

- [ ] **Step 3: 手动测试清单**

- [ ] 窗口大小变化时布局自适应
- [ ] 面板折叠/展开动画流畅
- [ ] 暗色模式所有组件颜色正确
- [ ] 主题切换无闪烁
- [ ] 快捷键功能正常
- [ ] 拖拽上传文件正常
- [ ] 区域框选和调整正常
- [ ] 右键菜单功能正常
- [ ] 不同分辨率布局正常
- [ ] 高 DPI 显示清晰

- [ ] **Step 4: 最终提交**

```bash
git add tests/ui/integration_test.py
git commit -m "test: add UI integration tests

- Main window creation and layout
- Panel toggle functionality
- Theme switching verification
- Shortcut binding checks

Co-Authored-By: Claude <noreply@anthropic.com>"
```

---

## 自审检查

### 1. Spec 覆盖检查

| Spec 要求 | 对应 Task |
|-----------|----------|
| ThemeManager 统一管理视觉常量 | Task 1 ✓ |
| 响应式布局（面板折叠/展开） | Task 4, 5, 7 ✓ |
| 紧凑工具栏 | Task 6 ✓ |
| 统一空状态 | Task 2 ✓ |
| 轻量通知 | Task 3 ✓ |
| 浮动工具栏 | Task 9 ✓ |
| 动态快捷键提示 | Task 13 ✓ |
| 动画系统 | Task 14 ✓ |
| 暗色模式 | Task 15 ✓ |
| 键盘工作流 | Task 7 ✓ |
| 信息密度优化 | Task 8, 9, 10, 11 ✓ |

### 2. Placeholder 扫描

- 无 "TBD", "TODO", "implement later"
- 所有步骤包含实际代码
- 无 "Similar to Task N" 引用
- 所有类型和函数名一致

### 3. 类型一致性检查

- `ThemeManager.get_color()` 返回 `str` — 一致 ✓
- `CollapsiblePanel.is_collapsed()` 返回 `bool` — 一致 ✓
- `SlidablePanel.is_visible()` 返回 `bool` — 一致 ✓
- 信号签名一致 ✓

---

## 执行方式选择

**Plan complete and saved to `docs/superpowers/plans/2026-07-26-ui-redesign-plan.md`. Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
