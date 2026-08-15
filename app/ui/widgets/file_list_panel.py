# app/ui/widgets/file_list_panel.py
"""Task 8 重构版 FileListPanel：紧凑设计 + 状态色条 + EmptyState 集成

设计要点：
- 44px 行高，左侧 3px 状态色条（QListWidgetItem 无 setStyleSheet API，
  故用自定义 delegate 绘制色条，颜色在 paint 时从 ThemeManager 解析，
  支持运行时主题切换）
- Task 3 / P2-c：delegate 额外右对齐绘制页数「N 页」与解析徽标
  （⟳ 解析中 / ✓ 成功 / ⚠ 失败），数据来自 PAGE_ROLE / PARSE_ROLE
- 空状态复用统一 EmptyState 组件（'no_files' 变体）
- 全部颜色/字体/间距来自 ThemeManager，禁止硬编码
"""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal as Signal, Qt, QRect, QTimer
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent, QFont
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyleOptionViewItem,
)
from PyQt6.QtGui import QPainter

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.empty_state import EmptyState

# qtawesome 延迟加载（避免启动开销与字体警告）
_qta = None


def _get_qta():
    """获取 qtawesome 实例（延迟加载）"""
    global _qta
    if _qta is None:
        import qtawesome
        _qta = qtawesome
    return _qta


# 列表项数据角色
PATH_ROLE = 256  # item.data(PATH_ROLE) -> 文件路径（沿用历史数值，兼容 Qt.UserRole）
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1  # item.data(STATUS_ROLE) -> 'custom'/'default'/'empty'
PAGE_ROLE = Qt.ItemDataRole.UserRole + 2    # item.data(PAGE_ROLE) -> int 页数 / None
PARSE_ROLE = Qt.ItemDataRole.UserRole + 3   # item.data(PARSE_ROLE) -> 'parsing'/'success'/'failed'/None


def status_color(status: str) -> str:
    """状态 -> 左侧色条颜色（ThemeManager 角色色）

    Args:
        status: 'custom', 'default', 'empty', 'none' 或 None
    """
    mapping = {
        'custom': ThemeManager.get_color('primary'),
        'default': ThemeManager.get_color('success'),
        'empty': ThemeManager.get_color('text_disabled'),
        'none': ThemeManager.get_color('text_disabled'),
        None: ThemeManager.get_color('text_disabled'),
    }
    return mapping.get(status, ThemeManager.get_color('text_disabled'))


def status_tooltip(filename: str, status: str) -> str:
    """状态 -> 列表项 tooltip 文本"""
    hints = {
        'custom': '使用自定义字段配置',
        'default': '使用默认模板',
        'empty': '无字段配置',
        'none': '无字段配置',
    }
    hint = hints.get(status, '无字段配置')
    return f"{filename}\n{hint}"


