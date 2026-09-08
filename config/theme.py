import re

from PySide6.QtGui import QColor, QPalette

# 呈现主题与解析常量。
#
# 所有 UI 颜色集中于 CHROME / COURSE_COLORS，由 config.json 的 theme
# 分区提供（main.py 启动时 load_theme 装载，先于任何 ui 模块导入）。
# 任何组件不得读系统调色板或系统默认样式，统一经 apply_app_theme 全局
# 下发，保证 macOS / Windows / Linux（含 GNOME 深色主题）呈现一致，
# 以 macOS 为基准。

# 内置默认主题（app_config.DEFAULT_CONFIG["theme"] 以此为默认值，同源）
_DEFAULT_CHROME = {
    # 框架
    "window": "#FFFFFF",        # 主窗口/对话框/状态栏底色（macOS 窗口灰）
    "surface": "#FFFFFF",       # 表格/输入框底色
    "header_bg": "#F4F6F8",     # 表头/分组框底色
    "gridline": "#E3E8EE",      # 表格网格线 / 表头边框
    "separator": "#D8DEE6",     # 单元格内分隔虚线 / 禁用按钮底色
    # 文字
    "text": "#2C3440",          # 主文字（兼作主按钮底色）
    "text_hover": "#3A4456",    # 主按钮悬停底色
    "muted": "#8A94A6",         # 弱化说明文字（节次列等）
    "status": "#888888",        # 状态栏文字
    # 交互
    "alt_row": "#F5F7FA",       # 表格隔行底色
    "select_bg": "#DCE7FB",     # 选中行底色
    "select_fg": "#1A3B5C",     # 选中行文字
    "accent": "#4C7DFF",        # 强调色（进度条/标签页/链接）
    "accent_light": "#7BA6FF",  # 强调色渐变浅端
    "ok": "#4CAF50",            # 连接正常
    "danger": "#B42318",        # 连接断开 / 错误
    # 语义底色
    "conflict_bg": "#FDECEA",   # 冲突格底色
    "conflict_fg": "#B42318",   # 冲突警示文字
    "info_bg_add": "#E6F4EA",   # 补选行（淡绿）
    "info_bg_drop": "#FEF6E0",  # 退选行（淡黄）
    "info_bg_conflict": "#FDECEA",  # 冲突行（淡红）
    "free_chip_bg": "#FCD34D",  # 空闲周标签底色
    "free_chip_fg": "#78350F",  # 空闲周标签文字
    "none_fg": "#6B7280",       # 无空闲周弱化文字
}

# 课程单元格配色（背景, 文字），按课程顺序循环
_DEFAULT_COURSE_COLORS = [
    ("#E8F0FE", "#1A3B5C"),   # 蓝
    ("#E6F4EA", "#1E5E3A"),   # 绿
    ("#FDECEA", "#8A2B25"),   # 红
    ("#FEF3E2", "#8A5A1A"),   # 橙
    ("#F1E8FE", "#5B2B8A"),   # 紫
    ("#E4F5F5", "#1E5E5E"),   # 青
    ("#EAF1FA", "#2A4D7A"),   # 钢蓝
    ("#FCE9F1", "#7A2B55"),   # 玫红
    ("#DFF3FA", "#0E5A75"),   # 天蓝
    ("#EFF5DC", "#55661C"),   # 黄绿
    ("#E9ECFD", "#343F8C"),   # 靛蓝
    ("#FEEBE3", "#B03A1E"),   # 鲑红
    ("#F6EEDF", "#6F5220"),   # 沙棕
    ("#DDF3EA", "#0E6B52"),   # 薄荷
    ("#ECEFF4", "#3E4C63"),   # 石板灰
    ("#F6E9F5", "#7A3B6B"),   # 藕紫
]

# 运行时主题：load_theme 用 config.json 的 theme 分区就地覆盖
CHROME = dict(_DEFAULT_CHROME)
COURSE_COLORS = [tuple(pair) for pair in _DEFAULT_COURSE_COLORS]

# sksj 分段正则（匹配数据源格式：星期X第N-M节{周次}）
SEGMENT_RE = re.compile(
    r"星期([一二三四五六日])第([\d,\-]+)节\{([^}]*)\}"
)


