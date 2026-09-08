import logging

from PySide6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLineEdit,
                               QTableWidget, QHeaderView,
                               QTableWidgetItem, QAbstractItemView,
                               QMenu, QApplication, QStyledItemDelegate,
                               QStyle, QStyleOptionViewItem, QStyleOptionButton)
from PySide6.QtCore import Qt, Signal, QThread, QObject, QTimer, QRect
from PySide6.QtGui import QAction, QShortcut, QKeySequence

from config.app_config import AppConfig
from data.course_loader import load_courses_from_file
from data.selection_store import load_selected_courses, save_selected_courses
from ui import search as search_logic

logger = logging.getLogger(__name__)

"""
搜索语法（见 refresh 与 ui.search）：

  优先级：! > | > 空格        （非 > 或 > 且）
  空格  → 且（AND）          计算机网络 肖周芳 = 同时包含“计算机网络”与“肖周芳”
  |     → 或（OR）           肖周|王晓 = 包含“肖周”或“王晓”
  !     → 非（NOT）          !肖周芳 = 不包含“肖周芳”；!1-2节 = 不包含“1-2节”

  规则B（宽容）：先剥离 | 两侧空格再解析。
    “肖周|王晓 赵云”   = (肖周 OR 王晓) AND 赵云
    “肖周 | 王晓 | 赵云” = 肖周 OR 王晓 OR 赵云（| 两侧空格被剥离，同样有效）

  作用域：
    !  仅对“课程名 / 教师姓名 / 教师工号 / 上课时间 / 校区”生效；不对
       开课学院/教学班名称/教学班组成/课程代码/学分/其它可见字段生效。
    |  仅对“时间 / 教师”字段有效；含 | 的组不会命中其它字段。
    普通词在全部字段按各自模式匹配。

  匹配模式与可见性：见 ui.search 模块 docstring（课程名/开课学院子序列简写、
    教师姓名/校区包含、教师工号/课程代码/学分全文、教学班名称有无学年学期
    前缀全文、教学班组成按班级号全文、时间星期⇄周归一；这些字段隐藏也可搜）。

  鲁棒性：时间字段做 星期⇄周 归一（“周一”匹配“星期一…”）。
"""

class CourseLoaderWorker(QObject):
    """后台加载开课课程池与已选课程，避免大文件解析阻塞 UI。"""
    finished = Signal(list, list)  # (course_pool, selected_courses)

    def __init__(self, pool_path, selected_path):
        super().__init__()
        self._pool_path = pool_path
        self._selected_path = selected_path

    def run(self):
        pool = load_courses_from_file(self._pool_path)
        selected = load_selected_courses(self._selected_path)
        self.finished.emit(pool, selected)


