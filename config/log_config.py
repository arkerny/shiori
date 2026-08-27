"""运行日志：全程序共用的 logging 配置。

main.py 启动时最先调用 setup_logging(config.log)（log 分区来自
config.json，缺省值见 config.app_config.DEFAULT_CONFIG；直接调用
setup_logging() 也能用内置默认跑起来）。各模块用
logging.getLogger(__name__) 取各自 logger 记录，天然按模块命名。
- 分级：DEBUG / INFO / WARNING / ERROR（+ CRITICAL）
- 落盘（log.file）：log.level 起全量写入，每条记录写完即 flush，
  运行期间滚动更新，可随时用 tail 跟踪；log.clear_on_start=True 时
  每次启动清空重写（mode="w"），False 改为跨启动追加（mode="a"）
- 控制台：log.console=True 时镜像输出（log.console_level 起），
  保留原 print 在命令行启动时的可见性
"""

import logging
from pathlib import Path

_DEFAULT_FILE = "logs/shiori.log"

_FORMAT = "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

# 级别名 -> logging 常量；config 里写了非法级别时回退调用方给的默认
_LEVELS = {"DEBUG": logging.DEBUG, "INFO": logging.INFO,
           "WARNING": logging.WARNING, "ERROR": logging.ERROR}


def _resolve_level(value, fallback):
    return _LEVELS.get(str(value).upper(), fallback)


def setup_logging(log_cfg=None):
    """按 config.json 的 log 分区初始化根 logger；已初始化时直接返回（幂等，防重复挂 handler。"""
    root = logging.getLogger()
    if root.handlers:
        return root
    cfg = dict(log_cfg or {})

    log_file = Path(cfg.get("file") or _DEFAULT_FILE)
    log_file.parent.mkdir(parents=True, exist_ok=True)

    # mode="w" 每次启动清空重写；clear_on_start=False 时改为跨启动追加
    mode = "w" if cfg.get("clear_on_start", True) else "a"
    file_handler = logging.FileHandler(log_file, mode=mode, encoding="utf-8")
    file_handler.setLevel(_resolve_level(cfg.get("level"), logging.DEBUG))
    file_handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
    root.addHandler(file_handler)

    if cfg.get("console", True):
        console_handler = logging.StreamHandler()
        console_handler.setLevel(
            _resolve_level(cfg.get("console_level"), logging.INFO))
        console_handler.setFormatter(logging.Formatter(_FORMAT, _DATE_FORMAT))
        root.addHandler(console_handler)

    root.setLevel(logging.DEBUG)

    # 三方库降噪：requests 底层 urllib3 的 DEBUG 刷屏且无分析价值
    logging.getLogger("urllib3").setLevel(logging.WARNING)

    return root
