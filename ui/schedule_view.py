import logging

from PySide6.QtCore import QObject, QPoint, Qt, QThread, Signal
from PySide6.QtGui import QAction, QColor, QImage, QPainter
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QHBoxLayout,
                               QHeaderView, QLabel, QMenu, QPushButton,
                               QSizePolicy, QTableWidget, QTableWidgetItem,
                               QVBoxLayout, QWidget)

from config.theme import (CHROME, COURSE_COLORS, SEGMENT_RE, item_sep)

logger = logging.getLogger(__name__)


def _to_float(value):
    """xf 学分字段以字符串存储（如 '2.0'），安全转 float。"""
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _expand_periods(period_str):
    """'1-2,8-9' -> [(1,2),(8,9)]，合并相邻段为连续区间。"""
    runs = []
    for part in period_str.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-")
            runs.append((int(a), int(b)))
        else:
            n = int(part)
            runs.append((n, n))
    runs.sort()
    merged = []
    for s, e in runs:
        if merged and s <= merged[-1][1] + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], e))
        else:
            merged.append((s, e))
    return merged


def _expand_weeks(week_str):
    """周次串 -> 周次集合（1..N）。

    支持：1-17周 / 1-17周(单) / 2-16周(双) / 4周,10周 / 1-2周,8-9周 /
    2周,6-8周(双),12-16周(双) 等组合。
    """
    weeks = set()
    for part in week_str.split(","):
        part = part.strip()
        if not part:
            continue
        odd = "(单)" in part
        even = "(双)" in part
        part = part.replace("(单)", "").replace("(双)", "").replace("周", "").strip()
        if "-" in part:
            a, b = part.split("-")
            a, b = int(a), int(b)
            for w in range(a, b + 1):
                if odd and w % 2 == 0:
                    continue
                if even and w % 2 == 1:
                    continue
                weeks.add(w)
        else:
            w = int(part)
            if odd and w % 2 == 0:
                continue
            if even and w % 2 == 1:
                continue
            weeks.add(w)
    return weeks


def _runs_of(weeks):
    """有序周次集合 -> [(s,e)] 连续区间。"""
    if not weeks:
        return []
    seq = sorted(weeks)
    runs = []
    for w in seq:
        if runs and w == runs[-1][1] + 1:
            runs[-1][1] = w
        else:
            runs.append([w, w])
    return [(s, e) for s, e in runs]


def _compress_weeks(weeks):
    """周次集合 -> '1-6周' / '4,10周' / '无'。"""
    runs = _runs_of(weeks)
    if not runs:
        return "无"
    parts = [str(s) if s == e else f"{s}-{e}" for s, e in runs]
    return ",".join(parts) + "周"


def _esc(text):
    """HTML 转义。"""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _segment_locations(jxdd):
    """jxdd 与 sksj 的 ';' 段一一对应；无值时返回空列表。"""
    if not jxdd:
        return []
    return [p.strip() for p in str(jxdd).split(";")]


def _format_locs(locs):
    """[(loc, weeks)] -> 'A' 或 'A(1-9周) / B(10-17周)'。"""
    uniq = []
    for loc, w in locs:
        if loc and not any(loc == u[0] for u in uniq):
            uniq.append((loc, w))
    if not uniq:
        return ""
    if len(uniq) == 1:
        return _esc(uniq[0][0])
    return " / ".join(f"{_esc(loc)}({_compress_weeks(w)})" for loc, w in uniq)


class _Item:
    """格内一门课程：可能由多个同节次段合并而来（周次并集、多地点）。"""

    __slots__ = ("course", "weeks", "locs", "color")

    def __init__(self, course, weeks, loc, color):
        self.course = course
        self.weeks = set(weeks)
        self.locs = [(loc, set(weeks))]
        self.color = color


class _Cell:
    """课表一个占用格：连续节次区间 + 涉及的课程项 + 是否冲突。"""

    __slots__ = ("start", "end", "items", "conflicted")

    def __init__(self, start, end, item):
        self.start = start
        self.end = end
        self.items = [item]
        self.conflicted = False

    def overlap(self, other):
        return self.start <= other.end and other.start <= self.end


def _has_conflict(items):
    """不同课程且周次相交才算冲突。同门课不同地点/周次不算。"""
    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if items[i].course is not items[j].course:
                if items[i].weeks & items[j].weeks:
                    return True
    return False