class _StatusBarDelegate(QStyledItemDelegate):
    """列表项绘制：左侧 3px 配置状态色条 + 右侧页数/解析徽标

    - 左侧色条仍为配置状态（custom/default/empty），来自 STATUS_ROLE
    - 右侧右对齐绘制「N 页」（text_disabled 小字号）与解析徽标
      （⟳ 解析中 warning / ✓ 成功 success / ⚠ 失败 error），
      均从 item 数据角色读取（自包含，不依赖面板 dict），
      颜色/字体在 paint 时实时解析 ThemeManager，天然主题安全
    """

    BAR_WIDTH = 3
    RIGHT_OFFSET = 8  # 距右缘间距（px）

    # 解析状态 → 徽标字符 / 主题色角色
    # （parsing 是文本徽标 → warning_text 压暗版；圆点用途仍用 warning）
    _BADGE = {'parsing': '⟳', 'success': '✓', 'failed': '⚠'}
    _BADGE_COLOR = {'parsing': 'warning_text', 'success': 'success', 'failed': 'error'}

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        painter.save()

        # 左侧 3px 配置状态色条（沿用 STATUS_ROLE）
        bar_color = status_color(index.data(STATUS_ROLE))
        painter.fillRect(
            QRect(
                option.rect.left(), option.rect.top(),
                self.BAR_WIDTH, option.rect.height(),
            ),
            QColor(bar_color),
        )

        # 右侧区域：页数 + 解析徽标（小一号字体，右对齐）
        # 必须基于副本：option.font 是 Qt 内部复用对象的 QFont 引用，
        # 直接修改会累积污染（每次 paint -1pt，列表行字号逐行变小）
        font = QFont(option.font)
        if font.pointSizeF() > 0:
            font.setPointSize(max(1, font.pointSize() - 1))
        else:
            font.setPixelSize(max(1, font.pixelSize() - 1))
        painter.setFont(font)

        page_count = index.data(PAGE_ROLE)
        parse_status = index.data(PARSE_ROLE)

        # 页数文本「N 页」右对齐（text_disabled）
        if page_count is not None:
            text = f"{page_count} 页"
            text_rect = QRect(
                option.rect.right() - self.RIGHT_OFFSET
                - painter.fontMetrics().horizontalAdvance(text),
                option.rect.top(),
                painter.fontMetrics().horizontalAdvance(text),
                option.rect.height(),
            )
            painter.setPen(QColor(ThemeManager.get_color('text_disabled')))
            painter.drawText(
                text_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                text,
            )

        # 解析徽标（在页数左侧）
        if parse_status in self._BADGE:
            badge = self._BADGE[parse_status]
            badge_width = painter.fontMetrics().horizontalAdvance(badge) + 6
            badge_rect = QRect(
                text_rect.left() - badge_width if page_count is not None
                else option.rect.right() - self.RIGHT_OFFSET - badge_width,
                option.rect.top(),
                badge_width,
                option.rect.height(),
            )
            painter.setPen(QColor(
                ThemeManager.get_color(self._BADGE_COLOR[parse_status])))
            painter.drawText(
                badge_rect,
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
                badge,
            )

        painter.restore()


