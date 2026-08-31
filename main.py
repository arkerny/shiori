import logging
import os
import sys
from pathlib import Path

from config.app_config import AppConfig
from config.log_config import setup_logging
from config.theme import FONT_FAMILIES
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

from PySide6.QtGui import QFontDatabase
from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow


def _apply_default_font(app):
    """应用默认字体：LXGW WenKai（霞鹜文楷）。

    按 FONT_FAMILIES 依次探测本机已安装的字体族，找到即设为全局
    默认（保留系统字号）；均未安装时保持系统默认并记日志。
    """
    installed = set(QFontDatabase.families())
    for family in FONT_FAMILIES:
        if family in installed:
            font = app.font()
            font.setFamily(family)
            app.setFont(font)
            logger.info("默认字体已设置为 %s", family)
            return
    logger.warning("未找到字体 %s，使用系统默认字体", "/".join(FONT_FAMILIES))


def main():
    logger.info("Shiori 启动")
    app = QApplication(sys.argv)
    _apply_default_font(app)
    window = MainWindow(config)
    window.show()
    ret = app.exec()
    logger.info("Shiori 退出（code=%d）", ret)
    sys.exit(ret)

if __name__ == "__main__":
    main()
