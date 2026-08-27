from PySide6.QtWidgets import (QWidget, QHBoxLayout, QVBoxLayout, QTableWidget,
                               QHeaderView, QPushButton, QAbstractItemView,
                               QTableWidgetItem, QMenu, QApplication)
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QBrush, QColor, QAction

from config.theme import (INFO_BG_ADD, INFO_BG_DROP, INFO_BG_CONFLICT,
                          CHROME)
from data.course_loader import load_courses_from_file


class InfoPanelView(QWidget):
    settings_requested = Signal()  # 用户点击“设置”，由主窗口打开设置对话框
    sync_courses_requested = Signal()   # 用户点击“更新课程信息”，触发在线拉取课程池
    sync_schedule_requested = Signal()  # 用户点击“更新个人课表”，触发在线拉取已选课

    def __init__(self, config):
        super().__init__()
        self._config = config
        self._jiaowu_courses = []      # 教务系统已选课（list[dict]）
        self._selected_courses = []    # 本地已选课（由 selection_changed 推送）
        self._conflicts = []           # 课表冲突描述（由 schedule_view 推送）
        self._grid_width = 0           # 上方课表网格宽度（由 schedule_view 推送）
        self.init_ui()
        self._load_jiaowu()

    def init_ui(self):
        layout = self._config.layout
        margin = layout.get("margin", 10)
        main_layout = QHBoxLayout(self)
        main_layout.setContentsMargins(margin, margin, margin, margin)
        main_layout.setSpacing(layout.get("spacing", 10))

        # 信息表（左）：类型 / 课程 / 教学班名称 / 时间 / 说明
        self.info_table = QTableWidget()
        self.info_table.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.info_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.info_table.setAlternatingRowColors(False)
        self.info_table.verticalHeader().setVisible(False)
        self.info_table.setShowGrid(True)
        self.info_table.setStyleSheet(
            f"QTableWidget {{ background:{CHROME['surface']}; border:none;"
            f" gridline-color:{CHROME['gridline']}; }}"
            f"QHeaderView::section {{ background:{CHROME['header_bg']};"
            f" color:{CHROME['text']}; border:none;"
            f" border-right:1px solid {CHROME['gridline']};"
            f" border-bottom:1px solid {CHROME['gridline']};"
            f" padding:6px; font-weight:600; }}"
        )
        # 右键复制：课程 / 教学班名称 / 说明
        self.info_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.info_table.customContextMenuRequested.connect(self._show_context_menu)
        main_layout.addWidget(self.info_table, stretch=1)

        # 右侧操作按钮：固定窄宽，不抢占表格空间
        button_layout = QVBoxLayout()
        button_layout.setSpacing(layout.get("spacing", 10))
        self.settings_button = QPushButton("设置")
        self.settings_button.setFixedWidth(120)
        self.settings_button.setCursor(Qt.PointingHandCursor)
        self.settings_button.setToolTip("配置列显示等选项")
        self.settings_button.clicked.connect(self.settings_requested)
        button_layout.addWidget(self.settings_button)

        # 在线更新按钮（由主窗口的同步管理器执行，忙碌时禁用）
        self.sync_courses_button = QPushButton("更新课程信息")
        self.sync_courses_button.setFixedWidth(120)
        self.sync_courses_button.setCursor(Qt.PointingHandCursor)
        self.sync_courses_button.setToolTip("从教务系统拉取全量课程信息（约 2 分钟）")
        self.sync_courses_button.clicked.connect(self.sync_courses_requested)
        button_layout.addWidget(self.sync_courses_button)

        self.sync_schedule_button = QPushButton("更新个人课表")
        self.sync_schedule_button.setFixedWidth(120)
        self.sync_schedule_button.setCursor(Qt.PointingHandCursor)
        self.sync_schedule_button.setToolTip("从教务系统拉取个人已选课，刷新补选/退选对比")
        self.sync_schedule_button.clicked.connect(self.sync_schedule_requested)
        button_layout.addWidget(self.sync_schedule_button)

        button_layout.addStretch()
        main_layout.addLayout(button_layout)

        self._apply_table_metrics()

    # ---- 由配置派生 ----

    def _jiaowu_file(self):
        return self._config.files.get("jiaowu_courses", "jiaowu_course.json")

    def _key_field(self):
        return self._config.course.get("key_field", "jxbmc")

    def _key(self, course):
        return course.get(self._key_field(), "")

    def _name(self, course):
        return course.get("kcmc", "") or course.get("jxbmc", "") or "课程"

    def _jxb(self, course):
        return course.get("jxbmc", "")

    def _time(self, course):
        return course.get("sksj", "") or "未排课"

    # ---- 表格结构（列宽 / 行高 / 最大宽度）----

    def _apply_table_metrics(self):
        """按 info_table 配置重建列、列宽、行高与最大宽度。"""
        cols = self._config.info_columns()
        header = self.info_table.horizontalHeader()
        self.info_table.setColumnCount(len(cols))
        self.info_table.setHorizontalHeaderLabels([c.get("name", "") for c in cols])
        for i, col in enumerate(cols):
            width = col.get("width", 0)
            if width and width > 0:
                header.setSectionResizeMode(i, QHeaderView.Interactive)
                self.info_table.setColumnWidth(i, width)
            else:
                # width<=0：自适应拉伸填满剩余宽度
                header.setSectionResizeMode(i, QHeaderView.Stretch)
        # 行高：固定
        vh = self.info_table.verticalHeader()
        h = self._config.info_row_height()
        vh.setSectionResizeMode(QHeaderView.Fixed)
        vh.setDefaultSectionSize(h)
        self._apply_max_width()

    def _apply_max_width(self):
        """整表最大宽度策略：
        max_width > 0：固定上限（px）；
        max_width == -1：跟随上方课表网格宽度对齐；
        max_width == 0（默认）：自适应，不限宽，填满左侧可用空间。
        """
        mw = self._config.info_max_width()
        if mw and mw > 0:
            self.info_table.setMaximumWidth(mw)
        elif mw == -1 and self._grid_width and self._grid_width > 0:
            self.info_table.setMaximumWidth(self._grid_width)
        else:
            # 自适应：恢复默认巨大上限
            self.info_table.setMaximumWidth(16777215)

    def set_table_max_width(self, grid_width):
        """由 schedule_view 推送上方课表网格宽度（仅在 max_width=-1 时生效）。"""
        self._grid_width = grid_width or 0
        self._apply_max_width()

    def apply_config(self, config):
        """配置变更后重建列结构与度量并重算对比。"""
        self._config = config
        self._load_jiaowu()
        self._apply_table_metrics()
        self._render_table()

    def set_sync_busy(self, busy: bool):
        """在线拉取进行中：禁用两个更新按钮，避免重复触发。"""
        self.sync_courses_button.setEnabled(not busy)
        self.sync_schedule_button.setEnabled(not busy)

    # ---- 数据来源 ----

    def _load_jiaowu(self):
        """从教务系统已选课 JSON 加载。文件小，同步读取即可。"""
        self._jiaowu_courses = load_courses_from_file(self._jiaowu_file())

    def reload_jiaowu(self):
        """重新加载教务已选课（如文件被外部更新）并刷新表格。"""
        self._load_jiaowu()
        self._render_table()

    # ---- 由信号推送 ----

    def update_courses(self, courses):
        """本地已选课变化（selection_changed）：重算补/退选并刷新。"""
        self._selected_courses = list(courses)
        self._render_table()

    def update_conflicts(self, conflicts):
        """课表冲突变化（schedule_view.conflicts_changed）：刷新冲突行。"""
        self._conflicts = list(conflicts)
        self._render_table()

    # ---- 对比与渲染 ----

    def _build_rows(self):
        """汇总三类行，每行含底色 + 源课程（供取字段与复制）。

        补选（淡绿）：本地已选、教务未选 -> 需在教务系统补选。
        退选（淡黄）：教务已选、本地未选 -> 需在教务系统退选。
        冲突（淡红）：课表检测到时间冲突。
        列文本由 _render_table 按 info_table.columns 的 field 逐列取值。
        """
        rows = []

        jiaowu_keys = {self._key(c) for c in self._jiaowu_courses}
        selected_keys = {self._key(c) for c in self._selected_courses}

        def row(kind, course, jxb, time, note, bg, courses):
            return {"kind": kind, "course": course, "jxb": jxb,
                    "time": time, "note": note, "bg": bg, "courses": courses}

        # 补选：本地已选但教务系统没有
        for c in self._selected_courses:
            if self._key(c) not in jiaowu_keys:
                rows.append(row("补选", self._name(c), self._jxb(c),
                                self._time(c), "需补选",
                                INFO_BG_ADD, [c]))
        # 退选：教务已选但本地未选
        for c in self._jiaowu_courses:
            if self._key(c) not in selected_keys:
                rows.append(row("退选", self._name(c), self._jxb(c),
                                self._time(c), "需退选",
                                INFO_BG_DROP, [c]))

        # 冲突：课程名后附教学班名称，说明从简
        for desc in self._conflicts:
            courses = desc.get("courses", [])
            names = "、".join(self._name(c) for c in courses) or "课程"
            jxbs = "、".join(self._jxb(c) for c in courses)
            pairs = "、".join(f"{self._name(c)}({self._jxb(c)})"
                             for c in courses) or "课程"
            overlap = desc.get("overlap", "无")
            note = (f"{pairs} {overlap}冲突"
                    if overlap and overlap != "无"
                    else f"{pairs} 时间冲突")
            rows.append(row("冲突", names, jxbs, desc.get("time", ""),
                            note, INFO_BG_CONFLICT, list(courses)))

        return rows

    def _computed_col_indices(self):
        """空 field 列为计算列：第一个是“类型”，最后一个（若有多个）是“说明”。"""
        empty = [i for i, c in enumerate(self._config.info_columns())
                 if not c.get("field")]
        kind = empty[0] if empty else -1
        note = empty[-1] if len(empty) > 1 else -1
        return kind, note

    def _cell_text(self, field, rd):
        """按列 field 取单元格文本：内置字段映射到行数据，其余查源课程 dict。"""
        if field == "kcmc":
            return rd["course"]
        if field == "jxbmc":
            return rd["jxb"]
        if field == "sksj":
            return rd["time"]
        # 其他字段（如 jxbrl / fcxxkrs）：取源课程字段值，
        # 多门课（冲突行）去重后换行拼接
        return self._join(rd["courses"], field)

    def _render_table(self):
        rows = self._build_rows()
        cols = self._config.info_columns()
        kind_col, note_col = self._computed_col_indices()
        h = self._config.info_row_height()
        self.info_table.setRowCount(len(rows))
        for r, rd in enumerate(rows):
            brush = QBrush(QColor(rd["bg"]))
            for col, c in enumerate(cols):
                if col == kind_col:
                    text = rd["kind"]
                elif col == note_col:
                    text = rd["note"]
                else:
                    text = self._cell_text(c.get("field", ""), rd)
                item = QTableWidgetItem(text)
                item.setTextAlignment(Qt.AlignLeft | Qt.AlignVCenter)
                item.setBackground(brush)
                # 鼠标悬停显示完整内容（含被截断部分）
                item.setToolTip(text)
                # 第 0 列记录源课程与说明，供右键复制
                if col == 0:
                    item.setData(Qt.UserRole,
                                 {"courses": rd["courses"], "note": rd["note"]})
                self.info_table.setItem(r, col, item)
            self.info_table.setRowHeight(r, h)

    # ---- 右键复制：课程 / 教学班名称 / 说明 ----

    def _row_courses(self, row):
        item = self.info_table.item(row, 0)
        if item is None:
            return [], ""
        data = item.data(Qt.UserRole) or {}
        return data.get("courses", []), data.get("note", "")

    def _show_context_menu(self, pos):
        row = self.info_table.rowAt(pos.y())
        if row < 0:
            return
        courses, note = self._row_courses(row)
        if not courses and not note:
            return
        self.info_table.selectRow(row)

        menu = QMenu(self)
        for label, text in (("复制课程名称", self._join(courses, "kcmc")),
                            ("复制教学班名称", self._join(courses, "jxbmc")),
                            ("复制说明", note)):
            act = QAction(label, menu)
            act.triggered.connect(
                lambda _=False, t=text: self._copy(t))
            if not text:
                act.setEnabled(False)
            menu.addAction(act)
        menu.exec(self.info_table.viewport().mapToGlobal(pos))

    @staticmethod
    def _join(courses, field):
        """多门课的某字段去重后换行拼接（教学班名称唯一，作 id 去重）。"""
        seen, out = set(), []
        for c in courses:
            v = str(c.get(field, "") or "")
            if not v or v in seen:
                continue
            seen.add(v)
            out.append(v)
        return "\n".join(out)

    @staticmethod
    def _copy(text):
        if text:
            QApplication.clipboard().setText(str(text))
