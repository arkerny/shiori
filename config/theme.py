import re

# 不需用户修改的呈现常量：配色 / sksj 解析正则 / 单元格分隔线。
# 集中于此，便于统一调整主题与解析格式。

# 课程单元格配色（背景, 文字），按课程顺序循环
COURSE_COLORS = [
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

# 冲突格警示色
CONFLICT_BG = "#FDECEA"
CONFLICT_FG = "#B42318"

# 信息面板（infopanel）状态行底色：补选 / 退选 / 冲突
INFO_BG_ADD = "#E6F4EA"       # 补选（淡绿）：selected 有、教务系统未选
INFO_BG_DROP = "#FEF6E0"      # 退选（淡黄）：教务系统已选、selected 未选
INFO_BG_CONFLICT = "#FDECEA"  # 冲突（淡红）：课表检测到时间冲突

# 空闲周次标签色（饱和琥珀，与所有课程底色拉开对比）
FREE_CHIP_BG = "#FCD34D"
FREE_CHIP_FG = "#78350F"
# 无空闲周的弱化文字色
NONE_FG = "#6B7280"

# 框架 / UI 配色（集中调整主题）
CHROME = {
    "text": "#2C3440",        # 主文字 / 按钮底色
    "text_hover": "#3A4456",  # 按钮悬停
    "muted": "#8A94A6",       # 弱化说明文字
    "surface": "#FFFFFF",     # 统计栏 / 表格背景
    "gridline": "#E3E8EE",    # 表格网格线 / 表头边框
    "header_bg": "#F4F6F8",   # 表头背景
    "separator": "#D8DEE6",  # 单元格分隔线
}

# 默认字体（main.py 启动时应用到 QApplication）。列表依次探测，
# 均未安装时保持系统默认字体。
FONT_FAMILIES = ["PingFang SC", "LXGW WenKai"]

# sksj 分段正则（匹配数据源格式：星期X第N-M节{周次}）
SEGMENT_RE = re.compile(
    r"星期([一二三四五六日])第([\d,\-]+)节\{([^}]*)\}"
)

# 同一单元格内多门课程的虚线分隔（颜色取自 CHROME，避免重复硬编码）
ITEM_SEP = (
    f"<hr style='border:none; border-top:1px dashed {CHROME['separator']};"
    f" margin:4px 0;'/>"
)
