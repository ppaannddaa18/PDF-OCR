# app/ui/widgets/file_list_panel.py
"""Task 8 重构版 FileListPanel：紧凑设计 + 状态色条 + EmptyState 集成

设计要点：
- 36px 行高，左侧 3px 状态色条（QListWidgetItem 无 setStyleSheet API，
  故用自定义 delegate 绘制色条，颜色在 paint 时从 ThemeManager 解析，
  支持运行时主题切换）
- 空状态复用统一 EmptyState 组件（'no_files' 变体）
- 全部颜色/字体/间距来自 ThemeManager，禁止硬编码
"""
from pathlib import Path

from PyQt6.QtCore import pyqtSignal as Signal, Qt, QRect, QTimer
from PyQt6.QtGui import QColor, QDragEnterEvent, QDropEvent
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QListWidget, QListWidgetItem, QStyledItemDelegate, QStyleOptionViewItem,
)
from PyQt6.QtGui import QPainter

from app.ui.theme_manager import ThemeManager
from app.ui.widgets.empty_state import EmptyState

# 列表项数据角色
PATH_ROLE = 256  # item.data(PATH_ROLE) -> 文件路径（沿用历史数值，兼容 Qt.UserRole）
STATUS_ROLE = Qt.ItemDataRole.UserRole + 1  # item.data(STATUS_ROLE) -> 'custom'/'default'/'empty'


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
    """在列表项左侧绘制 3px 状态色条（paint 时实时读取 ThemeManager 颜色）"""

    BAR_WIDTH = 3

    def paint(self, painter: QPainter, option: QStyleOptionViewItem, index) -> None:
        super().paint(painter, option, index)
        bar_color = status_color(index.data(STATUS_ROLE))
        painter.save()
        painter.fillRect(
            QRect(
                option.rect.left(), option.rect.top(),
                self.BAR_WIDTH, option.rect.height(),
            ),
            QColor(bar_color),
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
        self._pending_timers = []  # 待处理的定时器，用于组件销毁时清理
        self.files = []

        self._setup_ui()
        self._update_empty_state()

    # ---------- UI ----------

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

        # 文件列表（紧凑设计：36px 行高，悬停/选中背景）
        self.list_widget = QListWidget()
        self.list_widget.setItemDelegate(_StatusBarDelegate(self.list_widget))
        self.list_widget.setUniformItemSizes(True)
        self.list_widget.setStyleSheet(f"""
            QListWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
            }}
            QListWidget::item {{
                height: 36px;
                padding-left: {ThemeManager.get_spacing('sm')}px;
                color: {ThemeManager.get_color('text_primary')};
            }}
            QListWidget::item:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QListWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
        """)
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, stretch=1)

        # 空状态（'no_files' 变体；操作按钮触发 upload_requested）
        self.empty_state = EmptyState('no_files')
        self.empty_state.set_action(
            '上传 PDF', lambda: self.upload_requested.emit())
        layout.addWidget(self.empty_state, stretch=1)

        # 批量加载进度提示
        self.progress_label = QLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet(
            f"font-size: 12px; color: {ThemeManager.get_color('primary')};"
            f"padding: {ThemeManager.get_spacing('xs')}px;"
        )
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
        layout.addLayout(button_layout)

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
        """将文件路径加入列表并返回列表项（保持 PATH_ROLE / 状态数据一致）"""
        item = QListWidgetItem(Path(path).name)
        item.setData(PATH_ROLE, path)
        item.setData(STATUS_ROLE, self._pdf_configs.get(path))
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

        def process_batch(batch_paths, start_count):
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
            timer = QTimer()
            timer.setSingleShot(True)

            def make_callback(b=batch, s=processed_count + i, t=timer):
                def cb():
                    process_batch(b, s)
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
        # 更新列表项显示
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(PATH_ROLE) == pdf_path:
                name = Path(pdf_path).name
                item.setData(STATUS_ROLE, status)
                item.setToolTip(status_tooltip(name, status))
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
            if path in self._pdf_configs:
                del self._pdf_configs[path]
            self.list_widget.takeItem(self.list_widget.row(item))
            self._update_empty_state()
            # 发送文件移除信号
            self.file_removed.emit(path)

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
        self.progress_label.setText(f"⏳ 正在加载 {current}/{total} 个文件...")
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
        """拖拽放下事件 - 处理 PDF 文件"""
        files = []
        for url in event.mimeData().urls():
            path = url.toLocalFile()
            if path.lower().endswith('.pdf'):
                files.append(path)
        if files:
            self.add_files(files)  # add_files 内部已触发 file_selected 信号
        event.acceptProposedAction()
