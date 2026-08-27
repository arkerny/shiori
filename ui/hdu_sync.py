"""教务系统数据同步：在后台线程执行 hdu 模块的在线拉取。

一次只跑一个任务（课程池 / 个人课表互斥），通过信号向主窗口反馈
进度提示与连接状态；任务成功后通知对应视图刷新本地文件。
"""

from PySide6.QtCore import QObject, QThread, Signal

from hdu import fetch_courses as fetch_courses_online
from hdu import fetch_schedule as fetch_schedule_online


def config_ready(hdu_cfg):
    """判断 hdu 配置是否完备：任一账号（newjw/cas）可用，且学年学期合法。

    缺账号或学年学期缺失/非法时返回 False，调用方应跳过自动更新。
    """
    has_account = False
    for account in (hdu_cfg.get("newjw"), hdu_cfg.get("cas")):
        if account and account.get("username") and account.get("password"):
            has_account = True
            break
    xuenian = str(hdu_cfg.get("xuenian", "") or "")
    xueqi = str(hdu_cfg.get("xueqi", "") or "")
    return has_account and xuenian.isdigit() and xueqi in ("1", "2")


class FetchWorker(QObject):
    """在线程里执行拉取函数；finished 携带 (result, error)。"""

    finished = Signal(object, object)  # error 为 None 表示成功

    def __init__(self, func):
        super().__init__()
        self._func = func

    def run(self):
        try:
            self.finished.emit(self._func(), None)
        except Exception as e:  # 登录失败 / 网络异常等，统一回报给 UI
            self.finished.emit(None, str(e) or e.__class__.__name__)


class HduSyncManager(QObject):
    """串行调度课程池 / 个人课表拉取，维护“已连接 / 未连接”状态。"""

    task_started = Signal(str)          # 任务开始（状态栏提示文本）
    task_finished = Signal(bool, str)   # 结束（是否成功 + 结果消息）
    courses_updated = Signal(int)       # 课程池已落盘（门数）
    schedule_updated = Signal(int)      # 个人课表已落盘（门数）

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self._config = config
        self._done_cb = None  # 当前任务的成功回调：result -> 结果消息
        # 线程 -> worker 的映射；引用必须持有到线程真正结束，过早丢弃
        # （如任务完成回调里置 None）会让 Python GC 销毁仍在收尾的
        # QThread，导致程序 abort。
        self._jobs = {}

    @property
    def busy(self):
        return bool(self._jobs)

    # ---- 任务入口（busy 时拒绝，返回 False）----

    def fetch_courses(self):
        """手动更新课程池（任务落实查询，约 2 分钟）。"""
        return self._start(
            "正在更新课程信息（服务端聚合慢，约 2 分钟，请耐心等待）…",
            lambda: fetch_courses_online(self._config),
            lambda result: (self.courses_updated.emit(len(result)),
                            f"课程信息已更新（{len(result)} 门）")[1],
        )

    def fetch_schedule(self):
        """更新个人课表（教务已选课）。"""
        return self._start(
            "正在更新个人课表…",
            lambda: fetch_schedule_online(self._config),
            lambda result: (self.schedule_updated.emit(len(result)),
                            f"个人课表已更新（{len(result)} 门已选）")[1],
        )

    # ---- 线程调度 ----

    def _start(self, label, func, done_cb):
        if self.busy:
            return False
        self._done_cb = done_cb
        self.task_started.emit(label)

        worker = FetchWorker(func)
        thread = QThread()
        self._jobs[thread] = worker
        worker.moveToThread(thread)
        thread.started.connect(worker.run)
        worker.finished.connect(self._on_finished)
        worker.finished.connect(thread.quit)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        thread.finished.connect(lambda t=thread: self._jobs.pop(t, None))
        thread.start()
        return True

    def _on_finished(self, result, error):
        """回到主线程：汇报结果（线程引用由 thread.finished 统一清理）。"""
        if error is None:
            message = self._done_cb(result)
        else:
            message = f"更新失败：{error}"
        self._done_cb = None
        self.task_finished.emit(error is None, message)

    def stop(self):
        """窗口关闭时确保线程结束，避免 QThread 析构时仍运行导致崩溃。"""
        for thread in list(self._jobs):
            worker = self._jobs.get(thread)
            try:
                if not thread.isRunning():
                    self._jobs.pop(thread, None)
                    continue
            except RuntimeError:
                self._jobs.pop(thread, None)
                continue
            # 断开完成回调，防止在已销毁的控件上更新 UI
            if worker is not None:
                try:
                    worker.finished.disconnect(self._on_finished)
                except RuntimeError:
                    pass
            thread.quit()
            thread.wait(15000)
            self._jobs.pop(thread, None)
        # 注：拉取中的 requests 无法中断，极端情况下 wait 超时后放弃等待，
        # 线程随进程退出终止，不影响已落盘数据的完整性。