class FileListPanel(QWidget):
    """PDF 文件列表面板：紧凑布局 + 状态指示 + 空状态"""

    file_selected = Signal(str)          # 文件选择变化（点击或首个文件自动加载）
    files_cleared = Signal()             # 文件列表清空信号
    file_removed = Signal(str)           # 单个文件移除信号
    batch_add_progress = Signal(int, int)  # 批量添加进度信号 (当前, 总数)
    upload_requested = Signal()          # EmptyState 操作按钮 -> 请求打开文件对话框

    # 分批处理配置
    BATCH_SIZE = 10  # 每批处理的文件数量
    BATCH_DELAY = 30  # 批次之间的延迟(毫秒)

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        # 启用拖拽
        self.setAcceptDrops(True)
        self._pdf_configs = {}  # pdf_path -> 配置状态 ("custom"/"default"/"empty")
        self._page_counts = {}  # pdf_path -> int 页数
        self._parse_status = {}  # pdf_path -> 'parsing'/'success'/'failed'
        self._pending_timers = []  # 待处理的定时器，用于组件销毁时清理
        self.files = []

        self._setup_ui()
        self._update_empty_state()
        # Task 15：主题切换后由 ThemeManager 触发重建 QSS
        ThemeManager.register_refresh_callback(self.apply_theme)

    # ---------- UI ----------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 标题
        self.title = QLabel('文件列表')
        self.title.setFont(ThemeManager.get_font('subheading'))
        layout.addWidget(self.title)

        # 文件列表（紧凑设计：44px 行高，悬停/选中背景；
        # 状态色条/页数/解析徽标由 _StatusBarDelegate paint 时实时解析
        # ThemeManager，天然主题安全）
        self.list_widget = QListWidget()
        self.list_widget.setItemDelegate(_StatusBarDelegate(self.list_widget))
        # 显式使用全站正文字号，避免回退到 Qt 默认 9pt（旧版 ListWidget 自带 14px）
        self.list_widget.setFont(ThemeManager.get_font('body'))
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        self.list_widget.currentItemChanged.connect(
            lambda _cur, _prev: self._update_move_buttons())
        layout.addWidget(self.list_widget, stretch=1)

        # 空状态（'no_files' 变体；操作按钮触发 upload_requested）
        self.empty_state = EmptyState('no_files')
        self.empty_state.set_action(
            '上传 PDF', lambda: self.upload_requested.emit())
        layout.addWidget(self.empty_state, stretch=1)

        # 批量加载进度提示
        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # 底部按钮
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
        )
        # 上移 / 下移（icon-only，主题色图标）
        self._icon_buttons = []
        self.btn_move_up = QPushButton()
        self.btn_move_up.setFixedSize(24, 24)
        self.btn_move_up.setToolTip('上移 (Ctrl+↑)')
        self.btn_move_up.clicked.connect(lambda: self.move_selected(-1))
        button_layout.addWidget(self.btn_move_up)
        self._icon_buttons.append((self.btn_move_up, 'fa5s.arrow-up'))

        self.btn_move_down = QPushButton()
        self.btn_move_down.setFixedSize(24, 24)
        self.btn_move_down.setToolTip('下移 (Ctrl+↓)')
        self.btn_move_down.clicked.connect(lambda: self.move_selected(1))
        button_layout.addWidget(self.btn_move_down)
        self._icon_buttons.append((self.btn_move_down, 'fa5s.arrow-down'))

        self.btn_remove = QPushButton('移除选中')
        self.btn_remove.setToolTip('移除选中的PDF文件')
        self.btn_remove.clicked.connect(self.remove_selected)
        button_layout.addWidget(self.btn_remove)

        self.btn_clear = QPushButton('清空全部')
        self.btn_clear.setToolTip('清空所有已加载的PDF文件')
        self.btn_clear.clicked.connect(self.clear_files)
        button_layout.addWidget(self.btn_clear)

        self._apply_button_style(self.btn_remove)
        self._apply_button_style(self.btn_clear)
        self._apply_button_style(self.btn_move_up)
        self._apply_button_style(self.btn_move_down)
        layout.addLayout(button_layout)
        self._update_move_buttons()

        # 构造时烘焙样式（可安全重复执行）
        self.apply_theme()

    def apply_theme(self):
        """重建全部内嵌 QSS（Task 15：ThemeManager.set_theme 后调用；
        状态色条 delegate 在 paint 时解析颜色，天然主题安全无需处理）"""
        self.title.setStyleSheet(
            f"color: {ThemeManager.get_color('text_primary')};"
            f"padding: {ThemeManager.get_spacing('sm')}px;"
        )
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
            }}
            QListWidget:focus {{
                border: 1px solid {ThemeManager.get_color('border_focus')};
            }}
            QListWidget::item {{
                height: 44px;
                padding-left: {ThemeManager.get_spacing('sm')}px;
                font-size: 13px;
                color: {ThemeManager.get_color('text_primary')};
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
        """)
        self.progress_label.setStyleSheet(
            f"font-size: 12px; color: {ThemeManager.get_color('primary')};"
            f"padding: {ThemeManager.get_spacing('xs')}px;"
        )
        self._apply_button_style(self.btn_remove)
        self._apply_button_style(self.btn_clear)
        self._apply_button_style(self.btn_move_up)
        self._apply_button_style(self.btn_move_down)
        for btn, icon_name in self._icon_buttons:
            btn.setIcon(_get_qta().icon(
                icon_name, color=ThemeManager.get_color('text_secondary')))

    def _apply_button_style(self, button: QPushButton):
        """应用 ThemeManager 按钮样式（无硬编码颜色）"""
        button.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('bg_surface')};
                color: {ThemeManager.get_color('text_primary')};
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('sm')}px;
                padding: {ThemeManager.get_spacing('xs')}px
                         {ThemeManager.get_spacing('md')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QPushButton:disabled {{
                color: {ThemeManager.get_color('text_disabled')};
            }}
        """)

    # ---------- 空状态 ----------

    def _update_empty_state(self):
        has_files = len(self.files) > 0
        self.empty_state.setVisible(not has_files)
        self.list_widget.setVisible(has_files)
        self.btn_remove.setEnabled(has_files)
        self.btn_clear.setEnabled(has_files)
        self._update_move_buttons()

    def _update_move_buttons(self):
        """按选中行位置启用/禁用上移下移（首行禁上移，末行禁下移）"""
        row = self.list_widget.currentRow()
        count = self.list_widget.count()
        self.btn_move_up.setEnabled(count > 0 and row > 0)
        self.btn_move_down.setEnabled(count > 0 and 0 <= row < count - 1)

    def show_empty_state(self, show: bool = True):
        """显示/隐藏空状态"""
        self.empty_state.setVisible(show)
        self.list_widget.setVisible(not show)

    # ---------- 文件管理 ----------

    def add_files(self, paths: list):
        """
        添加文件 - 优化版：分批处理大量文件，避免UI阻塞
        """
        # 过滤已存在的文件
        new_paths = [p for p in paths if p not in self.files]
        if not new_paths:
            return

        total_count = len(new_paths)

        # 少量文件直接处理
        if total_count <= self.BATCH_SIZE:
            self._add_files_immediately(new_paths)
            return

        # 大量文件分批处理
        self._add_files_batch(new_paths)

    def _add_item(self, path: str) -> QListWidgetItem:
        """将文件路径加入列表并返回列表项（保持全部数据角色 / tooltip 一致）"""
        item = QListWidgetItem(Path(path).name)
        item.setData(PATH_ROLE, path)
        item.setData(STATUS_ROLE, self._pdf_configs.get(path))
        item.setData(PAGE_ROLE, self._page_counts.get(path))
        item.setData(PARSE_ROLE, self._parse_status.get(path))
        item.setToolTip(self._build_tooltip(path))
        self.list_widget.addItem(item)
        return item

    def _add_files_immediately(self, paths: list):
        """立即添加文件（少量文件）"""
        first_file = None
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                self._add_item(p)
                if first_file is None:
                    first_file = p
        self._update_empty_state()
        # 发送信号加载第一个文件
        if first_file:
            self.file_selected.emit(first_file)

    def _add_files_batch(self, paths: list):
        """分批添加文件（大量文件）"""
        total_count = len(paths)
        self.progress_label.setVisible(True)
        self._update_progress(0, total_count)

        # 首个文件优先处理
        first_path = paths[0]
        self.files.append(first_path)
        self._add_item(first_path)
        self._update_empty_state()
        self.file_selected.emit(first_path)
        self._update_progress(1, total_count)

        # 剩余文件分批处理
        remaining = paths[1:]
        processed_count = 1

        def process_batch(batch_paths):
            nonlocal processed_count
            for p in batch_paths:
                if p not in self.files:
                    self.files.append(p)
                    self._add_item(p)
                    processed_count += 1

            self._update_progress(processed_count, total_count)

            # 全部完成
            if processed_count >= total_count:
                self.progress_label.setVisible(False)
                self.batch_add_progress.emit(total_count, total_count)

        # 分批调度
        for i in range(0, len(remaining), self.BATCH_SIZE):
            batch = remaining[i:i + self.BATCH_SIZE]
            timer = QTimer(self)
            timer.setSingleShot(True)

            def make_callback(b=batch, t=timer):
                def cb():
                    process_batch(b)
                    if t in self._pending_timers:
                        self._pending_timers.remove(t)
                return cb

            timer.timeout.connect(make_callback())
            timer.start(self.BATCH_DELAY * (i // self.BATCH_SIZE + 1))
            self._pending_timers.append(timer)

    def set_pdf_config_status(self, pdf_path: str, status: str):
        """设置PDF的配置状态 - 左侧色条 + tooltip

        Args:
            pdf_path: 文件路径
            status: 'custom', 'default', 'empty'（'none' 兼容为 'empty'）
        """
        self._pdf_configs[pdf_path] = status
        self._refresh_item(pdf_path)

    def set_page_count(self, pdf_path: str, n: int):
        """设置文件页数（列表项右侧显示「N 页」）

        Args:
            pdf_path: 文件路径
            n: 页数（None 时清除）
        """
        if n is None:
            self._page_counts.pop(pdf_path, None)
        else:
            self._page_counts[pdf_path] = int(n)
        self._refresh_item(pdf_path)

    def set_parse_status(self, pdf_path: str, status):
        """设置解析状态（列表项右侧显示解析徽标）

        Args:
            pdf_path: 文件路径
            status: 'parsing' / 'success' / 'failed' / None（None 清除）
        """
        if status is None:
            self._parse_status.pop(pdf_path, None)
        else:
            self._parse_status[pdf_path] = status
        self._refresh_item(pdf_path)

    def _build_tooltip(self, pdf_path: str) -> str:
        """组合 tooltip：配置状态 + 页数 + 解析状态"""
        name = Path(pdf_path).name
        parts = [status_tooltip(name, self._pdf_configs.get(pdf_path))]
        n = self._page_counts.get(pdf_path)
        if n is not None:
            parts.append(f"共 {n} 页")
        parse_hints = {
            'parsing': '解析中…',
            'success': '解析成功',
            'failed': '解析失败',
        }
        status = self._parse_status.get(pdf_path)
        if status in parse_hints:
            parts.append(parse_hints[status])
        return "\n".join(parts)

    def _refresh_item(self, pdf_path: str):
        """刷新指定路径列表项的全部数据角色与 tooltip（局部刷新 viewport）"""
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(PATH_ROLE) == pdf_path:
                item.setData(STATUS_ROLE, self._pdf_configs.get(pdf_path))
                item.setData(PAGE_ROLE, self._page_counts.get(pdf_path))
                item.setData(PARSE_ROLE, self._parse_status.get(pdf_path))
                item.setToolTip(self._build_tooltip(pdf_path))
                # Qt6 中 QWidget.update() 不接受 rect，需通过 viewport 局部刷新
                self.list_widget.viewport().update(
                    self.list_widget.visualItemRect(item))
                break

    def update_file_status(self, index: int, status: str):
        """按列表索引更新状态指示（与 set_pdf_config_status 等价，索引版）"""
        item = self.list_widget.item(index)
        if not item:
            return
        path = item.data(PATH_ROLE)
        if path:
            self.set_pdf_config_status(path, status)

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item:
            path = item.data(PATH_ROLE)
            if path in self.files:
                self.files.remove(path)
            for d in (self._pdf_configs, self._page_counts, self._parse_status):
                d.pop(path, None)
            self.list_widget.takeItem(self.list_widget.row(item))
            self._update_empty_state()
            # 发送文件移除信号
            self.file_removed.emit(path)

    def move_selected(self, delta: int) -> bool:
        """上移(-1) / 下移(+1) 当前选中文件；越界时 no-op，返回是否发生移动"""
        item = self.list_widget.currentItem()
        if item is None:
            return False
        row = self.list_widget.row(item)
        new_row = row + delta
        if new_row < 0 or new_row >= self.list_widget.count():
            return False
        path = item.data(PATH_ROLE)
        moved = self.list_widget.takeItem(row)
        self.list_widget.insertItem(new_row, moved)
        self.list_widget.setCurrentItem(moved)
        self.files.remove(path)
        self.files.insert(new_row, path)
        self._update_move_buttons()
        return True

    def _on_item_clicked(self, item):
        """处理列表项点击"""
        if item:
            path = item.data(PATH_ROLE)
            if path:
                self.file_selected.emit(path)

    def current_file(self) -> str:
        """返回当前选中的文件路径，无选中则返回第一个文件"""
        item = self.list_widget.currentItem()
        if item:
            return item.data(PATH_ROLE)
        if self.files:
            return self.files[0]
        return None

    def all_files(self):
        return list(self.files)

    def clear_files(self):
        self.files.clear()
        self._pdf_configs.clear()
        self._page_counts.clear()
        self._parse_status.clear()
        self.list_widget.clear()
        self._update_empty_state()
        # 清理待处理的定时器
        for timer in self._pending_timers:
            timer.stop()
            timer.deleteLater()
        self._pending_timers.clear()
        self.progress_label.setVisible(False)
        self.files_cleared.emit()  # 发送清空信号

    def _update_progress(self, current: int, total: int):
        """更新批量添加进度"""
        self.progress_label.setText(f"正在加载 {current}/{total} 个文件...")
        self.batch_add_progress.emit(current, total)

    # ---------- 生命周期 ----------

    def closeEvent(self, event):
        """组件关闭时清理定时器"""
        for timer in self._pending_timers:
            timer.stop()
            timer.deleteLater()
        self._pending_timers.clear()
        super().closeEvent(event)

    # ---------- 拖拽 ----------

    def dragEnterEvent(self, event: QDragEnterEvent):
        """拖拽进入事件 - 只接受 PDF 文件"""
        if event.mimeData().hasUrls():
            urls = event.mimeData().urls()
            for url in urls:
                if url.toLocalFile().lower().endswith('.pdf'):
                    event.acceptProposedAction()
                    return
        event.ignore()

    def dropEvent(self, event: QDropEvent):
        """拖拽放下事件 - 处理 PDF 文件（无 PDF 时忽略，与 dragEnterEvent 对称）"""
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'):
                files.append(path)
        if files:
            self.add_files(files)  # add_files 内部已触发 file_selected 信号
            event.acceptProposedAction()
        else:
            event.ignore()
