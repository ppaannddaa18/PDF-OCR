# app/ui/widgets/field_panel.py
"""Task 11 重构版 FieldPanel：紧凑表格 + EmptyState 集成 + 扁平按钮

设计要点：
- 32px 行高（verticalHeader defaultSectionSize 确定性生效 + QSS 兜底）、紧凑内边距
- 空状态复用统一 EmptyState 组件（'no_fields' 变体）
- 全部颜色/字体/间距来自 ThemeManager，禁止硬编码（验证失败/低置信度的
  浅色背景用主题 error/warning 色的半透明色派生，天然适配暗色模式）
- 底部清空按钮为扁平样式（与 FileListPanel 一致）；删除按钮为单元格内紧凑按钮
- 全部既有功能与接口保留（字段添加/更新/删除/清空、试识别结果、详情展示、
  模板构建/加载、6 个信号），main_window 直接访问的 regions/table/
  _preview_results 属性保持不变
"""
from PyQt6.QtCore import pyqtSignal as Signal, Qt
from PyQt6.QtGui import QColor, QBrush
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QPushButton,
)
from qfluentwidgets import ComboBox, BodyLabel

from app.models.region import Region
from app.models.template import Template
from app.ui.theme_manager import ThemeManager
from app.ui.widgets.empty_state import EmptyState
from app.utils.validators import validate_with_error, normalize_by_type

# 表格行高（紧凑设计）
ROW_HEIGHT = 32


def _translucent(role: str, alpha: int) -> QColor:
    """主题角色色的半透明版本（用于验证失败/低置信度的浅色背景）"""
    color = QColor(ThemeManager.get_color(role))
    color.setAlpha(alpha)
    return color


