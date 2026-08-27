"""HDU 教务系统（newjw）对接模块。

移植自 HDU-KillCourse（Go）的 client/、pkg/login/ 与 pkg/course/。
常用方式：

    from hdu import JwClient, fetch_courses
    from config.app_config import AppConfig

    # 一步到位：登录（cookie 免登录或账号密码），在线拉取并覆盖 course.json
    courses = fetch_courses(AppConfig())

    # 或自行控制会话：登录一次（newjw 优先，失败自动换 cas），多次查询
    client = JwClient()
    client.login(newjw={"username": "学号", "password": "密码"})
    courses = query_courses(client, "2026", "1")
    mine = query_schedule(client, "2026", "1")
"""

from hdu.client import (JwClient, LoginError, NOT_LOGGED_IN,
                        aes_ecb_encrypt, rsa_encrypt,
                        as_int, login_with_config,
                        query_with_relogin, query_with_retry)
from hdu.course import CourseError, fetch_courses, query_courses
from hdu.schedule import ScheduleError, fetch_schedule, query_schedule

__all__ = [
    "JwClient", "LoginError", "CourseError", "ScheduleError",
    "NOT_LOGGED_IN", "rsa_encrypt", "aes_ecb_encrypt",
    "as_int", "login_with_config", "query_with_relogin", "query_with_retry",
    "fetch_courses", "query_courses", "fetch_schedule", "query_schedule",
]
