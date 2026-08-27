import logging
import sys

from config.app_config import AppConfig
from config.log_config import setup_logging

# 日志配置读自 config.json：先建配置实例、再初始化日志。须先于其他
# ui import——ui.search 等模块在 import 期就可能记录降级警告，晚了会丢。
# （已知边界：config.json 自身解析失败的告警发生在日志就绪前，只会
# 出现在控制台，不会进日志文件。）
config = AppConfig()
setup_logging(config.log)

from PySide6.QtWidgets import QApplication
from ui.main_window import MainWindow

logger = logging.getLogger(__name__)

def main():
    logger.info("Shiori 启动")
    app = QApplication(sys.argv)
    window = MainWindow(config)
    window.show()
    ret = app.exec()
    logger.info("Shiori 退出（code=%d）", ret)
    sys.exit(ret)

if __name__ == "__main__":
    main()
