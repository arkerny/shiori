import logging
import os
import sys
from pathlib import Path

from config.app_config import AppConfig
from config.log_config import setup_logging
from config.theme import apply_app_theme, load_theme
from data.selection_store import seed_from_jiaowu

# 数据主目录：config.json、course.json、logs/ 等所有相对路径统一以此为
# 基准。打包成 .app 后双击启动时 cwd 是 /（Finder），源码运行时 cwd 是
# 项目目录，两种形态收敛到同一处，行为一致。
DATA_DIR = Path.home() / ".shiori"


def _prepare_data_dir():
    """确保 ~/.shiori 存在并切入为工作目录。"""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    os.chdir(DATA_DIR)


_prepare_data_dir()

# 日志配置读自 config.json：先建配置实例、再初始化日志。须先于其他
# ui import——ui.search 等模块在 import 期就可能记录降级警告，晚了会丢。
# （已知边界：config.json 自身解析失败的告警发生在日志就绪前，只会
# 出现在控制台，不会进日志文件。）
config = AppConfig()
setup_logging(config.log)
# 主题装载（config.json theme 分区 -> config/theme.CHROME）。须先于下面
# 的 ui 导入：样式表在类定义期读取颜色；缺键回退的默认值同源，顺序异常
# 不会配色错乱，仅用户自定义值不生效。
load_theme(config.theme)

logger = logging.getLogger(__name__)


def _seed_selected_courses(cfg):
    """已选课初始化（同步部分）：教务课表文件已就位时立即复制。

    教务文件缺失时的补种在 MainWindow 完成（见其 _seed_after_sync）
    ——须先走在线拉取流程把文件取回来，依赖 UI 建立后的同步线程。
    """
    files = cfg.files
    seed_from_jiaowu(files.get("selected_courses", "selected_course.json"),
                     files.get("jiaowu_courses", "jiaowu_schedule.json"))


_seed_selected_courses(config)

from PySide6.QtCore import QEvent, QObject, QPoint, QSize
from PySide6.QtGui import QCursor, QFontDatabase
from PySide6.QtWidgets import QApplication, QWidget
from ui.main_window import MainWindow


def _apply_default_font(app, families):
    """应用默认字体（配置 font.families）。

    依次探测本机已安装的字体族，取第一个命中的设为全局默认（保留
    系统字号）；列表为空或均未安装时保持系统默认。
    """
    if not families:
        return
    installed = set(QFontDatabase.families())
    for family in families:
        if family in installed:
            font = app.font()
            font.setFamily(family)
            app.setFont(font)
            logger.info("默认字体已设置为 %s", family)
            return
    logger.warning("未找到已安装字体 %s，使用系统默认字体", "/".join(families))


class _TooltipPositioner(QObject):
    """提示框贴近鼠标显示、尺寸贴合文字。

    Qt 的 placeTip 把提示框放在「光标图像高度」下方（offset =
    (2, cursorSize.height())），高 DPI 下光标图像高度可达 40 逻辑像素，
    观感上离鼠标过远且无配置项；QTipLabel 在 sizeHint 之外还额外加了
    一片与字高等高的空白，框比文字大很多。这里在 Qt 摆位后（Show/Move
    事件）重设为文本实际 sizeHint，再贴到鼠标右下 14/18 逻辑像素，
    越出屏幕时翻到鼠标左/上方。仅识别 Qt 内部的 QTipLabel 窗口，
    识别失败（Qt 改名）则不干预。
    """

    _OFFSET = QPoint(14, 18)

    def eventFilter(self, watched, event):
        if event.type() not in (QEvent.Show, QEvent.Move):
            return False
        tip = watched
        if not (isinstance(tip, QWidget) and tip.isWindow()
                and tip.metaObject().className() == "QTipLabel"):
            return False
        self._tighten(tip)
        cursor = QCursor.pos()
        target = cursor + self._OFFSET
        avail = tip.screen().availableGeometry()
        # 右/下缘溢出 -> 翻到鼠标左/上方，再整体夹进屏幕可用区
        if target.x() + tip.width() > avail.right() + 1:
            target.setX(cursor.x() - self._OFFSET.x() - tip.width())
        if target.y() + tip.height() > avail.bottom() + 1:
            target.setY(cursor.y() - self._OFFSET.y() - tip.height())
        target.setX(max(avail.left(), min(target.x(), avail.right() + 1 - tip.width())))
        target.setY(max(avail.top(), min(target.y(), avail.bottom() + 1 - tip.height())))
        if (tip.pos() - target).manhattanLength() > 1:  # 自身 move 触发的重复事件
            tip.move(target)
        return False

    @staticmethod
    def _tighten(tip):
        """收紧提示框：去掉 QTipLabel 内建的大边距，再按其自身 sizeHint 重设。

        QTipLabel 默认 margin = 1 + PM_ToolTipLabelFrameWidth（本平台
        为 3），短文本时框比文字大很多。置 0 后用 QLabel 自己的
        sizeHint（已含 QSS padding/border 与换行判定）加 Qt 的 1px
        extra，布局仍由 Qt 计算，不会裁字。
        """
        tip.setMargin(0)
        avail = tip.screen().availableGeometry()
        size = tip.sizeHint() + QSize(1, 1)
        if tip.wordWrap() and size.width() > avail.width():
            size = QSize(avail.width(), tip.heightForWidth(avail.width()))
        size = size.boundedTo(avail.size())
        if size != tip.size():
            tip.resize(size)


def main():
    logger.info("Shiori 启动")
    app = QApplication(sys.argv)
    # 全局主题：Fusion 风格 + 固定调色板 + 全局样式表，不采用任何系统
    # 默认颜色，保证各平台呈现一致（以 macOS 为基准）。须在创建窗口前。
    apply_app_theme(app)
    # 提示框贴近鼠标（Qt 默认在高 DPI 下离鼠标过远），父对象挂 app 保活
    app.installEventFilter(_TooltipPositioner(app))
    _apply_default_font(app, config.font_families())
    window = MainWindow(config)
    window.show()
    ret = app.exec()
    logger.info("Shiori 退出（code=%d）", ret)
    sys.exit(ret)

if __name__ == "__main__":
    main()