def load_theme(theme_cfg):
    """用 config.json 的 theme 分区覆盖默认主题（就地更新）。

    在任何 ui 模块导入前调用（main.py）；缺键保持内置默认，与
    DEFAULT_CONFIG["theme"] 同源，故顺序异常也不会配色错乱，
    仅用户自定义值不生效。
    """
    if not isinstance(theme_cfg, dict):
        return
    for key in CHROME:
        if key in theme_cfg:
            CHROME[key] = theme_cfg[key]
    colors = theme_cfg.get("course_colors")
    if isinstance(colors, list) and colors:
        pairs = [tuple(pair) for pair in colors
                 if isinstance(pair, (list, tuple)) and len(pair) == 2]
        if pairs:
            COURSE_COLORS[:] = pairs


def item_sep():
    """同一单元格内多门课程的虚线分隔（HTML，颜色随主题）。"""
    return (f"<hr style='border:none; border-top:1px dashed "
            f"{CHROME['separator']}; margin:4px 0;'/>")


def _global_stylesheet():
    """全局样式表：统一所有未单独定制的控件（菜单/输入框/按钮/表格等）。

    单独 setStyleSheet 的控件（课表/信息面板表格、导出按钮等）以自身
    样式优先，不受影响。
    """
    return f"""
    QMainWindow, QDialog {{ background:{CHROME['window']}; }}
    QStatusBar {{ background:{CHROME['window']}; border:none; }}
    QStatusBar::item {{ border:none; }}
    QSplitter::handle {{ background:{CHROME['window']}; }}
    QToolTip {{ background:{CHROME['surface']}; color:{CHROME['text']};
                border:1px solid {CHROME['muted']}; padding:2px 6px; }}
    QMenu {{ background:{CHROME['surface']}; color:{CHROME['text']};
             border:1px solid {CHROME['gridline']}; padding:4px; }}
    QMenu::item {{ padding:4px 24px; border-radius:4px; }}
    QMenu::item:selected {{ background:{CHROME['select_bg']};
                            color:{CHROME['select_fg']}; }}
    QMenu::separator {{ height:1px; background:{CHROME['gridline']};
                        margin:4px 8px; }}
    QLineEdit, QSpinBox, QTimeEdit, QComboBox {{
        background:{CHROME['surface']}; color:{CHROME['text']};
        border:1px solid {CHROME['gridline']}; border-radius:4px;
        padding:3px 8px;
        selection-background-color:{CHROME['select_bg']};
        selection-color:{CHROME['select_fg']}; }}
    QComboBox::drop-down {{ border:none; }}
    QComboBox QAbstractItemView {{ background:{CHROME['surface']};
        color:{CHROME['text']}; border:1px solid {CHROME['gridline']};
        selection-background-color:{CHROME['select_bg']};
        selection-color:{CHROME['select_fg']}; }}
    QPushButton {{ background:{CHROME['text']}; color:{CHROME['surface']};
        border:none; border-radius:6px; padding:6px 16px; font-size:12px; }}
    QPushButton:hover {{ background:{CHROME['text_hover']}; }}
    QPushButton:pressed {{ background:{CHROME['text_hover']}; }}
    QPushButton:disabled {{ background:{CHROME['separator']};
                            color:{CHROME['muted']}; }}
    QGroupBox {{ border:1px solid {CHROME['gridline']}; border-radius:6px;
                 margin-top:12px; }}
    QGroupBox::title {{ subcontrol-origin:margin; left:10px; padding:0 4px;
                        color:{CHROME['text']}; font-weight:600; }}
    QTabWidget::pane {{ border:1px solid {CHROME['gridline']}; }}
    QTabBar::tab {{ background:{CHROME['header_bg']}; color:{CHROME['text']};
        padding:6px 16px; margin-right:2px;
        border:1px solid {CHROME['gridline']}; border-bottom:none;
        border-top-left-radius:4px; border-top-right-radius:4px; }}
    QTabBar::tab:selected {{ background:{CHROME['surface']};
        border-bottom:2px solid {CHROME['accent']}; }}
    QHeaderView::section {{ background:{CHROME['header_bg']};
        color:{CHROME['text']}; border:none;
        border-right:1px solid {CHROME['gridline']};
        border-bottom:1px solid {CHROME['gridline']};
        padding:6px; font-weight:600; }}
    QTableCornerButton::section {{ background:{CHROME['header_bg']};
                                   border:none; }}
    QTableWidget {{ background:{CHROME['surface']}; color:{CHROME['text']};
        gridline-color:{CHROME['gridline']};
        alternate-background-color:{CHROME['alt_row']};
        selection-background-color:{CHROME['select_bg']};
        selection-color:{CHROME['select_fg']}; }}
    QListWidget {{ background:{CHROME['surface']}; color:{CHROME['text']};
        border:1px solid {CHROME['gridline']}; }}
    QListWidget::item {{ padding:4px 6px; border-radius:4px; }}
    QListWidget::item:selected {{ background:{CHROME['select_bg']};
        color:{CHROME['select_fg']}; }}
    QProgressBar {{ border:none; border-radius:5px;
                    background:{CHROME['gridline']}; }}
    QProgressBar::chunk {{ border-radius:5px;
        background:qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {CHROME['accent_light']}, stop:1 {CHROME['accent']}); }}
    QScrollBar:vertical {{ background:transparent; width:10px; }}
    QScrollBar::handle:vertical {{ background:{CHROME['separator']};
        border-radius:5px; min-height:24px; }}
    QScrollBar::handle:vertical:hover {{ background:{CHROME['muted']}; }}
    QScrollBar:horizontal {{ background:transparent; height:10px; }}
    QScrollBar::handle:horizontal {{ background:{CHROME['separator']};
        border-radius:5px; min-width:24px; }}
    QScrollBar::handle:horizontal:hover {{ background:{CHROME['muted']}; }}
    QScrollBar::add-line, QScrollBar::sub-line {{ width:0; height:0; }}
    QScrollBar::add-page, QScrollBar::sub-page {{ background:transparent; }}
    """


