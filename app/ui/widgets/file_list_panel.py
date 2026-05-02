from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PyQt6.QtCore import pyqtSignal as Signal, Qt, QTimer
from qfluentwidgets import SubtitleLabel, ListWidget, PushButton, BodyLabel
from pathlib import Path
from PyQt6.QtGui import QDragEnterEvent, QDropEvent


class FileListPanel(QWidget):
    file_selected = Signal(str)
    files_cleared = Signal()  # 文件列表清空信号
    file_removed = Signal(str)  # 单个文件移除信号
    batch_add_progress = Signal(int, int)  # 批量添加进度信号 (当前, 总数)

    # 分批处理配置
    BATCH_SIZE = 10  # 每批处理的文件数量
    BATCH_DELAY = 30  # 批次之间的延迟(毫秒)

    def __init__(self):
        super().__init__()
        # 启用拖拽
        self.setAcceptDrops(True)
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # Fluent 列表
        self.list_widget = ListWidget()
        self.list_widget.itemClicked.connect(self._on_item_clicked)
        layout.addWidget(self.list_widget, 1)

        # 批量加载进度提示
        self.progress_label = BodyLabel("")
        self.progress_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_label.setStyleSheet("font-size: 12px; color: #0078d4; padding: 4px;")
        self.progress_label.setVisible(False)
        layout.addWidget(self.progress_label)

        # 增强的空状态提示
        self.empty_widget = QWidget()
        empty_layout = QVBoxLayout(self.empty_widget)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.setSpacing(12)

        # 图标
        from PyQt6.QtGui import QFont
        icon_label = QLabel("📄")
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon_label.setStyleSheet("font-size: 48px;")
        empty_layout.addWidget(icon_label)

        # 主标题
        title_label = BodyLabel("暂无PDF文件")
        title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title_label.setStyleSheet("font-size: 14px; color: #333; font-weight: bold;")
        empty_layout.addWidget(title_label)

        # 操作提示
        action_label = BodyLabel("点击上方「上传」按钮\n或拖拽PDF文件到此处")
        action_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        action_label.setStyleSheet("font-size: 12px; color: #666;")
        empty_layout.addWidget(action_label)

        # 格式提示
        format_label = BodyLabel("支持的格式: .pdf\n建议: 单次最多上传50个文件")
        format_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        format_label.setStyleSheet("font-size: 11px; color: #999;")
        empty_layout.addWidget(format_label)

        layout.addWidget(self.empty_widget)
        self.empty_widget.setVisible(True)

        # 操作按钮
        self.btn_remove = PushButton("移除选中")
        self.btn_remove.clicked.connect(self.remove_selected)
        layout.addWidget(self.btn_remove)

        self.btn_clear = PushButton("清空全部")
        self.btn_clear.clicked.connect(self.clear_files)
        layout.addWidget(self.btn_clear)

        self.files = []
        self._pdf_configs = {}  # pdf_path -> 配置状态 ("default", "custom", "empty")
        self._pending_timers = []  # 待处理的定时器，用于组件销毁时清理
        self._update_empty_state()

    def _update_empty_state(self):
        has_files = len(self.files) > 0
        self.empty_widget.setVisible(not has_files)
        self.list_widget.setVisible(has_files)
        self.btn_remove.setEnabled(has_files)
        self.btn_clear.setEnabled(has_files)

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

    def _add_files_immediately(self, paths: list):
        """立即添加文件（少量文件）"""
        first_file = None
        for p in paths:
            if p not in self.files:
                self.files.append(p)
                item_text = Path(p).name
                self.list_widget.addItem(item_text)
                self.list_widget.item(self.list_widget.count()-1).setData(256, p)
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
        self.list_widget.addItem(Path(first_path).name)
        self.list_widget.item(self.list_widget.count()-1).setData(256, first_path)
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
                    self.list_widget.addItem(Path(p).name)
                    self.list_widget.item(self.list_widget.count()-1).setData(256, p)
                    processed_count += 1

            self._update_progress(processed_count, total_count)

            # 全部完成
            if processed_count >= total_count:
                self.progress_label.setVisible(False)
                self.batch_add_progress.emit(total_count, total_count)

        # 分批调度
        for i in range(0, len(remaining), self.BATCH_SIZE):
            batch = remaining[i:i+self.BATCH_SIZE]
            timer = QTimer()
            timer.setSingleShot(True)
            timer.timeout.connect(lambda b=batch, s=processed_count + i: process_batch(b, s))
            timer.start(self.BATCH_DELAY * (i // self.BATCH_SIZE + 1))
            self._pending_timers.append(timer)

    def set_pdf_config_status(self, pdf_path: str, status: str):
        """[修复] 设置PDF的配置状态 - 使用图标而不是文本前缀"""
        from PyQt6.QtGui import QColor
        from PyQt6.QtCore import Qt

        self._pdf_configs[pdf_path] = status
        # 更新列表项显示
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.data(256) == pdf_path:
                name = Path(pdf_path).name
                item.setText(name)  # [修复] 保持原始文件名

                # [修复] 使用背景色和前景色表示状态，而不是文本前缀
                if status == "custom":
                    item.setBackground(QColor("#E5F3FF"))  # 浅蓝色
                    item.setToolTip(f"{name}\n使用自定义字段配置")
                elif status == "default":
                    item.setBackground(QColor("#E5F9E5"))  # 浅绿色
                    item.setToolTip(f"{name}\n使用默认模板")
                elif status == "empty":
                    item.setBackground(QColor("#F5F5F5"))  # 浅灰色
                    item.setToolTip(f"{name}\n无字段配置")
                break

    def remove_selected(self):
        item = self.list_widget.currentItem()
        if item:
            path = item.data(256)
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
            path = item.data(256)
            if path:
                self.file_selected.emit(path)

    def current_file(self) -> str:
        """返回当前选中的文件路径，无选中则返回第一个文件"""
        item = self.list_widget.currentItem()
        if item:
            return item.data(256)
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
        self._pending_timers.clear()
        self.progress_label.setVisible(False)
        self.files_cleared.emit()  # 发送清空信号

    def _update_progress(self, current: int, total: int):
        """更新批量添加进度"""
        self.progress_label.setText(f"⏳ 正在加载 {current}/{total} 个文件...")
        self.batch_add_progress.emit(current, total)

    def closeEvent(self, event):
        """组件关闭时清理定时器"""
        for timer in self._pending_timers:
            timer.stop()
        self._pending_timers.clear()
        super().closeEvent(event)

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
            self.add_files(files)
            # 发送信号加载第一个文件
            self.file_selected.emit(files[0])
        event.acceptProposedAction()
