from PySide6.QtWidgets import (QDialog, QVBoxLayout, QListWidget, QHBoxLayout,
                               QPushButton, QCheckBox, QWidget, QGroupBox,
                               QListWidgetItem, QTabWidget)
from PySide6.QtCore import Qt, Signal

from config.app_config import AppConfig


class SettingsDialog(QDialog):
    config_saved = Signal(AppConfig)

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self.current_config = config
        self.setWindowTitle("Settings")
        dialog = config.dialog
        self.resize(dialog.get("settings_width", 450),
                     dialog.get("settings_height", 350))
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._create_course_tab(), "显示设置")
        main_layout.addWidget(self.tabs)

        button_layout = QHBoxLayout()
        button_layout.addStretch()

        save_button = QPushButton("保存")
        save_button.clicked.connect(self._accept)
        button_layout.addWidget(save_button)
        cancel_button = QPushButton("取消")
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(cancel_button)

        main_layout.addLayout(button_layout)

    def _create_course_tab(self) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        col_group_box = QGroupBox("列显示设置")
        col_group_layout = QVBoxLayout(col_group_box)

        self.list_widget = QListWidget()
        self.list_widget.currentRowChanged.connect(self._update_button_states)

        for col in self.current_config.course_columns:
            name = col.get("name", "")
            item = QListWidgetItem(name)
            checkbox = QCheckBox()
            checkbox.setChecked(col.get("visible", True))
            if name == "选择":
                checkbox.setEnabled(False)  # "选择" 列固定可见，不可取消勾选
            self.list_widget.addItem(item)
            self.list_widget.setItemWidget(item, checkbox)
            item.setData(Qt.UserRole, dict(col))  # 记录该列定义，供交换/保存时使用
        col_group_layout.addWidget(self.list_widget)

        # 上下移动按钮，用于调整列顺序
        button_box = QVBoxLayout()
        self.button_up = QPushButton("▲")
        self.button_up.clicked.connect(self._move_item_up)
        self.button_down = QPushButton("▼")
        self.button_down.clicked.connect(self._move_item_down)
        button_box.addWidget(self.button_up)
        button_box.addWidget(self.button_down)
        button_box.addStretch()

        col_group_layout.addLayout(button_box)
        tab_layout.addWidget(col_group_box)

        self._update_button_states(self.list_widget.currentRow())
        return tab

    def _update_button_states(self, current_row: int):
        total = self.list_widget.count()
        if current_row <= 0:
            self.button_up.setEnabled(False)
            self.button_down.setEnabled(False)
        else:
            self.button_up.setEnabled(current_row > 1)
            self.button_down.setEnabled(current_row < total - 1)

    def _move_item_up(self):
        current_row = self.list_widget.currentRow()
        if current_row > 1:
            self._swap_items(current_row, current_row - 1)
            self.list_widget.setCurrentRow(current_row - 1)

    def _move_item_down(self):
        current_row = self.list_widget.currentRow()
        if current_row < self.list_widget.count() - 1 and current_row > 0:
            self._swap_items(current_row, current_row + 1)
            self.list_widget.setCurrentRow(current_row + 1)

    def _swap_items(self, row1, row2):
        item1 = self.list_widget.item(row1)
        item2 = self.list_widget.item(row2)

        col1 = item1.data(Qt.UserRole)
        col2 = item2.data(Qt.UserRole)

        checkbox1 = self.list_widget.itemWidget(item1)
        checkbox2 = self.list_widget.itemWidget(item2)

        cb1_checked = checkbox1.isChecked() if checkbox1 else True
        cb2_checked = checkbox2.isChecked() if checkbox2 else True
        cb1_enabled = checkbox1.isEnabled() if checkbox1 else True
        cb2_enabled = checkbox2.isEnabled() if checkbox2 else True

        # 交换两行的列定义与显示文本
        item1.setData(Qt.UserRole, col2)
        item2.setData(Qt.UserRole, col1)
        item1.setText(col2.get("name", ""))
        item2.setText(col1.get("name", ""))

        # 交换两行复选框的勾选/可用状态
        checkbox1.setChecked(cb2_checked)
        checkbox1.setEnabled(cb2_enabled)
        checkbox2.setChecked(cb1_checked)
        checkbox2.setEnabled(cb1_enabled)

    def _accept(self):
        course_columns = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            col = dict(item.data(Qt.UserRole))
            checkbox = self.list_widget.itemWidget(item)
            # "选择" 列固定可见
            visible = True if col.get("name") == "选择" else (
                checkbox.isChecked() if checkbox else True)
            col["visible"] = visible
            course_columns.append(col)
        self.current_config.course_columns = course_columns
        self.current_config.save_config()
        self.config_saved.emit(self.current_config)
        super().accept()