def apply_app_theme(app):
    """把主题全局应用到 QApplication：Fusion 风格 + 固定调色板 + 全局样式表。

    在创建任何窗口前调用（main.py）。所有颜色取自 CHROME（config.json
    theme 分区），不采用任何系统默认（Windows Vista 样式、Linux GTK/
    深色主题均被覆盖），跨平台呈现一致，以 macOS 为基准。
    """
    app.setStyle("Fusion")
    palette = QPalette()

    def set_role(role, color, *groups):
        # 默认同时设 Active/Inactive（否则非激活窗口回退到 Qt 内置色）
        for group in (groups or (QPalette.Active, QPalette.Inactive)):
            palette.setColor(group, role, QColor(color))

    set_role(QPalette.Window, CHROME["window"])
    set_role(QPalette.WindowText, CHROME["text"])
    set_role(QPalette.Base, CHROME["surface"])
    set_role(QPalette.AlternateBase, CHROME["alt_row"])
    set_role(QPalette.Text, CHROME["text"])
    set_role(QPalette.Button, CHROME["header_bg"])
    set_role(QPalette.ButtonText, CHROME["text"])
    set_role(QPalette.ToolTipBase, CHROME["surface"])
    set_role(QPalette.ToolTipText, CHROME["text"])
    set_role(QPalette.Highlight, CHROME["select_bg"])
    set_role(QPalette.HighlightedText, CHROME["select_fg"])
    set_role(QPalette.Link, CHROME["accent"])
    set_role(QPalette.PlaceholderText, CHROME["muted"])
    # 禁用态统一弱化
    set_role(QPalette.Text, CHROME["muted"], QPalette.Disabled)
    set_role(QPalette.WindowText, CHROME["muted"], QPalette.Disabled)
    set_role(QPalette.ButtonText, CHROME["muted"], QPalette.Disabled)
    set_role(QPalette.Base, CHROME["header_bg"], QPalette.Disabled)

    app.setPalette(palette)
    app.setStyleSheet(_global_stylesheet())