class CenteredCheckDelegate(QStyledItemDelegate):
    """“选择”列勾选指示器居中绘制。

    默认样式中勾选指示器固定画在单元格左侧（不受 setTextAlignment
    影响），窄列（如 30px 的“选择”列）下贴边不对称。此委托只经
    setItemDelegateForColumn 挂在“选择”列上，其余列不经过它；
    背景（选中/悬停/隔行）仍按默认绘制。
    """

    def paint(self, painter, option, index):
        if not (index.flags() & Qt.ItemIsUserCheckable):  # 防御：非勾选格
            super().paint(painter, option, index)
            return
        opt = QStyleOptionViewItem(option)
        self.initStyleOption(opt, index)
        # 画默认内容（选中/悬停/隔行底色），但去掉指示器与文字
        opt.features &= ~QStyleOptionViewItem.HasCheckIndicator
        opt.text = ""
        style = opt.widget.style() if opt.widget else QApplication.style()
        style.drawControl(QStyle.CE_ItemViewItem, opt, painter, opt.widget)
        # 格子中央画勾选指示器
        w = style.pixelMetric(QStyle.PM_IndicatorWidth, opt, opt.widget)
        h = style.pixelMetric(QStyle.PM_IndicatorHeight, opt, opt.widget)
        cb = QStyleOptionButton()
        cb.rect = QRect(opt.rect.center().x() - w // 2,
                        opt.rect.center().y() - h // 2, w, h)
        cb.state = QStyle.State_Enabled
        if opt.checkState == Qt.Checked:
            cb.state |= QStyle.State_On
        elif opt.checkState == Qt.PartiallyChecked:
            cb.state |= QStyle.State_NoChange
        style.drawPrimitive(QStyle.PE_IndicatorCheckBox, cb,
                            painter, opt.widget)


class CourseView(QWidget):
    selection_changed = Signal(list)  # 发射当前已选课程(dict)列表，供 schedule_view 等使用
    selection_toggled = Signal()      # 用户改变勾选（点击或空格框选）后（供主窗口按配置触发个人课表更新）

    def __init__(self, config: AppConfig):
        super().__init__()
        self.raw_course_data = []      # 开课课程数据池
        self.selected_courses = []     # 已选课程（完整 dict 列表，用于持久化与发信号）
        self.selected_keys = set()     # 已选课程的唯一标识集合（由 selected_courses 派生）
        self.filtered_data = []        # 表格当前展示的数据
        self.current_config = config
        self._loader_thread = None
        self._loader_worker = None
        self._check_delegate = None  # “选择”列勾选框居中委托（按列挂载）
        self.init_ui()
        self.update_table_columns()    # 先建好表头（空数据）
        self._start_loader()           # 后台加载数据，完成后填充

    # ---- 由配置派生（路径 / 标识字段 / 列宽）----

    def _pool_file(self):
        return self.current_config.files.get("course_pool", "example_course.json")

    def _selected_file(self):
        return self.current_config.files.get(
            "selected_courses", "selected_courses.json")

    def _key_field(self):
        return self.current_config.course.get("key_field", "jxbmc")

    def _default_col_width(self):
        return self.current_config.table.get("default_column_width", 120)

    def _start_loader(self):
        """在后台线程加载课程数据，防止大文件解析阻塞 UI。"""
        self._loader_worker = CourseLoaderWorker(
            self._pool_file(), self._selected_file())
        self._loader_thread = QThread()
        self._loader_worker.moveToThread(self._loader_thread)
        self._loader_thread.started.connect(self._loader_worker.run)
        self._loader_worker.finished.connect(self._on_loaded)
        self._loader_worker.finished.connect(self._loader_thread.quit)
        self._loader_thread.finished.connect(self._loader_thread.deleteLater)
        self._loader_thread.start()

    def _on_loaded(self, pool, selected):
        """后台加载完成，在 UI 线程填充数据。"""
        logger.info("本地数据加载完成：课程池 %d 门，已选 %d 门",
                    len(pool), len(selected))
        self.raw_course_data = pool
        self.selected_courses = selected
        self.selected_keys = {self._key(c) for c in selected}
        self.refresh()
        self._emit_selection()  # 初次加载后通知课表视图

    def reload_pool(self):
        """课程池文件被外部更新（如在线拉取）后重新加载并刷新表格。"""
        self._stop_loader()
        self._start_loader()

    def _stop_loader(self):
        """窗口关闭时确保加载线程结束，避免 QThread 析构时仍运行导致崩溃。
        线程结束后 finished -> deleteLater 可能已删掉 C++ 对象，此时 Python
        侧仍持有失效包装器，调用任意方法会抛 RuntimeError，需安全处理。
        """
        thread = self._loader_thread
        if thread is None:
            return
        try:
            running = thread.isRunning()
        except RuntimeError:
            self._loader_thread = None
            self._loader_worker = None
            return
        if not running:
            self._loader_thread = None
            self._loader_worker = None
            return
        # 断开完成回调，防止在已销毁的控件上更新 UI
        if self._loader_worker is not None:
            try:
                self._loader_worker.finished.disconnect()
            except RuntimeError:
                pass
        thread.quit()
        thread.wait(10000)
        self._loader_thread = None
        self._loader_worker = None

    def init_ui(self):
        layout = self.current_config.layout
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(layout.get("margin", 10),
                                       layout.get("margin", 10),
                                       layout.get("margin", 10),
                                       layout.get("margin", 10))
        main_layout.setSpacing(layout.get("spacing", 10))

        # 搜索栏：行高与 schedule_view 顶部统计栏一致（34px），
        # 保证两侧表格顶部对齐
        search_layout = QHBoxLayout()
        search_layout.setContentsMargins(0, 0, 0, 0)
        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("搜索任意信息，支持特定搜索语法，见帮助；置空则已选课程置顶，有些特殊语法可能出现未定义效果，可以反馈")
        self.search_input.setFixedHeight(34)
        search_layout.addWidget(self.search_input, stretch=1)
        main_layout.addLayout(search_layout)

        self._search_timer = QTimer(self)
        self._search_timer.setSingleShot(True)
        self._search_timer.setInterval(100)
        self._search_timer.timeout.connect(self.refresh)
        self.search_input.textChanged.connect(self._search_timer.start)

        # 回车立即搜索
        self.search_input.returnPressed.connect(self._search_timer.stop)
        self.search_input.returnPressed.connect(self.refresh)

        # 课程表格（不可编辑，右键复制）
        self.table = QTableWidget()
        self.table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setAlternatingRowColors(True)
        # Columns resizable and horizontally scrollable when content overflows
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.horizontalHeader().setDefaultSectionSize(self._default_col_width())
        self.table.verticalHeader().setVisible(False)

        main_layout.addWidget(self.table)

        self.table.itemChanged.connect(self._on_item_changed)

        # 右键菜单：复制教学班名称 / 课程名称 / 课程代码
        self.table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._show_context_menu)

        # Ctrl/Cmd+C 复制选中行的教学班名称
        self.copy_shortcut = QShortcut(QKeySequence.Copy, self.table)
        self.copy_shortcut.activated.connect(self._copy_selected_key)

        # 空格：对选中行批量切换勾选（框选）
        self.space_shortcut = QShortcut(QKeySequence(Qt.Key_Space), self.table)
        self.space_shortcut.activated.connect(self._toggle_selected_checkstates)

    # ---- 唯一标识 ----

    def _key(self, course):
        return course.get(self._key_field(), "")

    # ---- 配置 / 表格重建 ----

    def apply_config(self, config: AppConfig):
        self.current_config = config
        self.update_table_columns()

    def update_table_columns(self):
        """根据当前配置的可见列重建表格列，并刷新行。"""
        columns = self.current_config.get_visible_columns()
        names = [c.get("name", "") for c in columns]
        self.table.blockSignals(True)
        self.table.setColumnCount(len(columns))
        self.table.setHorizontalHeaderLabels(names)
        header = self.table.horizontalHeader()
        for col, col_def in enumerate(columns):
            width = col_def.get("width", 0)
            header.setSectionResizeMode(col, QHeaderView.Interactive)
            header.resizeSection(col, width if width and width > 0
                                 else self._default_col_width())
        self.table.setRowCount(0)
        self.table.blockSignals(False)
        self._apply_check_delegate(columns)
        self.refresh()

    def _apply_check_delegate(self, columns):
        """勾选框居中委托只挂在“选择”列，其余列一律走默认绘制。

        列重建时先清掉旧列上的委托（“选择”列位置可能变化）。
        """
        table = self.table
        for col in range(table.columnCount()):
            table.setItemDelegateForColumn(col, None)
        check_col = next((i for i, c in enumerate(columns)
                          if c.get("name") == "选择"), -1)
        if check_col < 0:
            return
        if self._check_delegate is None:
            self._check_delegate = CenteredCheckDelegate(table)
        table.setItemDelegateForColumn(check_col, self._check_delegate)

    def refresh(self):
        """
        根据搜索栏内容计算展示数据并填充表格。
        搜索栏为空时：已选（勾选）课程置顶，其余在后；
        搜索栏有内容时：只显示命中搜索语法的课程（见模块 docstring）。
        """
        columns = self.current_config.get_visible_columns()
        text = self.search_input.text().strip()
        if text:
            groups = search_logic.parse_query(text)
            if groups:
                # 用全部列（含隐藏列）做字段分类：教师姓名/工号、校区等
                # 特殊字段即使隐藏也参与搜索；普通字段仅可见时参与。
                cats = search_logic.field_categories(self.current_config.course_columns)
                self.filtered_data = [
                    c for c in self.raw_course_data
                    if search_logic.course_matches(c, groups, cats)
                ]
            else:
                # 仅含操作符/空白，无可搜词：显示全部
                self.filtered_data = list(self.raw_course_data)
        else:
            selected = [c for c in self.raw_course_data
                        if self._key(c) in self.selected_keys]
            others = [c for c in self.raw_course_data
                      if self._key(c) not in self.selected_keys]
            self.filtered_data = selected + others
        self._populate_rows(columns)

    def _populate_rows(self, columns):
        """按给定列定义从 filtered_data 填充表格行。"""
        data = self.filtered_data
        self.table.blockSignals(True)
        self.table.setRowCount(len(data))
        for row, course in enumerate(data):
            is_selected = self._key(course) in self.selected_keys
            for col, col_def in enumerate(columns):
                name = col_def.get("name", "")
                field = col_def.get("field", "")
                if name == "选择" or not field:
                    item = QTableWidgetItem()
                    item.setFlags(Qt.ItemIsUserCheckable | Qt.ItemIsEnabled | Qt.ItemIsSelectable)
                    item.setCheckState(Qt.Checked if is_selected else Qt.Unchecked)
                    item.setData(Qt.UserRole, course)  # 记录该行课程，供勾选时取回
                    item.setToolTip(self._key(course))
                else:
                    item = QTableWidgetItem(str(course.get(field, "")))
                    item.setToolTip(item.text())
                self.table.setItem(row, col, item)
        self.table.blockSignals(False)
        # 搜索过滤不改变已选集合，此处不再发 selection_changed，
        # 避免每次按键都重建整张课表造成卡顿。仅在勾选/取消与初次加载时发。

    def _on_item_changed(self, item):
        columns = self.current_config.get_visible_columns()
        col = self.table.column(item)
        if not (0 <= col < len(columns) and columns[col].get("name") == "选择"):
            return
        course = item.data(Qt.UserRole)
        if not course:
            return
        key = self._key(course)
        if not key:
            return
        if item.checkState() == Qt.Checked:
            if key not in self.selected_keys:
                self.selected_courses.append(course)
                self.selected_keys.add(key)
        else:
            self.selected_courses = [c for c in self.selected_courses
                                     if self._key(c) != key]
            self.selected_keys.discard(key)
        save_selected_courses(self._selected_file(), self.selected_courses)
        self._emit_selection()
        self.selection_toggled.emit()  # 点击勾选变化：主窗口按配置决定是否更新个人课表

    def _toggle_selected_checkstates(self):
        """空格：对当前选中行批量切换勾选状态。

        取选中行里“选择”列的勾选多数状态为基准——若选中行中已勾选者占多数
        则全部取消，否则全部勾选，行为与单行切换直觉一致。切换在 blockSignals
        下进行，最后一次性保存与发信号，避免逐行 _on_item_changed 重复写盘。
        """
        columns = self.current_config.get_visible_columns()
        check_col = next((i for i, c in enumerate(columns)
                          if c.get("name") == "选择"), -1)
        if check_col < 0:
            return
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        rows = [r for r in rows if 0 <= r < len(self.filtered_data)]
        if not rows:
            return
        items = [self.table.item(r, check_col) for r in rows]
        checked = sum(1 for it in items if it and it.checkState() == Qt.Checked)
        new_state = Qt.Unchecked if checked * 2 >= len(items) else Qt.Checked

        self.table.blockSignals(True)
        for it in items:
            if it:
                it.setCheckState(new_state)
        self.table.blockSignals(False)

        # 同步 selected_courses / selected_keys，并统一持久化与发信号
        for r in rows:
            it = self.table.item(r, check_col)
            if not it:
                continue
            course = it.data(Qt.UserRole)
            if not course:
                continue
            key = self._key(course)
            if not key:
                continue
            if new_state == Qt.Checked:
                if key not in self.selected_keys:
                    self.selected_courses.append(course)
                    self.selected_keys.add(key)
            else:
                self.selected_courses = [c for c in self.selected_courses
                                         if self._key(c) != key]
                self.selected_keys.discard(key)
        save_selected_courses(self._selected_file(), self.selected_courses)
        self._emit_selection()
        self.selection_toggled.emit()  # 空格框选完成：主窗口按配置决定是否更新个人课表

    def _emit_selection(self):
        # 发射完整课程 dict 列表，供 schedule_view 等直接使用
        self.selection_changed.emit(list(self.selected_courses))

    # ---- 复制 / 右键菜单 ----

    def _field_for(self, display_name):
        """按显示名从配置中取对应的数据字段名。"""
        for col in self.current_config.course_columns:
            if col.get("name") == display_name:
                return col.get("field", "")
        return ""

    def _copy_value(self, field, courses):
        """把给定课程的某个字段值写入剪贴板（多行用换行分隔）。"""
        text = "\n".join(str(c.get(field, "")) for c in courses if c)
        QApplication.clipboard().setText(text)

    def _copy_selected_key(self):
        """Ctrl/Cmd+C：复制当前选中行的教学班名称。"""
        rows = sorted({idx.row() for idx in self.table.selectedIndexes()})
        courses = [self.filtered_data[r] for r in rows
                   if 0 <= r < len(self.filtered_data)]
        if courses:
            self._copy_value(self._field_for("教学班") or self._key_field(),
                             courses)

    def _show_context_menu(self, pos):
        """右键菜单：复制该行的教学班名称 / 课程名称 / 课程代码。"""
        row = self.table.rowAt(pos.y())
        if row < 0 or row >= len(self.filtered_data):
            return
        course = self.filtered_data[row]
        self.table.selectRow(row)

        menu = QMenu(self)
        for label, display_name in (("复制教学班名称", "教学班"),
                                    ("复制课程名称", "课程名称"),
                                    ("复制课程代码", "课程代码")):
            field = self._field_for(display_name)
            act = QAction(label, self)
            act.triggered.connect(
                lambda checked=False, f=field: self._copy_value(f, [course]))
            menu.addAction(act)
        menu.exec(self.table.viewport().mapToGlobal(pos))