class FieldPanel(QWidget):
    """字段配置面板：4 列紧凑表格 + 空状态 + 底部清空操作"""

    region_changed = Signal(list)          # List[Region]
    region_deleted = Signal(str)           # region_id
    current_cleared = Signal()             # 清空当前字段信号
    all_cleared = Signal()                 # 清空所有字段信号
    field_name_changed = Signal(str, str, str)  # (region_id, old_name, new_name) 字段名变更信号
    set_as_default_template = Signal()     # 设为默认模板信号

    def __init__(self, parent: QWidget = None):
        super().__init__(parent)
        self.regions = {}   # id -> Region
        self._preview_results = {}  # region_id -> FieldResult (存储试识别结果)
        self._current_template_name = "未命名模板"
        self._setup_ui()
        self._update_empty_state()

    # ---------- UI ----------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        # 字段表格（紧凑设计：32px 行高）
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "识别结果", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        # 行高：defaultSectionSize 确定性生效（QSS item height 仅作兜底）
        self.table.verticalHeader().setDefaultSectionSize(ROW_HEIGHT)
        self.table.verticalHeader().setVisible(False)  # 紧凑设计：隐藏行号列
        self.table.setStyleSheet(f"""
            QTableWidget {{
                background-color: {ThemeManager.get_color('bg_surface')};
                border: none;
                outline: none;
                gridline-color: {ThemeManager.get_color('border')};
                alternate-background-color: {ThemeManager.get_color('bg_hover')};
            }}
            QTableWidget::item {{
                height: {ROW_HEIGHT}px;
                padding: {ThemeManager.get_spacing('xs')}px;
                color: {ThemeManager.get_color('text_primary')};
            }}
            QTableWidget::item:selected {{
                background-color: {ThemeManager.get_color('bg_selected')};
            }}
            QHeaderView::section {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('text_secondary')};
                padding: {ThemeManager.get_spacing('sm')}px;
                border: none;
                border-bottom: 1px solid {ThemeManager.get_color('border')};
            }}
        """)
        # 字段名列可编辑
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.DoubleClicked
            | QAbstractItemView.EditTrigger.EditKeyPressed
        )
        # 点击识别结果列显示详情
        self.table.cellClicked.connect(self._on_cell_clicked)
        # 监听字段名编辑完成事件
        self.table.itemChanged.connect(self._on_field_name_changed)
        layout.addWidget(self.table, stretch=1)

        # 空状态（'no_fields' 变体；无字段时显示）
        self.empty_state = EmptyState('no_fields')
        layout.addWidget(self.empty_state, stretch=1)

        # 识别结果详情显示区域
        self.detail_widget = QWidget()
        self.detail_widget.setVisible(False)
        detail_layout = QVBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
        )
        detail_layout.setSpacing(ThemeManager.get_spacing('xs'))

        self.detail_title = BodyLabel("识别结果详情")
        self.detail_title.setFont(ThemeManager.get_font('subheading'))
        detail_layout.addWidget(self.detail_title)

        self.detail_content = BodyLabel("")
        self.detail_content.setWordWrap(True)
        self.detail_content.setFont(ThemeManager.get_font('body'))
        self.detail_content.setStyleSheet(
            f"background: {ThemeManager.get_color('bg_hover')};"
            f"color: {ThemeManager.get_color('text_primary')};"
            f"padding: {ThemeManager.get_spacing('sm')}px;"
            f"border-radius: {ThemeManager.get_radius('sm')}px;"
        )
        detail_layout.addWidget(self.detail_content)

        self.detail_confidence = BodyLabel("")
        self.detail_confidence.setFont(ThemeManager.get_font('body'))
        detail_layout.addWidget(self.detail_confidence)

        layout.addWidget(self.detail_widget)

        # 底部操作按钮（水平布局，扁平样式）
        button_layout = QHBoxLayout()
        button_layout.setContentsMargins(
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
            ThemeManager.get_spacing('sm'),
        )

        # 清空当前字段按钮
        self.clear_current_btn = QPushButton("清空当前字段")
        self.clear_current_btn.setToolTip("仅清空当前选中PDF的字段配置，其他PDF不受影响")
        self.clear_current_btn.clicked.connect(self.clear_current)
        button_layout.addWidget(self.clear_current_btn)

        # 清空所有字段按钮
        self.clear_all_btn = QPushButton("清空所有字段")
        self.clear_all_btn.setToolTip("清空所有PDF的字段配置")
        self.clear_all_btn.clicked.connect(self._on_clear_all_clicked)
        button_layout.addWidget(self.clear_all_btn)

        self._apply_button_style(self.clear_current_btn)
        self._apply_button_style(self.clear_all_btn)
        layout.addLayout(button_layout)

    def _apply_button_style(self, button: QPushButton):
        """应用 ThemeManager 扁平按钮样式（无硬编码颜色）"""
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
        has_fields = len(self.regions) > 0
        self.empty_state.setVisible(not has_fields)
        self.table.setVisible(has_fields)

    def set_template_name(self, name: str, is_default: bool = False):
        """设置当前模板名称（供主窗口调用——实际显示由main_window管理）"""
        pass

    # ---------- 字段名编辑 ----------

    def _on_field_name_changed(self, item: QTableWidgetItem):
        """字段名编辑完成事件 - 同步更新识别结果"""
        # 只处理字段名列（第0列）
        if item.column() != 0:
            return

        row = item.row()
        region_id = item.data(Qt.ItemDataRole.UserRole)
        if region_id not in self.regions:
            return

        old_name = self.regions[region_id].field_name
        new_name = item.text()

        if old_name == new_name:
            return

        # 更新 region 中的字段名
        self.regions[region_id].field_name = new_name

        # [修复] 使用 region_id 作为 key，而不是字段名
        # _preview_results 使用 region_id 作为 key（见 show_preview_result 方法）
        # 所以这里不需要更新 _preview_results 的 key
        # 只需要更新识别结果中存储的字段名即可
        if region_id in self._preview_results:
            self._preview_results[region_id].field_name = new_name

        # 发送字段名变更信号（含 region_id 避免同名冲突）
        self.field_name_changed.emit(region_id, old_name, new_name)

    def _on_cell_clicked(self, row: int, column: int):
        """点击单元格事件 - 点击识别结果列显示详情"""
        if column != 2:  # 只处理识别结果列
            self.detail_widget.setVisible(False)
            return

        item = self.table.item(row, 0)
        if item is None:
            return
        rid = item.data(Qt.ItemDataRole.UserRole)
        if rid not in self._preview_results:
            self.detail_widget.setVisible(False)
            return

        region = self.regions.get(rid)
        fr = self._preview_results[rid]
        if fr.text:
            # 验证字段类型
            is_valid, error_msg = validate_with_error(
                fr.text, region.field_type if region else "text")
            normalized = normalize_by_type(
                fr.text, region.field_type if region else "text")

            self.detail_content.setText(f"内容：{fr.text}")

            # 显示标准化后的值（如果有变化）
            if normalized != fr.text:
                self.detail_content.setText(f"内容：{fr.text}\n标准化：{normalized}")

            conf_text = f"置信度：{fr.confidence:.2%}"
            if fr.confidence < 0.7:
                conf_text += " (较低)"
                self.detail_confidence.setStyleSheet(
                    f"color: {ThemeManager.get_color('error')};")
            else:
                self.detail_confidence.setStyleSheet(
                    f"color: {ThemeManager.get_color('success')};")

            # 显示验证结果
            if not is_valid:
                self.detail_confidence.setText(f"{conf_text}\n⚠ 格式错误: {error_msg}")
                self.detail_confidence.setStyleSheet(
                    f"color: {ThemeManager.get_color('error')};")
            else:
                self.detail_confidence.setText(conf_text)

            self.detail_widget.setVisible(True)
        else:
            self.detail_widget.setVisible(False)

    # ---------- 字段管理 ----------

    def add_region(self, region: Region):
        self.regions[region.id] = region

        # [修复] 临时阻塞信号，避免setItem触发itemChanged
        self.table.blockSignals(True)

        row = self.table.rowCount()
        self.table.insertRow(row)

        # 字段名（可编辑）- 带颜色标识
        name_item = QTableWidgetItem(region.field_name)
        name_item.setForeground(QBrush(QColor(region.color)))
        name_item.setData(Qt.ItemDataRole.UserRole, region.id)
        self.table.setItem(row, 0, name_item)

        # Fluent 下拉框
        type_combo = ComboBox()
        type_combo.addItems(["text", "number", "date", "email", "phone"])
        type_combo.setCurrentText(region.field_type)
        # [修复] 连接类型变更信号，同步更新region
        type_combo.currentTextChanged.connect(
            lambda text, rid=region.id: self._on_field_type_changed(rid, text))
        self.table.setCellWidget(row, 1, type_combo)

        # 识别结果（初始为空）
        self.table.setItem(row, 2, QTableWidgetItem(""))

        # [修复] 恢复信号
        self.table.blockSignals(False)

        # 删除按钮（单元格内紧凑扁平按钮）
        btn = QPushButton("删除")
        btn.setStyleSheet(f"""
            QPushButton {{
                background-color: {ThemeManager.get_color('bg_surface')};
                color: {ThemeManager.get_color('text_secondary')};
                border: 1px solid {ThemeManager.get_color('border')};
                border-radius: {ThemeManager.get_radius('sm')}px;
                padding: {ThemeManager.get_spacing('xs')}px
                         {ThemeManager.get_spacing('sm')}px;
            }}
            QPushButton:hover {{
                background-color: {ThemeManager.get_color('bg_hover')};
                color: {ThemeManager.get_color('error')};
            }}
        """)
        btn.clicked.connect(lambda _, rid=region.id: self._delete(rid))
        self.table.setCellWidget(row, 3, btn)

        self._update_empty_state()

    def _on_field_type_changed(self, region_id: str, new_type: str):
        """[修复] 字段类型变更事件 - 同步更新region并持久化"""
        if region_id in self.regions:
            self.regions[region_id].field_type = new_type
            # 发射信号通知主窗口保存配置
            self.region_changed.emit(list(self.regions.values()))

    def _delete(self, region_id):
        if region_id in self.regions:
            del self.regions[region_id]
        if region_id in self._preview_results:
            del self._preview_results[region_id]
        # 找到并删除对应行
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == region_id:
                self.table.removeRow(row)
                break
        self.region_deleted.emit(region_id)
        self._update_empty_state()
        # 隐藏详情区域
        self.detail_widget.setVisible(False)

    def clear_all(self):
        self.regions.clear()
        self._preview_results.clear()
        self.table.setRowCount(0)
        self.region_changed.emit([])
        self._update_empty_state()
        # 隐藏详情区域
        self.detail_widget.setVisible(False)

    def clear_current(self):
        """清空当前字段（仅发送信号，由主窗口处理具体逻辑）"""
        self.current_cleared.emit()
        self._update_empty_state()
        # 隐藏详情区域
        self.detail_widget.setVisible(False)

    def _on_clear_all_clicked(self):
        """清空所有字段按钮点击事件"""
        self.all_cleared.emit()

    # ---------- 模板 ----------

    def build_template(self) -> Template:
        """[修复] 复制 Region 对象，避免直接修改原始对象"""
        from copy import deepcopy
        regions = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid not in self.regions:
                continue
            # [修复] 深拷贝 Region 对象，避免修改原始对象
            r = deepcopy(self.regions[rid])
            r.field_name = item.text()
            combo = self.table.cellWidget(row, 1)
            if combo:
                r.field_type = combo.currentText()
            regions.append(r)
        return Template(name="current", regions=regions)

    def load_template(self, template: Template):
        # 手动清空，避免 clear_all() 触发多次信号
        self.regions.clear()
        self._preview_results.clear()
        self.table.setRowCount(0)
        self.detail_widget.setVisible(False)
        for r in template.regions:
            self.add_region(r)
        self._update_empty_state()
        # 仅在所有区域添加完毕后触发一次信号
        self.region_changed.emit(list(self.regions.values()))

    # ---------- 试识别结果 ----------

    def show_preview_result(self, file_result):
        """显示试识别结果 - 使用 field_name 匹配确保准确性，并进行字段类型验证"""
        self._preview_results.clear()
        # 临时阻塞信号，避免 setItem 触发 itemChanged
        self.table.blockSignals(True)
        try:
            for row in range(self.table.rowCount()):
                item = self.table.item(row, 0)
                if item is None:
                    continue
                rid = item.data(Qt.ItemDataRole.UserRole)
                if rid not in self.regions:
                    continue
                region = self.regions[rid]
                # 使用 region_id 遍历查找结果（B4 兼容：同名区域 key 可能带 _1 后缀）
                fr = next(
                    (f for f in file_result.fields.values() if f.region_id == rid),
                    None)
                if fr is not None:
                    self._preview_results[rid] = fr

                    # 根据字段类型进行验证和标准化
                    is_valid, error_msg = validate_with_error(fr.text, region.field_type)
                    normalized_text = normalize_by_type(fr.text, region.field_type)

                    result_item = QTableWidgetItem(normalized_text)

                    # 设置 Tooltip 显示完整内容和置信度
                    tooltip = f"内容: {fr.text}\n置信度: {fr.confidence:.2%}"

                    # 根据验证结果设置样式（半透明主题色，适配暗色模式）
                    if not is_valid:
                        # 验证失败 - 错误色浅底
                        result_item.setBackground(
                            _translucent('error', 40))
                        result_item.setForeground(
                            QBrush(QColor(ThemeManager.get_color('error'))))
                        tooltip += f"\n⚠ 格式错误: {error_msg}"
                    elif fr.confidence < 0.7:
                        # 置信度低 - 警告色浅底
                        result_item.setBackground(
                            _translucent('warning', 40))
                        tooltip += "\n(置信度较低，建议核对)"

                    result_item.setToolTip(tooltip)
                    self.table.setItem(row, 2, result_item)
        finally:
            self.table.blockSignals(False)
        # 隐藏详情区域
        self.detail_widget.setVisible(False)