def _build_day_cells(raw):
    """同一天 -> list[_Cell]。

    先按课程合并同节次重叠的段（周次并集、地点分段标注），再跨课程按节次
    合并成格；仅当不同课程且周次相交才判为冲突。
    """
    # 1. 按课程分组，合并该课程内节次重叠的段
    by_course = {}
    for (s, e, weeks, loc, course, color) in raw:
        by_course.setdefault(id(course), []).append(
            (s, e, weeks, loc, course, color))
    cells = []
    for clist in by_course.values():
        clist.sort(key=lambda x: x[0])
        cur = None
        for (s, e, weeks, loc, course, color) in clist:
            if cur is not None and s <= cur.end:  # 节次重叠 -> 同课合并
                cur.end = max(cur.end, e)
                it = cur.items[0]
                it.weeks |= weeks
                it.locs.append((loc, weeks))
            else:
                cur = _Cell(s, e, _Item(course, weeks, loc, color))
                cells.append(cur)
    # 2. 跨课程按节次合并成同一格（共享节次槽）
    cells.sort(key=lambda c: c.start)
    merged = []
    for c in cells:
        if merged and merged[-1].overlap(c):
            top = merged[-1]
            top.end = max(top.end, c.end)
            top.items.extend(c.items)
        else:
            merged.append(_Cell(c.start, c.end, c.items[0]))
    # 3. 冲突判定
    for c in merged:
        c.conflicted = _has_conflict(c.items)
    return merged


def _cell_bg(cell):
    return (CHROME["conflict_bg"] if cell.conflicted
            else cell.items[0].color[0])


