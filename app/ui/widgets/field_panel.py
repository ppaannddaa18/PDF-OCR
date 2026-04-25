from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QTableWidget, QTableWidgetItem,
    QHeaderView, QAbstractItemView, QHBoxLayout
)
from PyQt6.QtCore import pyqtSignal as Signal, Qt
from PyQt6.QtGui import QColor, QBrush
from qfluentwidgets import SubtitleLabel, PushButton, ComboBox, BodyLabel, InfoBar, InfoBarPosition
from app.models.region import Region
from app.models.template import Template
from app.utils.validators import validate_with_error, normalize_by_type


class FieldPanel(QWidget):
    region_changed = Signal(list)          # List[Region]
    region_deleted = Signal(str)           # region_id
    current_cleared = Signal()             # 清空当前字段信号
    all_cleared = Signal()                 # 清空所有字段信号
    field_name_changed = Signal(str, str)  # (old_name, new_name) 字段名变更信号
    set_as_default_template = Signal()     # 设为默认模板信号

    # 字段类型颜色映射
    TYPE_COLORS = {
        "text": "#0078d4",
        "number": "#107c10",
        "date": "#5c2d91",
        "email": "#008272",
        "phone": "#d83b01",
    }

    def __init__(self):
        super().__init__()
        self.regions = {}   # id -> Region
        self._preview_results = {}  # region_id -> FieldResult (存储试识别结果)
        self._current_template_name = "未命名模板"
        self._init_ui()

    def _init_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(8)
        layout.setContentsMargins(0, 0, 0, 0)

        # 模板信息区域
        self.template_info_widget = QWidget()
        template_info_layout = QVBoxLayout(self.template_info_widget)
        template_info_layout.setContentsMargins(8, 8, 8, 8)
        template_info_layout.setSpacing(4)

        # 模板名称标签
        self.template_name_label = BodyLabel("当前模板: 未命名模板")
        self.template_name_label.setStyleSheet("font-weight: bold; color: #0078d4;")
        template_info_layout.addWidget(self.template_name_label)

        # 设为默认模板按钮
        self.btn_set_default = PushButton("设为默认模板")
        self.btn_set_default.setToolTip("将当前字段配置设为默认模板，新加载的PDF将自动应用此配置")
        self.btn_set_default.clicked.connect(self._on_set_as_default)
        template_info_layout.addWidget(self.btn_set_default)

        # 分隔线
        from PyQt6.QtWidgets import QFrame
        line = QFrame()
        line.setFrameShape(QFrame.Shape.HLine)
        line.setStyleSheet("background: #e0e0e0;")
        line.setFixedHeight(1)
        template_info_layout.addWidget(line)

        layout.addWidget(self.template_info_widget)

        # 空状态提示
        self.empty_label = BodyLabel("暂无字段\n在 PDF 画布上拖拽框选区域")
        self.empty_label.setStyleSheet("color: #888; text-align: center;")
        self.empty_label.setAlignment(Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter)
        self.empty_label.setMinimumHeight(100)
        layout.addWidget(self.empty_label)

        # 字段表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["字段名", "类型", "识别结果", "操作"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setAlternatingRowColors(True)
        self.table.setStyleSheet("""
            QTableWidget {
                gridline-color: #e0e0e0;
                alternate-background-color: #f5f5f5;
            }
        """)
        # 字段名列可编辑
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.DoubleClicked | QAbstractItemView.EditTrigger.EditKeyPressed)
        # 点击识别结果列显示详情
        self.table.cellClicked.connect(self._on_cell_clicked)
        # 监听字段名编辑完成事件
        self.table.itemChanged.connect(self._on_field_name_changed)
        layout.addWidget(self.table, 1)

        # 识别结果详情显示区域
        self.detail_widget = QWidget()
        self.detail_widget.setVisible(False)
        detail_layout = QVBoxLayout(self.detail_widget)
        detail_layout.setContentsMargins(8, 8, 8, 8)
        detail_layout.setSpacing(4)

        self.detail_title = BodyLabel("识别结果详情")
        self.detail_title.setStyleSheet("font-weight: bold;")
        detail_layout.addWidget(self.detail_title)

        self.detail_content = BodyLabel("")
        self.detail_content.setWordWrap(True)
        self.detail_content.setStyleSheet("background: #f5f5f5; padding: 8px; border-radius: 4px;")
        detail_layout.addWidget(self.detail_content)

        self.detail_confidence = BodyLabel("")
        detail_layout.addWidget(self.detail_confidence)

        layout.addWidget(self.detail_widget)

        # 操作按钮区域（水平布局）
        btn_layout = QHBoxLayout()

        # 清空当前字段按钮
        btn_clear_current = PushButton("清空当前字段")
        btn_clear_current.setToolTip("仅清空当前选中PDF的字段配置，其他PDF不受影响\n快捷键: 无")
        btn_clear_current.clicked.connect(self.clear_current)
        btn_layout.addWidget(btn_clear_current)

        # 清空所有字段按钮
        btn_clear_all = PushButton("清空所有字段")
        btn_clear_all.setToolTip("清空所有PDF的字段配置\n快捷键: 无")
        btn_clear_all.clicked.connect(self._on_clear_all_clicked)
        btn_layout.addWidget(btn_clear_all)

        layout.addLayout(btn_layout)

        self._update_empty_state()

    def set_template_name(self, name: str, is_default: bool = False):
        """设置当前模板名称显示"""
        self._current_template_name = name
        if is_default:
            self.template_name_label.setText(f"当前模板: 默认")
            self.template_name_label.setStyleSheet("font-weight: bold; color: #107c10;")
            self.btn_set_default.setEnabled(False)
            self.btn_set_default.setText("设为默认")
        else:
            self.template_name_label.setText(f"当前模板: {name}")
            self.template_name_label.setStyleSheet("font-weight: bold; color: #0078d4;")
            self.btn_set_default.setEnabled(True)
            self.btn_set_default.setText("设为默认模板")

    def _on_set_as_default(self):
        """设为默认模板按钮点击事件"""
        self.set_as_default_template.emit()

    def _update_empty_state(self):
        has_fields = len(self.regions) > 0
        self.empty_label.setVisible(not has_fields)
        self.table.setVisible(has_fields)

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
        # _preview_results 使用 region_id 作为 key（见 show_preview_result 方法第332行）
        # 所以这里不需要更新 _preview_results 的 key
        # 只需要更新识别结果中存储的字段名即可
        if region_id in self._preview_results:
            self._preview_results[region_id].field_name = new_name

        # 发送字段名变更信号
        self.field_name_changed.emit(old_name, new_name)

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
            is_valid, error_msg = validate_with_error(fr.text, region.field_type if region else "text")
            normalized = normalize_by_type(fr.text, region.field_type if region else "text")

            self.detail_content.setText(f"内容：{fr.text}")

            # 显示标准化后的值（如果有变化）
            if normalized != fr.text:
                self.detail_content.setText(f"内容：{fr.text}\n标准化：{normalized}")

            conf_text = f"置信度：{fr.confidence:.2%}"
            if fr.confidence < 0.7:
                conf_text += " (较低)"
                self.detail_confidence.setStyleSheet("color: #d13438;")
            else:
                self.detail_confidence.setStyleSheet("color: #107c10;")

            # 显示验证结果
            if not is_valid:
                self.detail_confidence.setText(f"{conf_text}\n⚠ 格式错误: {error_msg}")
                self.detail_confidence.setStyleSheet("color: #d13438;")
            else:
                self.detail_confidence.setText(conf_text)

            self.detail_widget.setVisible(True)
        else:
            self.detail_widget.setVisible(False)

    def add_region(self, region: Region):
        self.regions[region.id] = region
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
        self.table.setCellWidget(row, 1, type_combo)

        # 识别结果（初始为空）
        self.table.setItem(row, 2, QTableWidgetItem(""))

        # Fluent 删除按钮
        btn = PushButton("删除")
        btn.clicked.connect(lambda _, rid=region.id: self._delete(rid))
        self.table.setCellWidget(row, 3, btn)

        self._update_empty_state()

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
        self.clear_all()
        for r in template.regions:
            self.add_region(r)
        self.region_changed.emit(list(self.regions.values()))

    def show_preview_result(self, file_result):
        """显示试识别结果 - 使用 region_id 匹配确保准确性，并进行字段类型验证"""
        self._preview_results.clear()
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid not in self.regions:
                continue
            region = self.regions[rid]
            # 使用 region_id 对应的 field_name 查找结果
            field_name = region.field_name
            if field_name in file_result.fields:
                fr = file_result.fields[field_name]
                # 使用 region_id 作为 key 存储结果，便于后续查找
                self._preview_results[rid] = fr

                # 根据字段类型进行验证和标准化
                is_valid, error_msg = validate_with_error(fr.text, region.field_type)
                normalized_text = normalize_by_type(fr.text, region.field_type)

                result_item = QTableWidgetItem(normalized_text)

                # 设置 Tooltip 显示完整内容和置信度
                tooltip = f"内容: {fr.text}\n置信度: {fr.confidence:.2%}"

                # 根据验证结果设置样式
                if not is_valid:
                    # 验证失败 - 红色背景
                    result_item.setBackground(QColor("#FFE5E5"))
                    result_item.setForeground(QBrush(QColor("#d13438")))
                    tooltip += f"\n⚠ 格式错误: {error_msg}"
                elif fr.confidence < 0.7:
                    # 置信度低 - 黄色背景
                    result_item.setBackground(QColor("#FFF4E5"))
                    tooltip += "\n(置信度较低，建议核对)"

                result_item.setToolTip(tooltip)
                self.table.setItem(row, 2, result_item)
        # 隐藏详情区域
        self.detail_widget.setVisible(False)

    def _refresh_preview_results(self):
        """根据存储的_preview_results刷新表格显示"""
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item is None:
                continue
            rid = item.data(Qt.ItemDataRole.UserRole)
            if rid in self._preview_results:
                fr = self._preview_results[rid]
                result_item = QTableWidgetItem(fr.text)
                # 设置 Tooltip 显示完整内容和置信度
                tooltip = f"内容: {fr.text}\n置信度: {fr.confidence:.2%}"
                if fr.confidence < 0.7:
                    result_item.setBackground(QColor("#FFE5E5"))
                    tooltip += "\n(置信度较低，建议核对)"
                    result_item.setToolTip(tooltip)
                else:
                    result_item.setToolTip(tooltip)
                self.table.setItem(row, 2, result_item)