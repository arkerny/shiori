import logging
from pathlib import Path

from PySide6.QtWidgets import (QMainWindow, QSplitter, QLabel, QProgressBar,
                               QWidget, QHBoxLayout)
from PySide6.QtCore import Qt, QTimer

from config.app_config import AppConfig
from config.theme import CHROME
from data.selection_store import has_content, seed_from_jiaowu
from ui.schedule_view import ScheduleView
from ui.course_view import CourseView
from ui.infopanel_view import InfoPanelView
from ui.settings_dialog import SettingsDialog
from ui.hdu_sync import HduSyncManager, config_ready

logger = logging.getLogger(__name__)

class MainWindow(QMainWindow):
    def __init__(self, config=None):
        super().__init__()
        self.setWindowTitle("Shiori")
        # 唯一配置实例，统一供各视图调用；main.py 传入以复用其读到的配置
        self.config = config or AppConfig()

        # 已选课初始化：教务文件就位时的同步复制已在 main.py 尝试；此处
        # 记录“教务文件缺失且已选无内容”的待补种状态，待在线拉取成功
        # 落盘后补做（见 _seed_after_sync）。
        _files = self.config.files
        self._seed_pending = (
            not has_content(_files.get("selected_courses", "selected_course.json"))
            and not Path(_files.get("jiaowu_courses", "jiaowu_schedule.json")).is_file()
        )

        w = self.config.window
        self.resize(w.get("width", 1500), w.get("height", 800))

        self.schedule_view = ScheduleView(self.config)
        self.course_view = CourseView(self.config)
        self.info_panel_view = InfoPanelView(self.config)

        # 勾选课程即刷新课表视图的学分统计与周课表网格
        self.course_view.selection_changed.connect(self.schedule_view.update_courses)

        # 本地已选课变化 -> infopanel 重算补选/退选（淡绿/淡黄行）
        self.course_view.selection_changed.connect(self.info_panel_view.update_courses)

        # 课表检测到的冲突 -> infopanel 用淡红行展示
        self.schedule_view.conflicts_changed.connect(self.info_panel_view.update_conflicts)

        # 课表网格宽度 -> infopanel 整表最大宽度对齐上方课表
        self.schedule_view.grid_width_changed.connect(self.info_panel_view.set_table_max_width)

        # infopanel 设置按钮 -> 打开设置对话框
        self.info_panel_view.settings_requested.connect(self._open_settings)

        # ---- 教务系统在线同步（后台线程，状态栏反馈进度）----
        self.sync = HduSyncManager(self.config, self)
        self.sync.task_started.connect(self._on_sync_started)
        self.sync.task_finished.connect(self._on_sync_finished)
        # 拉取成功后让对应视图重新读文件刷新
        self.sync.courses_updated.connect(lambda _n: self.course_view.reload_pool())
        self.sync.schedule_updated.connect(lambda _n: self.info_panel_view.reload_jiaowu())
        # 启动时教务文件缺失的场景：拉取落盘后补做已选课初始化并重载
        self.sync.schedule_updated.connect(self._seed_after_sync)
        # 手动触发：infopanel 两个更新按钮
        self.info_panel_view.sync_courses_requested.connect(self._sync_courses)
        self.info_panel_view.sync_schedule_requested.connect(self._sync_schedule)
        # 自动触发个人课表更新：course_view 勾选变化（按配置开关）、导出课表前
        self.course_view.selection_toggled.connect(self._on_selection_toggled)
        self.schedule_view.export_started.connect(self._auto_sync_schedule)

        # Horizontal splitter: schedule | course (boundary draggable)
        self.h_splitter = QSplitter(Qt.Horizontal)
        self.h_splitter.setHandleWidth(w.get("handle_width", 8))
        self.h_splitter.addWidget(self.schedule_view)
        self.h_splitter.addWidget(self.course_view)
        self.schedule_view.setMinimumWidth(w.get("schedule_min_width", 360))
        self.course_view.setMinimumWidth(w.get("course_min_width", 280))
        self.h_splitter.setSizes(w.get("splitter_h_sizes", [780, 720]))
        h_stretch = w.get("h_stretch", [6, 4])
        if len(h_stretch) >= 2:
            self.h_splitter.setStretchFactor(0, h_stretch[0])
            self.h_splitter.setStretchFactor(1, h_stretch[1])

        # Vertical splitter: (schedule|course) | info panel (boundary draggable)
        # Used directly as the central widget so handles always render and drag.
        self.v_splitter = QSplitter(Qt.Vertical)
        self.v_splitter.setHandleWidth(w.get("handle_width", 8))
        self.v_splitter.addWidget(self.h_splitter)
        self.v_splitter.addWidget(self.info_panel_view)
        self.h_splitter.setMinimumHeight(w.get("h_min_height", 150))
        self.info_panel_view.setMinimumHeight(w.get("info_min_height", 120))
        self.v_splitter.setSizes(w.get("splitter_v_sizes", [650, 150]))
        v_stretch = w.get("v_stretch", [7, 3])
        if len(v_stretch) >= 2:
            self.v_splitter.setStretchFactor(0, v_stretch[0])
            self.v_splitter.setStretchFactor(1, v_stretch[1])

        self.setCentralWidget(self.v_splitter)
        self._setup_status_bar()

        # 打开时自动更新个人课表：hdu 配置（账号 + 学年学期）完备才做
        if config_ready(self.config.hdu):
            logger.info("hdu 配置完备，启动时自动更新个人课表")
            QTimer.singleShot(0, self._auto_sync_schedule)
        else:
            logger.info("hdu 配置不完备（缺账号或学年学期），跳过自动更新")

    def closeEvent(self, event):
        """退出前等待后台线程结束，避免 QThread 析构时仍运行而 abort。"""
        self.course_view._stop_loader()
        self.schedule_view._stop_export()
        self.sync.stop()
        super().closeEvent(event)

    # ---- 教务系统在线同步 ----

    def _sync_courses(self):
        """手动更新课程信息（infopanel 按钮）。"""
        if not self.sync.fetch_courses():
            self.set_hint("已有更新任务在进行，请稍候")

    def _sync_schedule(self):
        """手动更新个人课表（infopanel 按钮）。"""
        if not self.sync.fetch_schedule():
            self.set_hint("已有更新任务在进行，请稍候")

    def _on_selection_toggled(self):
        """勾选变化（点击 / 空格框选）后：仅在配置开启时更新个人课表（默认关）。"""
        if self.config.hdu.get("update_schedule_after_selection", False):
            self.sync.fetch_schedule()

    def _auto_sync_schedule(self):
        """自动更新个人课表（启动 / 导出前）：忙碌时静默跳过。"""
        self.sync.fetch_schedule()

    def _seed_after_sync(self, _count):
        """启动时教务文件缺失的场景：在线拉取落盘后补做已选课初始化。

        已选已有内容时 seed_from_jiaowu 内部直接跳过（绝不覆盖）；
        补种成功后重载课程视图（loader 同时读课程池与已选）。
        """
        if not self._seed_pending:
            return
        files = self.config.files
        if seed_from_jiaowu(files.get("selected_courses", "selected_course.json"),
                            files.get("jiaowu_courses", "jiaowu_schedule.json")):
            self._seed_pending = False
            self.course_view.reload_pool()

    def _on_sync_started(self, label):
        """任务开始：进度条忙模式 + 提示等待，并禁用更新按钮。"""
        self.set_progress_busy(True)
        self.set_hint(label)
        self.info_panel_view.set_sync_busy(True)

    def _on_sync_finished(self, ok, message):
        """任务结束：收起进度条，按成败切换连接状态。"""
        self.set_progress_busy(False)
        self.set_hint(message)
        self.info_panel_view.set_sync_busy(False)
        if ok:
            self.set_connection_state("● 已连接", CHROME["ok"])
        else:
            self.set_connection_state("● 未连接", CHROME["danger"])

    # 状态栏统一字体格式（提示信息、导出状态、连接状态共用）；
    # 进度条样式由全局样式表统一下发（config/theme._global_stylesheet）
    _STATUS_LABEL_STYLE = (f"color:{CHROME['status']};"
                           f" border:none; font-size:12px;")

    def _setup_status_bar(self):
        """常驻状态栏：左侧提示信息，右侧进度条与教务系统连接状态。

        原先仅在导出 PNG 时由 statusBar().showMessage() 临时弹出；现改为常驻，
        导出状态直接写入提示标签，与“就绪”共用同一字体格式。进度条在导出时
        以不确定（忙）模式显示，为后续教务系统连接状态预留位置。
        """
        sb = self.statusBar()
        sb.setSizeGripEnabled(True)

        # 左侧：提示信息（占据剩余空间；导出状态亦写入此处，字体统一）
        self.status_hint = QLabel("就绪")
        self.status_hint.setStyleSheet(self._STATUS_LABEL_STYLE)
        sb.addWidget(self.status_hint, 1)

        # 进度条：导出/在线更新等任务以不确定模式显示，默认隐藏。
        # 外包一层容器提供右侧 12px 间距，与连接状态标签拉开距离。
        # 样式由全局样式表统一下发。
        self.status_progress = QProgressBar()
        self.status_progress.setFixedSize(140, 10)
        self.status_progress.setTextVisible(False)
        self.status_progress.setVisible(False)
        progress_wrap = QWidget()
        wrap_layout = QHBoxLayout(progress_wrap)
        wrap_layout.setContentsMargins(0, 0, 12, 0)
        wrap_layout.setSpacing(0)
        wrap_layout.addWidget(self.status_progress)
        sb.addPermanentWidget(progress_wrap)

        # 教务系统连接状态
        self.status_conn = QLabel("● 未连接")
        self.status_conn.setStyleSheet(self._STATUS_LABEL_STYLE)
        sb.addPermanentWidget(self.status_conn)

        # 左右留出边距，避免提示信息紧贴窗口边缘（须在添加全部控件后设置，
        # QStatusBar 会在增删控件时重置布局的 contentsMargins）
        sb.layout().setContentsMargins(10, 0, 10, 0)
        sb.layout().setSpacing(0)

    def set_hint(self, text: str):
        """更新常驻提示信息（导出状态等共用此标签，字体格式统一）。"""
        self.status_hint.setText(text)

    def set_progress_busy(self, busy: bool):
        """显示/隐藏状态栏进度条（不确定模式，用于无法精确计进度的任务）。"""
        self.status_progress.setRange(0, 0)  # 0..0 = 不确定（忙）动画
        self.status_progress.setVisible(busy)

    def set_connection_state(self, text: str, color: str = None):
        """更新教务系统连接状态指示（保持统一字体格式）。"""
        self.status_conn.setText(text)
        self.status_conn.setStyleSheet(
            f"color:{color or CHROME['status']};"
            f" border:none; font-size:12px;")

    def _open_settings(self):
        dlg = SettingsDialog(self.config, self)
        dlg.config_saved.connect(self._on_config_saved)
        dlg.exec()

    def _on_config_saved(self, config):
        # 配置已在对话框中保存；让各视图按新配置重建并刷新。
        # ScheduleView 在构造时快照 schedule/layout/export 分区，需整体重建；
        # course_view / info_panel_view 只重排列定义，数据文件路径变化则重读文件。
        self._rebuild_schedule_view()
        self.course_view.apply_config(config)
        self.course_view.reload_pool()
        self.info_panel_view.apply_config(config)
        self.set_hint("设置已保存")
        logger.info("设置已保存并应用")

    def _rebuild_schedule_view(self):
        """用当前配置重建课表视图并重新接线（替换 splitter 中的旧视图）。"""
        old = self.schedule_view
        self.schedule_view = ScheduleView(self.config)
        w = self.config.window
        self.schedule_view.setMinimumWidth(w.get("schedule_min_width", 360))
        self.h_splitter.setMinimumHeight(w.get("h_min_height", 150))
        sizes = self.h_splitter.sizes()
        self.h_splitter.replaceWidget(self.h_splitter.indexOf(old),
                                      self.schedule_view)
        self.h_splitter.setSizes(sizes)

        self.course_view.selection_changed.connect(self.schedule_view.update_courses)
        self.schedule_view.conflicts_changed.connect(self.info_panel_view.update_conflicts)
        self.schedule_view.grid_width_changed.connect(self.info_panel_view.set_table_max_width)
        self.schedule_view.export_started.connect(self._auto_sync_schedule)

        old._stop_export()
        old.deleteLater()
        # 用当前已选课立即渲染新课表（reload_pool 加载完成后会再次推送）
        self.schedule_view.update_courses(self.course_view.selected_courses)
