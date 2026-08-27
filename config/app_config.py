import json
import logging
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


# 全量默认配置：config.json 缺失/缺键时回退、首次生成、兼作 schema 文档。
DEFAULT_CONFIG = {
    "course_columns": [],  # 列定义：{"name","field","visible","width"}，由用户在设置中编辑
    "files": {
        "course_pool": "course.json",
        "selected_courses": "selected_course.json",
        "jiaowu_courses": "jiaowu_course.json",  # 教务系统已选课，用于与本地已选对比补/退选
    },
    "log": {
        # 运行日志（config/log_config.py 消费）。level 取级别名
        # DEBUG/INFO/WARNING/ERROR，非法值回退默认。
        "file": "logs/shiori.log",  # 日志文件路径（相对运行目录）
        "level": "DEBUG",           # 文件记录级别
        "console": True,            # 是否同时输出到控制台
        "console_level": "INFO",    # 控制台记录级别
        "clear_on_start": True,     # 每次启动清空日志文件；False 改为追加
    },
    "course": {
        "key_field": "jxbmc",  # 课程唯一标识字段（教学班名称）
    },
    "hdu": {
        # 教务系统（newjw）对接配置，供 hdu 模块使用。
        # 对应 HDU-KillCourse 的 NewjwLogin/CasLogin/Time/Cookies 配置。
        # 登录固定 newjw 优先，失败自动换 cas（两套账号相互独立）。
        "newjw": {               # 教务系统账号（优先；密码明文存本地，注意保管）
            "username": "",
            "password": "",
        },
        "cas": {                 # 统一身份认证账号（newjw 失败时的兜底）
            "username": "",
            "password": "",
        },
        "xuenian": "2026",       # 学年（秋季学期所在年份）
        "xueqi": "1",            # 学期：1=秋季 / 2=春季
        # 勾选变化（点击或空格框选）后是否自动在线更新个人课表，默认关
        "update_schedule_after_selection": False,
        "course_timeout": 600,   # 课程池查询超时（秒）；任务落实聚合慢，高峰可更久
        "course_retries": 2,     # 课程池查询超时/网络错误的自动重试次数
        "schedule_timeout": 30,  # 个人课表查询超时（秒）；已选课列表小，秒级返回
        "schedule_retries": 2,   # 个人课表查询超时/网络错误的自动重试次数
        "user_agent": "",        # 空 = 使用内置 UA
        "cookies": {             # 登录成功后自动回写，下次免登录
            "enabled": True,
            "jsessionid": "",
            "route": "",
        },
    },
    "table": {
        "default_column_width": 120,  # 列未指定 width 时的默认宽（px）
    },
    "info_table": {
        # 信息面板（infopanel）配置。columns 结构与 course_columns 一致
        # （{name, field, width}）；field 指向课程 dict 字段，教学班名称(jxbmc)
        # 全局唯一，作为区分课程的 id。field 留空为计算列：第一个空 field 列
        # 显示“类型”（补选/退选/冲突），最后一个显示“说明”。
        # width<=0 表示该列自适应拉伸填满剩余宽度。
        "row_height": 28,        # 行高（px）
        "max_width": 0,          # 0 = 跟随上方课表网格宽度；>0 则固定上限（px）
        "columns": [
            {"name": "类型", "field": "", "width": 60},
            {"name": "课程", "field": "kcmc", "width": 150},
            {"name": "教学班名称", "field": "jxbmc", "width": 180},
            {"name": "时间", "field": "sksj", "width": 220},
            {"name": "说明", "field": "", "width": 0},
        ],
    },
    "schedule": {
        "total_weeks": 17,  # 一学期教学周数
        "period_times": {  # 节次 -> [起, 止]；键以字符串存（JSON 限制），运行时转 int
            "1": ["08:05", "08:50"],
            "2": ["08:55", "09:40"],
            "3": ["10:00", "10:45"],
            "4": ["10:50", "11:35"],
            "5": ["11:40", "12:25"],
            "6": ["13:30", "14:15"],
            "7": ["14:20", "15:05"],
            "8": ["15:15", "16:00"],
            "9": ["16:05", "16:50"],
            "10": ["18:30", "19:15"],
            "11": ["19:20", "20:05"],
            "12": ["20:10", "20:55"],
        },
        "weekdays": ["星期一", "星期二", "星期三", "星期四",
                     "星期五", "星期六", "星期日"],
        "weekday_always": [0, 1, 2, 3, 4],  # 始终显示的星期下标（周一~周五）
        "practice_location": "课外实践不在教室",  # 该地点的段周次按空闲处理
        "credit_limit": 25,  # 学分上限；超出部分在统计栏标红
    },
    "layout": {
        "margin": 10,       # 面板四周留白
        "spacing": 10,      # 面板内控件间距
        "scroll_pad": 24,   # 课表最大宽度计算时的滚动条+边框预留
    },
    "export": {
        "scale": 4,  # 导出 PNG 的超采样倍数
    },
    "window": {
        "width": 1500,
        "height": 800,
        "handle_width": 8,
        "schedule_min_width": 360,
        "course_min_width": 280,
        "h_min_height": 150,
        "info_min_height": 120,
        "splitter_h_sizes": [780, 720],
        "splitter_v_sizes": [650, 150],
        "h_stretch": [6, 4],
        "v_stretch": [7, 3],
    },
    "dialog": {
        "settings_width": 780,
        "settings_height": 700,
    },
}


