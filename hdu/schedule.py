"""个人选课情况（教务已选课）查询与保存。

接口来自「个人选课情况」页面的抓包（hdu/schedule_example.har）：
POST /jwglxt/xkcx/xkmdcx_cxXkmdcxIndex.html?doType=query&gnmkdm=N255010
响应 items 的字段与 shiori 的 files.jiaowu_courses 完全一致
（除课程信息外还含本人学籍信息，注意文件保管）。
结构与 course.py 对应：query_schedule 只管查询，fetch_schedule
负责登录（复用 client.login_with_config）+ 拉取 + 覆盖落盘。
"""

import json
import logging
import time
from pathlib import Path

from hdu.client import (LoginError, NOT_LOGGED_IN, as_int,
                        query_with_relogin, query_with_retry)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 30  # 个人已选课列表很小，秒级返回

_SCHEDULE_URL = ("https://newjw.hdu.edu.cn/jwglxt/xkcx/"
                 "xkmdcx_cxXkmdcxIndex.html?doType=query&gnmkdm=N255010")

# 浏览器实际发送的请求头（抓包记录）
_SCHEDULE_HEADERS = {
    "X-Requested-With": "XMLHttpRequest",
    "Referer": ("https://newjw.hdu.edu.cn/jwglxt/xkcx/"
                "xkmdcx_cxXkmdcxIndex.html?gnmkdm=N255010&layout=default"),
}


class ScheduleError(Exception):
    """选课情况查询失败（学年学期格式错误等）。"""


def query_schedule(client, xuenian, xueqi, timeout=DEFAULT_TIMEOUT):
    """查询个人选课情况，返回已选课程 dict 列表。

    xuenian: 学年，如 "2026"（秋季学期所在年份）
    xueqi:   学期，"1"=秋季 / "2"=春季
    timeout: 请求超时秒数（个人列表小，默认 30）
    """
    xqm = {"1": "3", "2": "12"}.get(xueqi)  # 学期内部码：1 -> 3，2 -> 12
    if xqm is None:
        raise ScheduleError('学期只能是 "1"（秋季）或 "2"（春季）')

    # 表单与抓包一一对应；查询条件留空即查本人全部已选课
    form = {
        "xnm": xuenian,
        "xqm": xqm,
        "kkxy_id": "",       # 开课学院
        "kclbdm": "",        # 课程类别
        "kcxzmc": "",        # 课程性质
        "kch": "",           # 课程号
        "kklxdm": "",        # 开课类型
        "kkzt": "1",         # 开课状态：只查「开课」
        "jxbmc": "",         # 教学班名称
        "jsxx": "",          # 教师信息
        "kcgsdm": "",        # 课程归属
        "xdbj": "",          # 选订标记
        "fxbj": "",          # 辅修标记
        "cxbj": "",          # 重修标记
        "zxbj": "",          # 免听标记（响应中为“是”=免听：课仍显示但周次算空闲）
        "sfzbh_kcflsj": "",  # 是否主办_课程分类筛选
        "cxlx": "",          # 查询类型
        "zyfx_id": "",       # 专业方向
        "xklc": "",          # 选课轮次
        "xkly": "",          # 选课来源
        "_search": "false",
        "nd": str(int(time.time() * 1000)),
        "queryModel.showCount": "999",  # 抓包为 15，放大防漏（已选课一般不超过几十门）
        "queryModel.currentPage": "1",
        "queryModel.sortName": "xkbjmc,xnmc,xqmc,kkxymc,kch,jxbmc,xh ",  # 末尾空格为抓包原文
        "queryModel.sortOrder": "asc",
        "time": "0",
    }

    result = client.post_form(_SCHEDULE_URL, form, timeout=timeout,
                              headers=_SCHEDULE_HEADERS)
    if NOT_LOGGED_IN in result:
        raise LoginError("登录已过期")
    try:
        return json.loads(result)["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        # 响应不是预期 JSON（多半是会话失效跳到了错误页），按登录过期处理
        raise LoginError("登录已过期（响应异常）")


def save_local_schedule(app_config, schedule):
    path = Path(app_config.files.get("jiaowu_courses", "jiaowu_schedule.json"))
    path.write_text(json.dumps(schedule, ensure_ascii=False, indent=2),
                    encoding="utf-8")


def fetch_schedule(app_config):
    """在线拉取个人选课情况并覆盖保存到 files.jiaowu_courses。

    何时更新由前端控制，这里不做本地缓存判断。
    容错：查询超时/网络错误自动重试（hdu.schedule_retries 次）；
    登录态过期交给 query_with_relogin 重登后整体重来。
    超时秒数由 hdu.schedule_timeout 配置（默认 30）。
    """
    hdu = app_config.hdu
    timeout = as_int(hdu.get("schedule_timeout"), DEFAULT_TIMEOUT)
    retries = max(0, as_int(hdu.get("schedule_retries"), 2))

    def query(client):
        return query_with_retry(
            lambda: query_schedule(client, hdu["xuenian"], hdu["xueqi"],
                                   timeout=timeout),
            retries, "个人课表查询", ScheduleError, step=2, max_wait=5)

    schedule = query_with_relogin(app_config, query)
    save_local_schedule(app_config, schedule)
    logger.info("已保存 %d 门已选课程到 %s",
                len(schedule), app_config.files.get("jiaowu_courses"))
    return schedule
