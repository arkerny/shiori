"""macOS 原生辅助功能（Accessibility）关闭。

规避 QTBUG-107022：macOS 上启用辅助功能时，item view 的每个单元格都会
被 QAccessibleCache 创建并永久缓存一个原生包装对象（QMacAccessibilityElement），
且系统 AX 服务会周期性强制枚举全部子元素。课程表 4609 行 × 约 10 列 ≈
4.6 万格，久置后缓存把内存吃到 14~15 GB（16 GB 机器上触发压缩/换出），
再在搜索框输入时，输入法按键处理内 autorelease pool 出栈需释放这数万条
AX 对象，伴随海量缺页中断，主线程冻结数秒（macOS hang 报告实锤，
见项目根 error_log1/2.txt）。

对策：窗口显示后调用 [NSApp setAccessibilityEnabled:NO]，系统不再向本
应用投递 AX 查询，缓存不再膨胀。本应用不依赖 VoiceOver 等读屏功能，
关闭无副作用；仅 macOS 生效，Linux（Ubuntu 22.04）直接跳过。

时序注意：过早调用（应用刚启动、窗口尚未上屏）不生效，须等窗口显示
后再关（调用方用 singleShot 延迟保证）；NSApp 尚未就绪时静默跳过。
"""

import logging
import sys

logger = logging.getLogger(__name__)


def disable_native_accessibility():
    """关闭 macOS 原生辅助功能（无 AppKit / 非 macOS / 应用未就绪则跳过）。"""
    if sys.platform != "darwin":
        return
    try:
        from AppKit import NSApplication
    except ImportError:
        logger.warning(
            "未安装 pyobjc-framework-Cocoa，无法关闭 macOS 原生辅助功能"
            "（久置后搜索可能因 QTBUG-107022 卡顿）")
        return
    # 注意不能用 `from AppKit import NSApp` 判空：pyobjc 的 NSApp 是懒加载
    # 代理，应用未创建时调用其方法才抛 AttributeError，is None 恒为假。
    app = NSApplication.sharedApplication()
    if app is None:
        logger.warning("NSApplication 尚未就绪，本次未关闭原生辅助功能")
        return
    app.setAccessibilityEnabled_(False)
    logger.info("已关闭 macOS 原生辅助功能（规避 QTBUG-107022 内存膨胀）")