def _deep_merge(base, override):
    """递归合并：dict 深合并，list/标量以 override 为准。"""
    out = dict(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


class AppConfig:
    """config.json 的唯一读写器。全量 round-trip，分区访问。

    config.json 是唯一数据来源；缺失或键不全时与 DEFAULT_CONFIG 深合并回退。
    course_columns 由 SettingsDialog 直接读写（property），其余分区只读使用。
    """

    def __init__(self, config_file='config.json'):
        self.config_file = Path(config_file)
        self._data = {}
        self.load_config()

    def load_config(self):
        data = {}
        if self.config_file.exists():
            data = self._read_json(self.config_file)
        elif self._seed_from_example():
            # 已从示例复制生成 config.json，读取复制出来的文件
            data = self._read_json(self.config_file)
        else:
            logger.info("配置文件 %s 不存在，使用默认配置", self.config_file)
        self._data = _deep_merge(DEFAULT_CONFIG, data)

    def _read_json(self, path):
        """读取 JSON 配置；失败时记日志并返回空 dict（回退默认配置）。"""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except json.JSONDecodeError as e:
            logger.warning("配置文件 %s 解析失败，使用默认配置：%s", path, e)
        except OSError as e:
            logger.warning("配置文件 %s 读取失败，使用默认配置：%s", path, e)
        return {}

    def _seed_from_example(self):
        """config.json 缺失时，复制同目录的 config.example.json 兜底。

        复制成功返回 True（调用方随后读取复制出的文件）；示例不存在或
        复制失败返回 False，走 DEFAULT_CONFIG 默认配置。
        """
        example = self.config_file.with_name("config.example.json")
        if not example.exists():
            logger.info("示例配置 %s 也不存在，使用内置默认配置", example)
            return False
        try:
            shutil.copyfile(example, self.config_file)
        except OSError as e:
            logger.warning("从 %s 复制配置失败，使用内置默认配置：%s", example, e)
            return False
        logger.info("配置文件 %s 不存在，已从 %s 复制生成",
                    self.config_file, example)
        return True

    def save_config(self):
        with open(self.config_file, 'w', encoding='utf-8') as f:
            json.dump(self._data, f, ensure_ascii=False, indent=4)

    # ---- course_columns（SettingsDialog 读写）----

    @property
    def course_columns(self):
        return self._data.get("course_columns", [])

    @course_columns.setter
    def course_columns(self, value):
        self._data["course_columns"] = list(value)

    def get_visible_columns(self):
        """返回可见列的定义列表（每项含 name / field / width）。"""
        return [c for c in self.course_columns if c.get("visible")]

    # ---- 分区只读访问 ----

    @property
    def files(self):
        return self._data.get("files", {})

    @property
    def course(self):
        return self._data.get("course", {})

    @property
    def hdu(self):
        return self._data.get("hdu", {})

    @property
    def log(self):
        return self._data.get("log", {})

    @property
    def table(self):
        return self._data.get("table", {})

    @property
    def info_table(self):
        return self._data.get("info_table", {})

    def info_columns(self):
        """信息面板列定义（list[dict]，每项含 name/field/width）。"""
        return self.info_table.get("columns", [])

    def info_row_height(self):
        return self.info_table.get("row_height", 28)

    def info_max_width(self):
        """0 = 跟随上方课表网格宽度；>0 = 固定上限。"""
        return self.info_table.get("max_width", 0)

    @property
    def schedule(self):
        return self._data.get("schedule", {})

    @property
    def layout(self):
        return self._data.get("layout", {})

    @property
    def export(self):
        return self._data.get("export", {})

    @property
    def window(self):
        return self._data.get("window", {})

    @property
    def dialog(self):
        return self._data.get("dialog", {})

    # ---- 转换辅助（JSON 结构 -> 运行时结构）----

    def period_times(self):
        """JSON 字符串键 -> {int 节次: (start, end)}。"""
        raw = self.schedule.get("period_times", {})
        return {int(k): (tuple(v) if isinstance(v, list) else v)
                for k, v in raw.items()}

    def weekday_always(self):
        """-> set[int]。"""
        return set(self.schedule.get("weekday_always", []))
