import copy
import logging

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QTabWidget,
                               QWidget, QFormLayout, QGroupBox, QLineEdit,
                               QCheckBox, QComboBox, QSpinBox, QPushButton,
                               QDialogButtonBox, QListWidget, QListWidgetItem,
                               QGridLayout, QLabel, QTimeEdit, QScrollArea,
                               QFrame, QAbstractSpinBox, QApplication)
from PySide6.QtCore import Qt, Signal, QTime, QObject, QEvent

from config.app_config import AppConfig

logger = logging.getLogger(__name__)


# 输入控件统一微调：文本框占满剩余宽度，数字框隐藏上下箭头呈纯输入框样式
INPUT_MIN_WIDTH = 220


class _NoWheelFilter(QObject):
    """数字框禁用滚轮改值。

    事件过滤器拦截 QSpinBox/QTimeEdit 的滚轮事件（避免悬停时误改数值），
    并转交给所在的滚动区——悬停在数字框上滚动时页面照常滚动。
    """

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Wheel:
            scroll = watched
            while scroll is not None and not isinstance(scroll, QScrollArea):
                scroll = scroll.parentWidget()
            if scroll is not None:
                event.accept()
                QApplication.sendEvent(scroll.viewport(), event)
            return True
        return super().eventFilter(watched, event)


_no_wheel = _NoWheelFilter()


def _wrap_scroll(content: QWidget) -> QScrollArea:
    """把页面包进纵向滚动区：内容放不下时出滚动条，放得下时不占额外空间。

    视口不自绘背景，与对话框底色融为一体（滚动区默认会铺一层
    面板色，导致各页出现一块不同的背景）。
    """
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.NoFrame)
    scroll.setAutoFillBackground(False)
    scroll.viewport().setAutoFillBackground(False)
    scroll.setWidget(content)
    return scroll


def _polish_inputs(root):
    """微调 root 下所有输入控件：高度保持原生，表单字段自动拉伸填满可用宽度。"""
    # 数字/时间框隐藏右侧上下箭头，外观与普通输入框一致（仍保留取值范围校验）；
    # 同时禁用滚轮改值（悬停滚动交给页面滚动）
    for widget_class in (QSpinBox, QTimeEdit):
        for widget in root.findChildren(widget_class):
            widget.setButtonSymbols(QAbstractSpinBox.NoButtons)
            widget.installEventFilter(_no_wheel)
    for line_edit in root.findChildren(QLineEdit):
        line_edit.setMinimumWidth(INPUT_MIN_WIDTH)
    for form in root.findChildren(QFormLayout):
        form.setFieldGrowthPolicy(QFormLayout.AllNonFixedFieldsGrow)
        form.setLabelAlignment(Qt.AlignRight | Qt.AlignVCenter)
        form.setHorizontalSpacing(12)
        form.setVerticalSpacing(10)


def _to_qtime(text, fallback=(8, 0)):
    """"HH:MM" 字符串 -> QTime；非法值回退默认。"""
    t = QTime.fromString(str(text or ""), "HH:mm")
    return t if t.isValid() else QTime(*fallback)