class ScheduleView(QWidget):
    """课表视图：顶部为已选学分统计栏，下方为周课表网格。"""

    conflicts_changed = Signal(list)  # 冲突描述列表，供 infopanel 用淡红行展示
    grid_width_changed = Signal(int)  # 课表网格总宽，供 infopanel 对齐最大宽度
    export_started = Signal()  # 开始导出课表（主窗口借此先更新个人课表）

    def __init__(self, config):
        super().__init__()
        self._config = config
        sched = config.schedule
        # 由配置派生的课表结构（运行时只读快照）
        self._weekdays = list(sched.get("weekdays", []))
        self._weekday_index = {name: i for i, name in enumerate(self._weekdays)}
        self._period_times = config.period_times()
        self._total_weeks = sched.get("total_weeks", 0)
        self._weekday_always = config.weekday_always()
        self._practice_loc = sched.get("practice_location", "")
        self._credit_limit = sched.get("credit_limit", 0)  # 0 表示不启用上限
        layout = config.layout
        self._margin = layout.get("margin", 10)
        self._spacing = layout.get("spacing", 10)
        self._scroll_pad = layout.get("scroll_pad", 0)

        self._credits = 0.0
        self._count = 0
        self._courses = []
        self._layout = {}          # day_index -> [merged _Cell]
        self._visible_days = []    # 实际显示的星期列下标
        self._conflicts = 0
        self._export_thread = None  # 后台 PNG 编码线程（退出前需 wait）
        self._export_worker = None
        self.init_ui()

    # ---- UI ----

    def init_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(self._margin, self._margin,
                                  self._margin, self._margin)
        layout.setSpacing(self._spacing)

        self.stats_bar = self._create_stats_bar()
        layout.addWidget(self.stats_bar)

        self.timetable = self._create_timetable()
        layout.addWidget(self.timetable, stretch=1)

        self._build_layout()        # 初始化空网格：显示工作日列并限定左栏宽度
        self._render_stats()
        self._render_timetable()

    def _create_stats_bar(self):
        bar = QFrame()
        bar.setStyleSheet(
            f"QFrame {{ background-color: {CHROME['surface']}; border: 0px; }}")
        bar.setFixedHeight(34)
        self._stats_layout = QHBoxLayout(bar)
        self._stats_layout.setContentsMargins(10, 4, 10, 4)
        self._stats_layout.setSpacing(24)

        self.label_credits = QLabel()
        self.label_credits.setStyleSheet(
            f"color:{CHROME['text']}; border:none;")
        self.label_count = QLabel()
        self.label_count.setStyleSheet(
            f"color:{CHROME['text']}; border:none;")
        self.label_conflicts = QLabel()
        self.label_conflicts.setStyleSheet("border:none;")
        self.label_conflicts.setVisible(False)
        self.label_credit_over = QLabel()
        self.label_credit_over.setStyleSheet("border:none;")
        self.label_credit_over.setVisible(False)
        self._stats_layout.addWidget(self.label_credits)
        self._stats_layout.addWidget(self.label_count)
        self._stats_layout.addWidget(self.label_conflicts)
        self._stats_layout.addStretch()
        self._stats_layout.addWidget(self.label_credit_over)

        self.export_button = QPushButton("导出课表")
        self.export_button.setCursor(Qt.PointingHandCursor)
        self.export_button.setStyleSheet(
            f"QPushButton {{ background:{CHROME['text']};"
            f" color:{CHROME['surface']}; border:none;"
            f" border-radius:6px; padding:6px 16px; font-size:12px; }}"
            f"QPushButton:hover {{ background:{CHROME['text_hover']}; }}"
        )
        self.export_button.clicked.connect(self._export)
        self._stats_layout.addWidget(self.export_button)
        return bar

    def _create_timetable(self):
        table = QTableWidget()
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.setSelectionMode(QTableWidget.NoSelection)
        table.setFocusPolicy(Qt.NoFocus)
        table.setAlternatingRowColors(False)
        table.setShowGrid(True)
        table.horizontalHeader().setVisible(True)
        table.verticalHeader().setVisible(False)

        # 固定格子大小：节次列窄、每天列固定宽，行高固定
        table.setColumnCount(1 + len(self._weekdays))
        table.setHorizontalHeaderLabels(
            ["节次"] + [d.replace("星期", "周") for d in self._weekdays])
        table.horizontalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.horizontalHeader().setDefaultAlignment(Qt.AlignCenter)
        table.setColumnWidth(0, 64)
        for c in range(1, 1 + len(self._weekdays)):
            table.setColumnWidth(c, 130)

        table.verticalHeader().setSectionResizeMode(QHeaderView.Fixed)
        table.verticalHeader().setDefaultSectionSize(80)

        table.setRowCount(len(self._period_times))
        self._fill_period_column(table)

        table.setStyleSheet(
            f"QTableWidget {{ gridline-color:{CHROME['gridline']};"
            f" background:{CHROME['surface']}; border:none; }}"
            "QTableWidget::item { padding:2px; }"
            f"QHeaderView::section {{ background:{CHROME['header_bg']};"
            f" color:{CHROME['text']};"
            f" border:none; border-right:1px solid {CHROME['gridline']};"
            f" border-bottom:1px solid {CHROME['gridline']};"
            f" padding:6px; font-weight:600; }}"
        )
        table.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

        # 右键复制课程信息
        table.setContextMenuPolicy(Qt.CustomContextMenu)
        table.customContextMenuRequested.connect(self._show_cell_menu)
        return table

    def _fill_period_column(self, table):
        for p, (start, end) in self._period_times.items():
            item = QTableWidgetItem(f"{p}\n{start}\n{end}")
            item.setTextAlignment(Qt.AlignCenter)
            # 固定色值，不取系统调色板：QPalette.Mid 在 Linux GTK 主题下
            # 是接近边框的浅灰，白底上几乎不可见（macOS 正常，Ubuntu 复现）
            item.setForeground(QColor(CHROME["muted"]))
            item.setFlags(Qt.NoItemFlags)
            table.setItem(p - 1, 0, item)

    # ---- 富文本（需读 config/theme，故为实例方法）----

    def _free_chips(self, weeks):
        """空闲周次 -> 彩色底色标签 HTML；无空闲时显示弱化的'无'。"""
        free = set(range(1, self._total_weeks + 1)) - weeks
        if not free:
            return f"<span style='color:{CHROME['none_fg']};'>无</span>"
        chips = []
        for s, e in _runs_of(free):
            label = str(s) if s == e else f"{s}-{e}"
            chips.append(
                f"<span style='background-color:{CHROME['free_chip_bg']};"
                f" color:{CHROME['free_chip_fg']};'>{label}周</span>")
        return " ".join(chips)

    def _item_html(self, item):
        """单个课程项的富文本。

        顺序：空闲周标签（最上方） -> 课程名 -> 教师 -> 教学班 -> 地点。
        """
        course = item.course
        fg = item.color[1]
        name = _esc(course.get("kcmc", ""))
        teacher = _esc(course.get("jsmc", ""))
        jxb = _esc(course.get("jxbmc", ""))
        loc = _format_locs(item.locs)
        # 免听标记：课程名旁的小标签，提示该课周次按空闲处理
        audit = ""
        if str(course.get("zxbj", "")).strip() == "是":
            audit = (f"<span style='background-color:"
                     f"{CHROME['audit_chip_bg']}; color:"
                     f"{CHROME['audit_chip_fg']};'>免听</span> ")
        return (
            f"<div style='color:{fg};'>"
            f"<div style='font-size:10px; margin-bottom:3px;'>"
            f"空闲周：{self._free_chips(item.weeks)}</div>"
            f"<div style='font-weight:700; font-size:13px;'>{audit}{name}</div>"
            f"<div style='font-size:11px;'>{teacher}</div>"
            f"<div style='font-size:11px; opacity:0.85;'>{jxb}</div>"
            f"<div style='font-size:11px; opacity:0.8;'>{loc}</div>"
            f"</div>"
        )

    def _cell_html(self, cell):
        """整格内容：多课程项以分隔线串联，冲突时加警示横幅。"""
        inner = item_sep().join(self._item_html(it) for it in cell.items)
        if cell.conflicted:
            banner = (f"<div style='color:{CHROME['conflict_fg']};"
                      f" font-weight:700;"
                      f" font-size:11px; margin-bottom:2px;'>⚠ 时间冲突</div>")
            return banner + inner
        return inner

    def _parse_raw(self, course, color):
        """一门课的 sksj/jxdd -> list[(day, start, end, weeks, loc, course, color)]。

        sksj 以 ';' 分段，jxdd 同样以 ';' 分段且按顺序一一对应；
        单段内的多个节次区间（如 1-2,8-9）共享该段地点。
        """
        # 免听标记（个人课表 API 字段 zxbj=“是”）：课仍显示在课表，但
        # 周次按空闲处理——占用集为空集，故不与任何课判冲突，其格子的
        # 空闲周标签也显示全部周次
        audit = str(course.get("zxbj", "")).strip() == "是"
        sksj = course.get("sksj", "") or ""
        segments = [s.strip() for s in sksj.split(";") if s.strip()]
        locations = _segment_locations(course.get("jxdd", ""))

        out = []
        for i, seg in enumerate(segments):
            m = SEGMENT_RE.search(seg)
            if not m:
                continue
            day_name = "星期" + m.group(1)
            if day_name not in self._weekday_index:
                continue
            day = self._weekday_index[day_name]
            runs = _expand_periods(m.group(2))
            weeks = set() if audit else _expand_weeks(m.group(3))
            # 该段地点：按下标取；段数多于地点数时回退到首个/空
            if i < len(locations):
                loc = locations[i]
            elif locations:
                loc = locations[0]
            else:
                loc = ""
            # 课外实践不在教室：该段周次按空闲处理，不占用本格
            if loc.strip() == self._practice_loc:
                continue
            if not runs:
                continue
            for (s, e) in runs:
                out.append((day, s, e, weeks, loc, course, color))
        return out

    # ---- 数据更新 ----

    def update_courses(self, courses):
        """根据已选课程列表刷新学分统计与课表网格。由 selection_changed 触发。"""
        self._courses = list(courses)
        self._count = len(courses)
        self._credits = sum(_to_float(c.get("xf")) for c in courses if c)
        self._build_layout()
        self._render_stats()
        self._render_timetable()
        self.conflicts_changed.emit(self._build_conflict_report())

    def _build_conflict_report(self):
        """遍历当前课表的冲突格 -> 冲突描述列表。

        每项：{"courses": [课程dict...], "time": "星期X 第a-b节", "overlap": "1-6周"}
        overlap 为冲突涉及的周次并集（已压缩），无交集时为 "无"。
        """
        report = []
        for day, blocks in self._layout.items():
            for blk in blocks:
                if not blk.conflicted:
                    continue
                # 去重参与课程（同一课程不同地点/周次只取一次）
                courses = []
                weeks_by_course = []
                for it in blk.items:
                    if not any(it.course is c for c in courses):
                        courses.append(it.course)
                        weeks_by_course.append(set(it.weeks))
                    else:
                        for i, c in enumerate(courses):
                            if it.course is c:
                                weeks_by_course[i] |= it.weeks
                # 冲突周次 = 任意两门课的周次交集之并
                overlap = set()
                for i in range(len(weeks_by_course)):
                    for j in range(i + 1, len(weeks_by_course)):
                        overlap |= weeks_by_course[i] & weeks_by_course[j]
                day_name = self._weekdays[day] if 0 <= day < len(self._weekdays) else ""
                periods = (str(blk.start) if blk.start == blk.end
                           else f"{blk.start}-{blk.end}")
                report.append({
                    "courses": courses,
                    "time": f"{day_name} 第{periods}节",
                    "overlap": _compress_weeks(overlap),
                })
        return report

    def _render_stats(self):
        credits_text = (f"{self._credits:.0f}"
                        if self._credits.is_integer() else f"{self._credits:.2f}")
        self.label_credits.setText(
            f"<b style=\"font-size:16px;\">{credits_text}</b>"
            f"<span style=\"color:{CHROME['muted']}; font-size:12px;\"> 学分</span>")
        # 超出上限：右侧红色警示（风格同时间冲突）；limit<=0 时不启用
        limit = self._credit_limit
        if limit and self._credits > limit:
            excess = self._credits - limit
            excess_text = (f"{excess:.0f}" if excess.is_integer()
                           else f"{excess:.2f}")
            self.label_credit_over.setText(
                f"<b style=\"font-size:12px; color:{CHROME['conflict_fg']};\">"
                f"⚠ 超出学分上限 {excess_text} 学分</b>")
            self.label_credit_over.setVisible(True)
        else:
            self.label_credit_over.setVisible(False)
        self.label_count.setText(
            f"<b style=\"font-size:16px;\">{self._count}</b>"
            f"<span style=\"color:{CHROME['muted']}; font-size:12px;\"> 门课程</span>")
        if self._conflicts > 0:
            self.label_conflicts.setText(
                f"<b style=\"font-size:12px; color:{CHROME['conflict_fg']};\">"
                f"⚠ {self._conflicts} 处时间冲突</b>")
            self.label_conflicts.setVisible(True)
        else:
            self.label_conflicts.setVisible(False)

    def _build_layout(self):
        """解析当前已选课程 -> (by_day cells, visible_days, conflicts)。"""
        raw_by_day = {i: [] for i in range(len(self._weekdays))}
        for idx, course in enumerate(self._courses):
            color = COURSE_COLORS[idx % len(COURSE_COLORS)]
            for day, s, e, weeks, loc, c, col in self._parse_raw(course, color):
                raw_by_day[day].append((s, e, weeks, loc, c, col))

        self._layout = {d: _build_day_cells(raw) for d, raw in raw_by_day.items()}

        # 实际占用的星期：工作日恒显示，周末仅在有课时显示
        used = {d for d, blocks in self._layout.items() if blocks}
        self._visible_days = [
            d for d in range(len(self._weekdays))
            if d in self._weekday_always or d in used
        ]

        self._conflicts = sum(
            1 for blocks in self._layout.values()
            for blk in blocks if blk.conflicted)

    def _render_timetable(self):
        table = self.timetable
        # 清空旧内容与合并（重建行数以丢弃旧 span）
        for r in range(table.rowCount()):
            for c in range(1, table.columnCount()):
                if table.cellWidget(r, c) is not None:
                    table.removeCellWidget(r, c)
                if table.item(r, c) is not None:
                    table.takeItem(r, c)
        table.setRowCount(0)
        table.setRowCount(len(self._period_times))
        self._fill_period_column(table)

        # 隐藏无课的周末列
        for d in range(len(self._weekdays)):
            table.setColumnHidden(d + 1, d not in self._visible_days)

        for day in self._visible_days:
            col = day + 1
            for blk in self._layout.get(day, []):
                row = blk.start - 1
                span = blk.end - blk.start + 1
                if span < 1:
                    continue
                table.setSpan(row, col, span, 1)
                label = QLabel(self._cell_html(blk))
                label.setWordWrap(True)
                label.setAlignment(Qt.AlignLeft | Qt.AlignTop)
                label.setStyleSheet(
                    f"QLabel {{ background-color:{_cell_bg(blk)};"
                    f" border-radius:4px; padding:4px; }}"
                )
                table.setCellWidget(row, col, label)

        # 左栏最大宽度：不超过表格实际所需宽度 + 留白 + 滚动条预留，
        # 避免左半部分超出表格边界、把多余空间留给右侧课程表
        full = sum(table.columnWidth(c)
                   for c in range(table.columnCount())
                   if not table.isColumnHidden(c))
        self.setMaximumWidth(full + 2 * self._margin + self._scroll_pad)
        self._grid_width = full
        self.grid_width_changed.emit(full)
        self._update_stats_margins()

    def _update_stats_margins(self):
        """让导出按钮右缘对齐表格网格右缘。

        统计栏撑满布局宽度，但表格网格常窄于控件（固定列宽 + 滚动条预留会
        在右侧留白）。按钮若贴统计栏右缘就会越过网格右缘。这里按当前网格
        宽度动态加大统计栏右边距，把按钮收回到网格右缘以内。
        """
        grid_w = getattr(self, "_grid_width", 0)
        if grid_w <= 0 or not hasattr(self, "_stats_layout"):
            return
        # button 右缘 = stats_bar.right - R；网格右缘 = self._margin + grid_w
        # stats_bar.right = self.width() - self._margin（栏撑满布局）
        # => R = self.width() - 2*self._margin - grid_w
        right = self.width() - 2 * self._margin - grid_w
        right = max(right, 10)  # 至少保留原有内边距
        self._stats_layout.setContentsMargins(10, 4, right, 4)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_stats_margins()

    # ---- 右键复制 ----

    def _block_at(self, day, period):
        for blk in self._layout.get(day, []):
            if blk.start <= period <= blk.end:
                return blk
        return None

    def _show_cell_menu(self, pos):
        idx = self.timetable.indexAt(pos)
        if not idx.isValid():
            return
        row, col = idx.row(), idx.column()
        if col < 1:
            return
        blk = self._block_at(col - 1, row + 1)
        if not blk:
            return

        courses = [it.course for it in blk.items]
        menu = QMenu(self)
        multi = len(courses) > 1
        for course in courses:
            name = course.get("kcmc", "") or course.get("jxbmc", "") or "课程"
            prefix = f"[{name}] " if multi else ""
            a_name = QAction(f"{prefix}复制课程名称", menu)
            a_name.triggered.connect(
                lambda _=False, c=course: self._copy(c.get("kcmc", "")))
            a_jxb = QAction(f"{prefix}复制教学班名称", menu)
            a_jxb.triggered.connect(
                lambda _=False, c=course: self._copy(c.get("jxbmc", "")))
            a_both = QAction(f"{prefix}复制课程名 / 教学班", menu)
            a_both.triggered.connect(
                lambda _=False, c=course: self._copy(
                    f"{c.get('kcmc', '')}\t{c.get('jxbmc', '')}"))
            
            menu.addAction(a_name)
            menu.addAction(a_jxb)
            menu.addAction(a_both)

            if multi:
                menu.addSeparator()

        if multi:
            a_all = QAction("复制全部（课程名 / 教学班）", menu)
            a_all.triggered.connect(lambda _=False: self._copy(
                "\n".join(f"{c.get('kcmc', '')}\t{c.get('jxbmc', '')}"
                          for c in courses)))
            menu.addAction(a_all)

        menu.exec(self.timetable.viewport().mapToGlobal(pos))

    @staticmethod
    def _copy(text):
        if text:
            QApplication.clipboard().setText(str(text))

    # ---- 导出（PNG，直接渲染 QTableWidget）----

    def _stop_export(self):
        """窗口关闭时确保编码线程结束，避免 QThread 析构时仍运行导致崩溃。
        线程结束后 finished -> deleteLater 可能已删掉 C++ 对象，此时 Python
        侧仍持有失效包装器，调用任意方法会抛 RuntimeError，需安全处理。
        """
        thread = self._export_thread
        if thread is None:
            return
        try:
            running = thread.isRunning()
        except RuntimeError:
            self._export_thread = None
            self._export_worker = None
            return
        if not running:
            self._export_thread = None
            self._export_worker = None
            return
        # 断开完成回调，防止在已销毁的控件上更新 UI
        if self._export_worker is not None:
            try:
                self._export_worker.finished.disconnect()
            except RuntimeError:
                pass
        thread.quit()
        thread.wait(10000)
        self._export_thread = None
        self._export_worker = None


    def _set_export_status(self, busy: bool, hint: str):
        """
        通过主窗口常驻状态栏反馈导出进度与提示。
        导出渲染在主线程会短暂阻塞，调用前先 processEvents 让进度条/提示立即绘制。
        """
        win = self.window()
        if hasattr(win, "set_progress_busy"):
            win.set_progress_busy(busy)
        if hasattr(win, "set_hint"):
            win.set_hint(hint)
        QApplication.processEvents()

    def _export(self):
        if not self._courses:
            return
        # 导出前触发一次个人课表在线更新（由主窗口异步执行，不阻塞导出）
        self.export_started.emit()
        path, _ = QFileDialog.getSaveFileName(
            self, "导出课表", "课表.png", "PNG 图片 (*.png)")
        if not path:
            return
        if not path.lower().endswith(".png"):
            path += ".png"
        # 立即反馈：渲染在主线程会短暂阻塞，先显示进度条与提示
        self._set_export_status(True, "正在导出…")
        # GUI 线程渲染高分辨率位图（触及 QTableWidget，必须在主线程）
        image = self._render_to_image(self._config.export.get("scale", 1))
        if image.isNull():
            self._set_export_status(False, "导出失败：无法渲染")
            return
        self._start_export(image, path)

    def _start_export(self, image, path):
        """在后台线程完成 PNG 编码，避免阻塞 UI。进度条保持不确定模式。"""
        self.export_button.setEnabled(False)
        self.export_button.setText("导出中…")
        self._export_worker = _ExportWorker(image, path)
        self._export_thread = QThread()
        self._export_worker.moveToThread(self._export_thread)
        self._export_thread.started.connect(self._export_worker.run)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.finished.connect(self._export_thread.quit)
        self._export_thread.finished.connect(self._export_thread.deleteLater)
        self._export_thread.finished.connect(self._export_worker.deleteLater)
        self._export_thread.start()

    def _on_export_done(self, path):
        self.export_button.setEnabled(True)
        self.export_button.setText("导出课表")
        self._set_export_status(False, "已导出：" + path if path else "导出失败")

    # ---- 表格 -> 高分辨率 QImage ----

    def _full_content_size(self):
        table = self.timetable
        cols = [c for c in range(table.columnCount())
                if not table.isColumnHidden(c)]
        hh = table.horizontalHeader()
        full_w = sum(table.columnWidth(c) for c in cols)
        full_h = hh.height() + sum(table.rowHeight(r)
                                    for r in range(table.rowCount()))
        return full_w, full_h

    def _render_to_image(self, scale):
        """以 scale 倍超采样渲染整张课表（含表头与合并格）为 QImage。"""
        full_w, full_h = self._full_content_size()
        if full_w <= 0 or full_h <= 0:
            return QImage()
        image = QImage(full_w * scale, full_h * scale,
                       QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.white)
        painter = QPainter(image)
        painter.setRenderHint(QPainter.Antialiasing, True)
        painter.setRenderHint(QPainter.TextAntialiasing, True)
        painter.scale(scale, scale)
        self._render_table_into(painter)
        painter.end()
        return image

    def _render_table_into(self, painter):
        """暂时撑开表格、关掉滚动条，使 viewport 露出全部内容再渲染到 painter。"""
        table = self.timetable
        full_w, full_h = self._full_content_size()
        layout = self.layout()
        hsb = table.horizontalScrollBarPolicy()
        vsb = table.verticalScrollBarPolicy()
        old_size = table.size()
        table.setUpdatesEnabled(False)
        table.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        table.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        if layout is not None:
            layout.setEnabled(False)
        table.resize(full_w, full_h)
        table.setUpdatesEnabled(True)
        table.viewport().repaint()
        table.render(painter, QPoint(0, 0))
        # 还原
        table.resize(old_size)
        table.setHorizontalScrollBarPolicy(hsb)
        table.setVerticalScrollBarPolicy(vsb)
        if layout is not None:
            layout.setEnabled(True)


class _ExportWorker(QObject):
    """后台 PNG 编码（不触及 widget，可安全在工作线程运行）。"""

    finished = Signal(str)  # 成功为文件路径，失败为 ""

    def __init__(self, image, path):
        super().__init__()
        self._image = image
        self._path = path

    def run(self):
        try:
            self._image.save(self._path, "PNG")
        except Exception:
            logger.exception("导出 PNG 失败：%s", self._path)
            self.finished.emit("")
            return
        logger.info("课表已导出到 %s", self._path)
        self.finished.emit(self._path)