def _parse_int_list(text):
    """逗号分隔的整数文本 -> list[int]；含非法项时返回 None。"""
    values = []
    for part in str(text).replace("，", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            values.append(int(part))
        except ValueError:
            return None
    return values


class ColumnListEditor(QWidget):
    """列定义编辑器（course_columns / info_table.columns 共用）。

    列表项文本为列名，勾选框控制可见（with_visible=False 时无勾选框，
    如信息面板列）；选中某项后在下方表单编辑名称 / 字段 / 宽度；
    上移 / 下移调整列顺序，添加 / 删除维护列本身。
    fixed_first_name 指定的首列固定在第一位、不可删除（如“选择”列）。
    """

    def __init__(self, columns, with_visible=True, fixed_first_name=None,
                 parent=None):
        super().__init__(parent)
        self._with_visible = with_visible
        self._fixed_first_name = fixed_first_name
        self._loading = False  # 表单回填时屏蔽编辑信号，防止回写覆盖

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        self.list_widget = QListWidget()
        self.list_widget.setMinimumHeight(180)
        self.list_widget.currentItemChanged.connect(self._on_current_changed)
        for col in columns:
            self.list_widget.addItem(self._make_item(dict(col)))
        layout.addWidget(self.list_widget)

        # 上移 / 下移 / 添加 / 删除
        button_row = QHBoxLayout()
        self.button_up = QPushButton("上移")
        self.button_up.clicked.connect(lambda: self._move_current(-1))
        self.button_down = QPushButton("下移")
        self.button_down.clicked.connect(lambda: self._move_current(1))
        self.button_add = QPushButton("添加")
        self.button_add.clicked.connect(self._add_column)
        self.button_remove = QPushButton("删除")
        self.button_remove.clicked.connect(self._remove_column)
        for button in (self.button_up, self.button_down,
                       self.button_add, self.button_remove):
            button_row.addWidget(button)
        button_row.addStretch()
        layout.addLayout(button_row)

        # 选中列的详细编辑表单
        form_group = QGroupBox("列属性")
        form = QFormLayout(form_group)
        self.edit_name = QLineEdit()
        self.edit_name.textChanged.connect(self._on_form_edited)
        self.edit_field = QLineEdit()
        self.edit_field.textChanged.connect(self._on_form_edited)
        self.spin_width = QSpinBox()
        self.spin_width.setRange(0, 5000)
        self.spin_width.setToolTip(
            "列宽（px）。\n课程表列：0 = 使用默认列宽；\n"
            "信息面板列：0 = 自适应拉伸填满剩余宽度。")
        self.spin_width.valueChanged.connect(self._on_form_edited)
        form.addRow("名称", self.edit_name)
        form.addRow("字段", self.edit_field)
        form.addRow("宽度", self.spin_width)
        layout.addWidget(form_group)

        self._fixed_count = 0
        first = self.list_widget.item(0)
        if (first is not None and self._fixed_first_name is not None
                and first.data(Qt.UserRole).get("name") == self._fixed_first_name):
            self._fixed_count = 1

        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)
        self._update_buttons()

    # ---- 构建条目 ----

    def _make_item(self, col: dict) -> QListWidgetItem:
        item = QListWidgetItem(col.get("name", ""))
        if self._with_visible:
            item.setFlags(item.flags() | Qt.ItemIsUserCheckable)
            item.setCheckState(Qt.Checked if col.get("visible", True)
                               else Qt.Unchecked)
        item.setData(Qt.UserRole, col)
        return item

    # ---- 交互 ----

    def _on_current_changed(self, current, _previous):
        self._load_form(current)

    def _load_form(self, item):
        """把选中列的定义回填到表单。"""
        self._loading = True
        if item is None:
            self.edit_name.clear()
            self.edit_field.clear()
            self.spin_width.setValue(0)
            self._set_form_enabled(False)
        else:
            col = item.data(Qt.UserRole)
            self.edit_name.setText(col.get("name", ""))
            self.edit_field.setText(col.get("field", ""))
            self.spin_width.setValue(int(col.get("width", 0) or 0))
            self._set_form_enabled(True)
        self._loading = False
        self._update_buttons()

    def _set_form_enabled(self, enabled: bool):
        self.edit_name.setEnabled(enabled)
        self.edit_field.setEnabled(enabled)
        self.spin_width.setEnabled(enabled)

    def _on_form_edited(self):
        """表单变化 -> 写回当前选中列的定义与显示文本。"""
        if self._loading:
            return
        item = self.list_widget.currentItem()
        if item is None:
            return
        # PySide6 会把 dict 经 QVariant 转换，data() 每次返回副本，
        # 修改后必须 setData 写回才生效
        col = dict(item.data(Qt.UserRole))
        col["name"] = self.edit_name.text()
        col["field"] = self.edit_field.text()
        col["width"] = self.spin_width.value()
        item.setData(Qt.UserRole, col)
        item.setText(col["name"])

    def _move_current(self, delta: int):
        row = self.list_widget.currentRow()
        target = row + delta
        if row < 0 or target < self._fixed_count or target >= self.list_widget.count():
            return
        item = self.list_widget.takeItem(row)
        self.list_widget.insertItem(target, item)
        self.list_widget.setCurrentRow(target)

    def _add_column(self):
        col = {"name": "新列", "field": "", "width": 100}
        if self._with_visible:
            col["visible"] = True
        row = self.list_widget.currentRow() + 1
        self.list_widget.insertItem(row, self._make_item(col))
        self.list_widget.setCurrentRow(row)

    def _remove_column(self):
        row = self.list_widget.currentRow()
        if row < self._fixed_count:
            return
        self.list_widget.takeItem(row)

    def _update_buttons(self):
        row = self.list_widget.currentRow()
        count = self.list_widget.count()
        self.button_up.setEnabled(
            self._fixed_count <= row - 1 and row > 0)
        self.button_down.setEnabled(0 <= row < count - 1)
        self.button_remove.setEnabled(row >= self._fixed_count and row >= 0)

    # ---- 结果 ----

    def columns(self):
        """按当前列表顺序返回列定义列表（dict 副本）。"""
        cols = []
        for index in range(self.list_widget.count()):
            item = self.list_widget.item(index)
            col = dict(item.data(Qt.UserRole))
            if self._with_visible and (item.flags() & Qt.ItemIsUserCheckable):
                col["visible"] = item.checkState() == Qt.Checked
            cols.append(col)
        return cols


class _PlainPaneTabs(QTabWidget):
    """原生标签栏 + 无底色的页容器。

    QTabWidget::paintEvent 只负责绘制内容面板框（PE_FrameTabWidget），
    macOS 原生样式会给面板铺一层底色。这里跳过面板绘制，页面背景与
    对话框一致；标签栏（QTabBar）是独立子控件，仍为系统原生样式。
    """

    def paintEvent(self, event):
        pass


class SettingsDialog(QDialog):
    """全量设置对话框：覆盖 config.json 的所有分区。

    打开时深拷贝一份配置作工作副本，取消即弃；保存时整体写回
    AppConfig（各视图持有同一实例）并落盘，随后发射 config_saved
    供主窗口重新渲染各视图。
    """

    config_saved = Signal(AppConfig)

    LOG_LEVELS = ("DEBUG", "INFO", "WARNING", "ERROR")

    def __init__(self, config: AppConfig, parent=None):
        super().__init__(parent)
        self._config = config
        self._data = copy.deepcopy(config._data)  # 工作副本，保存前不动原配置
        dialog = self._data.get("dialog", {})
        self.resize(max(dialog.get("settings_width", 780), 660),
                    max(dialog.get("settings_height", 700), 560))
        self.setMinimumSize(660, 560)
        self.setWindowTitle("设置")
        self.init_ui()

    def init_ui(self):
        main_layout = QVBoxLayout(self)
        main_layout.setSpacing(12)

        self.tabs = _PlainPaneTabs()
        for title, builder in (("通用", self._create_general_tab),
                               ("教务系统", self._create_hdu_tab),
                               ("课程表列", self._create_columns_tab),
                               ("信息面板", self._create_info_tab),
                               ("课表", self._create_schedule_tab),
                               ("窗口与界面", self._create_advanced_tab)):
            tab = builder()
            tab.layout().setSpacing(12)  # 各页分组之间拉开间距，更易读
            # 内容超高时纵向滚动，短页不受影响
            self.tabs.addTab(_wrap_scroll(tab), title)
        main_layout.addWidget(self.tabs)
        _polish_inputs(self.tabs)  # 统一调整输入控件并让表单字段拉伸

        buttons = QDialogButtonBox(QDialogButtonBox.Save |
                                   QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("保存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        buttons.accepted.connect(self._accept)
        buttons.rejected.connect(self.reject)
        main_layout.addWidget(buttons)

    # ---- 各页构建 ----

    def _create_general_tab(self) -> QWidget:
        files = self._data.get("files", {})
        log = self._data.get("log", {})
        course = self._data.get("course", {})

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        files_group = QGroupBox("数据文件")
        files_form = QFormLayout(files_group)
        self.edit_course_pool = QLineEdit(files.get("course_pool", ""))
        self.edit_selected_courses = QLineEdit(files.get("selected_courses", ""))
        self.edit_jiaowu_courses = QLineEdit(files.get("jiaowu_courses", ""))
        files_form.addRow("课程池文件", self.edit_course_pool)
        files_form.addRow("已选课程文件", self.edit_selected_courses)
        files_form.addRow("教务已选课文件", self.edit_jiaowu_courses)
        tab_layout.addWidget(files_group)

        course_group = QGroupBox("课程")
        course_form = QFormLayout(course_group)
        self.edit_key_field = QLineEdit(course.get("key_field", "jxbmc"))
        self.edit_key_field.setToolTip("课程的唯一标识字段，如 jxbmc（教学班名称）")
        course_form.addRow("唯一标识字段", self.edit_key_field)
        tab_layout.addWidget(course_group)

        log_group = QGroupBox("日志")
        log_form = QFormLayout(log_group)
        self.edit_log_file = QLineEdit(log.get("file", ""))
        log_form.addRow("日志文件", self.edit_log_file)
        self.combo_log_level = QComboBox()
        self.combo_log_level.addItems(list(self.LOG_LEVELS))
        self.combo_log_level.setCurrentText(log.get("level", "DEBUG"))
        log_form.addRow("文件记录级别", self.combo_log_level)
        self.check_log_console = QCheckBox("同时输出到控制台")
        self.check_log_console.setChecked(log.get("console", True))
        log_form.addRow("", self.check_log_console)
        self.combo_log_console_level = QComboBox()
        self.combo_log_console_level.addItems(list(self.LOG_LEVELS))
        self.combo_log_console_level.setCurrentText(log.get("console_level", "INFO"))
        log_form.addRow("控制台记录级别", self.combo_log_console_level)
        self.check_log_clear = QCheckBox("每次启动清空日志文件（不勾选则追加）")
        self.check_log_clear.setChecked(log.get("clear_on_start", True))
        log_form.addRow("", self.check_log_clear)
        tab_layout.addWidget(log_group)

        tab_layout.addStretch()
        return tab

    def _create_hdu_tab(self) -> QWidget:
        hdu = self._data.get("hdu", {})
        newjw = hdu.get("newjw", {})
        cas = hdu.get("cas", {})
        cookies = hdu.get("cookies", {})

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        newjw_group = QGroupBox("教务系统账号（newjw，优先登录）")
        newjw_form = QFormLayout(newjw_group)
        self.edit_newjw_username = QLineEdit(newjw.get("username", ""))
        self.edit_newjw_password = QLineEdit(newjw.get("password", ""))
        self.edit_newjw_password.setEchoMode(QLineEdit.Password)
        newjw_form.addRow("用户名", self.edit_newjw_username)
        newjw_form.addRow("密码", self.edit_newjw_password)
        tab_layout.addWidget(newjw_group)

        cas_group = QGroupBox("统一身份认证账号（cas，newjw 失败时兜底）")
        cas_form = QFormLayout(cas_group)
        self.edit_cas_username = QLineEdit(cas.get("username", ""))
        self.edit_cas_password = QLineEdit(cas.get("password", ""))
        self.edit_cas_password.setEchoMode(QLineEdit.Password)
        cas_form.addRow("用户名", self.edit_cas_username)
        cas_form.addRow("密码", self.edit_cas_password)
        tab_layout.addWidget(cas_group)

        term_group = QGroupBox("学年学期")
        term_form = QFormLayout(term_group)
        self.edit_xuenian = QLineEdit(str(hdu.get("xuenian", "")))
        self.edit_xuenian.setToolTip("学年（秋季学期所在年份），如 2026")
        term_form.addRow("学年", self.edit_xuenian)
        self.combo_xueqi = QComboBox()
        self.combo_xueqi.addItem("1（秋季）", "1")
        self.combo_xueqi.addItem("2（春季）", "2")
        index = self.combo_xueqi.findData(str(hdu.get("xueqi", "1")))
        self.combo_xueqi.setCurrentIndex(max(index, 0))
        term_form.addRow("学期", self.combo_xueqi)
        self.check_auto_update = QCheckBox("勾选课程后自动在线更新个人课表")
        self.check_auto_update.setChecked(
            hdu.get("update_schedule_after_selection", False))
        term_form.addRow("", self.check_auto_update)
        tab_layout.addWidget(term_group)

        net_group = QGroupBox("网络")
        net_form = QFormLayout(net_group)
        self.spin_course_timeout = QSpinBox()
        self.spin_course_timeout.setRange(1, 86400)
        self.spin_course_timeout.setValue(int(hdu.get("course_timeout", 600)))
        net_form.addRow("课程池查询超时（秒）", self.spin_course_timeout)
        self.spin_course_retries = QSpinBox()
        self.spin_course_retries.setRange(0, 20)
        self.spin_course_retries.setValue(int(hdu.get("course_retries", 2)))
        net_form.addRow("课程池查询重试次数", self.spin_course_retries)
        self.spin_schedule_timeout = QSpinBox()
        self.spin_schedule_timeout.setRange(1, 86400)
        self.spin_schedule_timeout.setValue(int(hdu.get("schedule_timeout", 30)))
        net_form.addRow("个人课表查询超时（秒）", self.spin_schedule_timeout)
        self.spin_schedule_retries = QSpinBox()
        self.spin_schedule_retries.setRange(0, 20)
        self.spin_schedule_retries.setValue(int(hdu.get("schedule_retries", 2)))
        net_form.addRow("个人课表查询重试次数", self.spin_schedule_retries)
        self.edit_user_agent = QLineEdit(hdu.get("user_agent", ""))
        self.edit_user_agent.setToolTip("留空 = 使用内置 UA")
        net_form.addRow("User-Agent", self.edit_user_agent)
        tab_layout.addWidget(net_group)

        cookie_group = QGroupBox("Cookie（登录成功后自动回写，可免登录）")
        cookie_form = QFormLayout(cookie_group)
        self.check_cookies_enabled = QCheckBox("启用 Cookie 免登录")
        self.check_cookies_enabled.setChecked(cookies.get("enabled", True))
        cookie_form.addRow("", self.check_cookies_enabled)
        self.edit_jsessionid = QLineEdit(cookies.get("jsessionid", ""))
        cookie_form.addRow("JSESSIONID", self.edit_jsessionid)
        self.edit_route = QLineEdit(cookies.get("route", ""))
        cookie_form.addRow("route", self.edit_route)
        tab_layout.addWidget(cookie_group)

        tab_layout.addStretch()
        return tab

    def _create_columns_tab(self) -> QWidget:
        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        self.course_columns_editor = ColumnListEditor(
            self._data.get("course_columns", []),
            with_visible=True, fixed_first_name="选择")
        tab_layout.addWidget(self.course_columns_editor)

        note = QLabel("“选择”列固定在首位且始终可见；勾选框控制列是否显示。")
        note.setWordWrap(True)
        tab_layout.addWidget(note)
        return tab

    def _create_info_tab(self) -> QWidget:
        info = self._data.get("info_table", {})

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        metric_group = QGroupBox("表格度量")
        metric_form = QFormLayout(metric_group)
        self.spin_info_row_height = QSpinBox()
        self.spin_info_row_height.setRange(10, 200)
        self.spin_info_row_height.setValue(int(info.get("row_height", 28)))
        metric_form.addRow("行高（px）", self.spin_info_row_height)
        self.spin_info_max_width = QSpinBox()
        self.spin_info_max_width.setRange(-1, 10000)
        self.spin_info_max_width.setValue(int(info.get("max_width", 0)))
        self.spin_info_max_width.setToolTip(
            "0 = 自适应不限宽；-1 = 跟随上方课表网格宽度；>0 = 固定上限（px）")
        metric_form.addRow("整表最大宽度", self.spin_info_max_width)
        tab_layout.addWidget(metric_group)

        self.info_columns_editor = ColumnListEditor(
            info.get("columns", []), with_visible=False)
        tab_layout.addWidget(self.info_columns_editor)

        note = QLabel("field 留空为计算列：第一个空 field 列显示“类型”，"
                      "最后一个显示“说明”。")
        note.setWordWrap(True)
        tab_layout.addWidget(note)
        return tab

    def _create_schedule_tab(self) -> QWidget:
        sched = self._data.get("schedule", {})

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        base_group = QGroupBox("基础")
        base_form = QFormLayout(base_group)
        self.spin_total_weeks = QSpinBox()
        self.spin_total_weeks.setRange(1, 30)
        self.spin_total_weeks.setValue(int(sched.get("total_weeks", 17)))
        base_form.addRow("教学周数", self.spin_total_weeks)
        self.edit_practice_location = QLineEdit(
            sched.get("practice_location", ""))
        self.edit_practice_location.setToolTip("该地点的课程周次按空闲处理")
        base_form.addRow("课外实践地点", self.edit_practice_location)
        self.spin_credit_limit = QSpinBox()
        self.spin_credit_limit.setRange(0, 200)
        self.spin_credit_limit.setValue(int(sched.get("credit_limit", 0)))
        self.spin_credit_limit.setToolTip("超出部分在统计栏标红；0 = 不启用上限")
        base_form.addRow("学分上限", self.spin_credit_limit)
        tab_layout.addWidget(base_group)

        # 节次时间：双列网格（1-6 节居左，其余居右）
        period_group = QGroupBox("节次时间")
        period_grid = QGridLayout(period_group)
        raw_periods = sched.get("period_times", {})
        keys = sorted(raw_periods.keys(), key=lambda k: int(k))
        self._period_edits = []  # [(键, 起始 QTimeEdit, 结束 QTimeEdit)]
        half = (len(keys) + 1) // 2
        for i, key in enumerate(keys):
            block, row = divmod(i, half)
            value = raw_periods.get(key) or []
            start_text = value[0] if isinstance(value, list) and value else ""
            end_text = value[1] if isinstance(value, list) and len(value) > 1 else ""
            start_edit = QTimeEdit(_to_qtime(start_text))
            end_edit = QTimeEdit(_to_qtime(end_text, (8, 45)))
            for edit in (start_edit, end_edit):
                edit.setDisplayFormat("HH:mm")
            column = block * 3
            period_grid.addWidget(QLabel(f"第{key}节"), row, column)
            period_grid.addWidget(start_edit, row, column + 1)
            period_grid.addWidget(end_edit, row, column + 2)
            self._period_edits.append((key, start_edit, end_edit))
        tab_layout.addWidget(period_group)

        # 星期名称与始终显示的星期列
        names = list(sched.get("weekdays", []))
        always = set(sched.get("weekday_always", []))
        weekday_group = QGroupBox("星期")
        weekday_grid = QGridLayout(weekday_group)
        self._weekday_checks = []
        for i in range(7):
            label = names[i] if i < len(names) else f"第{i + 1}天"
            check = QCheckBox(f"{label}始终显示")
            check.setChecked(i in always)
            weekday_grid.addWidget(check, i // 4, i % 4)
            self._weekday_checks.append(check)
        weekday_grid.addWidget(
            QLabel("星期名称（逗号分隔，须为 7 个）："), 2, 0, 1, 4)
        self.edit_weekdays = QLineEdit(", ".join(names))
        weekday_grid.addWidget(self.edit_weekdays, 3, 0, 1, 4)
        tab_layout.addWidget(weekday_group)

        tab_layout.addStretch()
        return tab

    def _create_advanced_tab(self) -> QWidget:
        table = self._data.get("table", {})
        layout_cfg = self._data.get("layout", {})
        export = self._data.get("export", {})
        window = self._data.get("window", {})
        dialog = self._data.get("dialog", {})

        tab = QWidget()
        tab_layout = QVBoxLayout(tab)

        table_group = QGroupBox("课程表")
        table_form = QFormLayout(table_group)
        self.spin_default_column_width = QSpinBox()
        self.spin_default_column_width.setRange(10, 2000)
        self.spin_default_column_width.setValue(
            int(table.get("default_column_width", 120)))
        table_form.addRow("默认列宽（px）", self.spin_default_column_width)
        self.spin_export_scale = QSpinBox()
        self.spin_export_scale.setRange(1, 16)
        self.spin_export_scale.setValue(int(export.get("scale", 4)))
        table_form.addRow("导出 PNG 超采样倍数", self.spin_export_scale)
        tab_layout.addWidget(table_group)

        layout_group = QGroupBox("面板布局")
        layout_form = QFormLayout(layout_group)
        self.spin_margin = QSpinBox()
        self.spin_margin.setRange(0, 100)
        self.spin_margin.setValue(int(layout_cfg.get("margin", 10)))
        layout_form.addRow("四周留白（px）", self.spin_margin)
        self.spin_spacing = QSpinBox()
        self.spin_spacing.setRange(0, 100)
        self.spin_spacing.setValue(int(layout_cfg.get("spacing", 10)))
        layout_form.addRow("控件间距（px）", self.spin_spacing)
        self.spin_scroll_pad = QSpinBox()
        self.spin_scroll_pad.setRange(0, 200)
        self.spin_scroll_pad.setValue(int(layout_cfg.get("scroll_pad", 24)))
        layout_form.addRow("滚动条预留（px）", self.spin_scroll_pad)
        tab_layout.addWidget(layout_group)

        window_group = QGroupBox("窗口（保存后重启生效）")
        window_form = QFormLayout(window_group)
        self.spin_window_width = QSpinBox()
        self.spin_window_width.setRange(400, 10000)
        self.spin_window_width.setValue(int(window.get("width", 1500)))
        window_form.addRow("窗口宽度", self.spin_window_width)
        self.spin_window_height = QSpinBox()
        self.spin_window_height.setRange(300, 10000)
        self.spin_window_height.setValue(int(window.get("height", 800)))
        window_form.addRow("窗口高度", self.spin_window_height)
        self.spin_handle_width = QSpinBox()
        self.spin_handle_width.setRange(1, 50)
        self.spin_handle_width.setValue(int(window.get("handle_width", 8)))
        window_form.addRow("分隔条宽度（px）", self.spin_handle_width)
        self.spin_schedule_min_width = QSpinBox()
        self.spin_schedule_min_width.setRange(100, 5000)
        self.spin_schedule_min_width.setValue(
            int(window.get("schedule_min_width", 360)))
        window_form.addRow("课表最小宽度", self.spin_schedule_min_width)
        self.spin_course_min_width = QSpinBox()
        self.spin_course_min_width.setRange(100, 5000)
        self.spin_course_min_width.setValue(
            int(window.get("course_min_width", 280)))
        window_form.addRow("课程表最小宽度", self.spin_course_min_width)
        self.spin_h_min_height = QSpinBox()
        self.spin_h_min_height.setRange(50, 5000)
        self.spin_h_min_height.setValue(int(window.get("h_min_height", 150)))
        window_form.addRow("上栏最小高度", self.spin_h_min_height)
        self.spin_info_min_height = QSpinBox()
        self.spin_info_min_height.setRange(50, 5000)
        self.spin_info_min_height.setValue(
            int(window.get("info_min_height", 120)))
        window_form.addRow("信息面板最小高度", self.spin_info_min_height)

        # 列表值（分割器初始尺寸 / 拉伸系数）：逗号分隔编辑
        self.edit_splitter_h = QLineEdit(
            ", ".join(str(v) for v in window.get("splitter_h_sizes", [780, 720])))
        self.edit_splitter_h.setToolTip("左右分割器初始尺寸，逗号分隔，如 780, 720")
        window_form.addRow("左右分割尺寸", self.edit_splitter_h)
        self.edit_splitter_v = QLineEdit(
            ", ".join(str(v) for v in window.get("splitter_v_sizes", [650, 150])))
        self.edit_splitter_v.setToolTip("上下分割器初始尺寸，逗号分隔，如 650, 150")
        window_form.addRow("上下分割尺寸", self.edit_splitter_v)
        self.edit_h_stretch = QLineEdit(
            ", ".join(str(v) for v in window.get("h_stretch", [6, 4])))
        self.edit_h_stretch.setToolTip("左右拉伸系数，逗号分隔，如 6, 4")
        window_form.addRow("左右拉伸系数", self.edit_h_stretch)
        self.edit_v_stretch = QLineEdit(
            ", ".join(str(v) for v in window.get("v_stretch", [7, 3])))
        self.edit_v_stretch.setToolTip("上下拉伸系数，逗号分隔，如 7, 3")
        window_form.addRow("上下拉伸系数", self.edit_v_stretch)
        tab_layout.addWidget(window_group)

        dialog_group = QGroupBox("设置对话框（保存后下次打开生效）")
        dialog_form = QFormLayout(dialog_group)
        self.spin_settings_width = QSpinBox()
        self.spin_settings_width.setRange(660, 5000)
        self.spin_settings_width.setValue(
            int(dialog.get("settings_width", 780)))
        dialog_form.addRow("对话框宽度", self.spin_settings_width)
        self.spin_settings_height = QSpinBox()
        self.spin_settings_height.setRange(560, 5000)
        self.spin_settings_height.setValue(
            int(dialog.get("settings_height", 700)))
        dialog_form.addRow("对话框高度", self.spin_settings_height)
        tab_layout.addWidget(dialog_group)

        tab_layout.addStretch()
        return tab

    # ---- 保存 ----

    def _accept(self):
        """收集全部控件值写回工作副本，整体写回 AppConfig 并落盘。"""
        self._collect()

        # “选择”列固定可见
        for col in self._data.get("course_columns", []):
            if col.get("name") == "选择":
                col["visible"] = True

        # 写回同一实例（各视图持有该实例引用），再持久化
        self._config._data = self._data
        try:
            self._config.save_config()
        except OSError as e:
            logger.error("配置保存失败：%s", e)
        self.config_saved.emit(self._config)
        super().accept()

    def _collect(self):
        data = self._data

        files = data.setdefault("files", {})
        files["course_pool"] = self.edit_course_pool.text().strip()
        files["selected_courses"] = self.edit_selected_courses.text().strip()
        files["jiaowu_courses"] = self.edit_jiaowu_courses.text().strip()

        log = data.setdefault("log", {})
        log["file"] = self.edit_log_file.text().strip()
        log["level"] = self.combo_log_level.currentText()
        log["console"] = self.check_log_console.isChecked()
        log["console_level"] = self.combo_log_console_level.currentText()
        log["clear_on_start"] = self.check_log_clear.isChecked()

        course = data.setdefault("course", {})
        course["key_field"] = self.edit_key_field.text().strip()

        hdu = data.setdefault("hdu", {})
        hdu["newjw"] = {"username": self.edit_newjw_username.text(),
                        "password": self.edit_newjw_password.text()}
        hdu["cas"] = {"username": self.edit_cas_username.text(),
                      "password": self.edit_cas_password.text()}
        hdu["xuenian"] = self.edit_xuenian.text().strip()
        hdu["xueqi"] = str(self.combo_xueqi.currentData())
        hdu["update_schedule_after_selection"] = self.check_auto_update.isChecked()
        hdu["course_timeout"] = self.spin_course_timeout.value()
        hdu["course_retries"] = self.spin_course_retries.value()
        hdu["schedule_timeout"] = self.spin_schedule_timeout.value()
        hdu["schedule_retries"] = self.spin_schedule_retries.value()
        hdu["user_agent"] = self.edit_user_agent.text()
        hdu["cookies"] = {"enabled": self.check_cookies_enabled.isChecked(),
                          "jsessionid": self.edit_jsessionid.text(),
                          "route": self.edit_route.text()}

        data["course_columns"] = self.course_columns_editor.columns()

        info = data.setdefault("info_table", {})
        info["row_height"] = self.spin_info_row_height.value()
        info["max_width"] = self.spin_info_max_width.value()
        info["columns"] = self.info_columns_editor.columns()

        sched = data.setdefault("schedule", {})
        sched["total_weeks"] = self.spin_total_weeks.value()
        sched["period_times"] = {
            key: [start.time().toString("HH:mm"), end.time().toString("HH:mm")]
            for key, start, end in self._period_edits}
        sched["weekdays"] = [part.strip() for part in
                             self.edit_weekdays.text().replace("，", ",").split(",")
                             if part.strip()]
        sched["weekday_always"] = [i for i, check in enumerate(self._weekday_checks)
                                   if check.isChecked()]
        sched["practice_location"] = self.edit_practice_location.text()
        sched["credit_limit"] = self.spin_credit_limit.value()

        table = data.setdefault("table", {})
        table["default_column_width"] = self.spin_default_column_width.value()

        layout_cfg = data.setdefault("layout", {})
        layout_cfg["margin"] = self.spin_margin.value()
        layout_cfg["spacing"] = self.spin_spacing.value()
        layout_cfg["scroll_pad"] = self.spin_scroll_pad.value()

        export = data.setdefault("export", {})
        export["scale"] = self.spin_export_scale.value()

        window = data.setdefault("window", {})
        window["width"] = self.spin_window_width.value()
        window["height"] = self.spin_window_height.value()
        window["handle_width"] = self.spin_handle_width.value()
        window["schedule_min_width"] = self.spin_schedule_min_width.value()
        window["course_min_width"] = self.spin_course_min_width.value()
        window["h_min_height"] = self.spin_h_min_height.value()
        window["info_min_height"] = self.spin_info_min_height.value()
        for key, edit in (("splitter_h_sizes", self.edit_splitter_h),
                          ("splitter_v_sizes", self.edit_splitter_v),
                          ("h_stretch", self.edit_h_stretch),
                          ("v_stretch", self.edit_v_stretch)):
            values = _parse_int_list(edit.text())
            if values:  # 解析失败保留原值
                window[key] = values

        dialog = data.setdefault("dialog", {})
        dialog["settings_width"] = self.spin_settings_width.value()
        dialog["settings_height"] = self.spin_settings_height.value()
