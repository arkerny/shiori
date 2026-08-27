"""任务落实课程查询与保存。

对应 Go 版的 pkg/course/getCourse.go 与 client.GetCourse：
- query_courses：调任务落实查询接口，直接取响应 items 的全部字段
- fetch_courses：登录教务系统（cookie 免登录或账号密码），在线拉取并
  覆盖保存本地课程池。是否需要更新由前端控制，这里不做本地缓存判断。
- 课程池保存为纯数组（shiori 的 data/course_loader 直接读 list；
  Go 版导出 Excel 的步骤 shiori 不需要，未移植）
"""

import json
import logging
import time
from pathlib import Path

from hdu.client import (LoginError, NOT_LOGGED_IN, as_int,
                        query_with_relogin, query_with_retry)

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # 服务端要聚合全量课程，实测约 2 分钟，高峰时更久


class CourseError(Exception):
    """课程查询失败（接口未开放、学年学期格式错误等）。"""


# 任务落实查询的表单字段全集（与浏览器抓包一一对应，顺序同抓包）。
# 服务端要求字段齐全，未用到的必须以空串提交。缺字段或值不符时，
# 服务端会按教师拆行返回（双教师课程每个老师一条），字段集也会变化。
_COURSE_FORM_KEYS = [
    "xb_id", "kkbm", "kch", "kcfzr", "xy_xb_id", "xsxy", "zyh_id", "bh_id",
    "zyfx_id", "njdm_id", "xsdm", "jxdd", "kklxdm", "xqh_id", "xkbj", "kkzt",
    "kclbdm", "kcgsdm", "kcxzdm", "apksfsdm", "zwlbm", "zcjbdm", "ksz",
    "ksfsdm", "khfsdm", "cxfs", "js_xb_id", "jsssbm", "zcm", "xbdm",
    "cdlb_id", "cdejlb_id", "jxbmc", "sfzjxb", "sfhbbj", "zymc", "xnmc",
    "xqmc", "kkxymc", "jgmc", "njmc", "sfpk", "sfwp", "ywtk", "sfddsk",
    "skfs", "dylx", "jzglbm", "jxms", "skpt", "sfhxkc", "sfggjckc", "sfxwkc",
    "sknr", "bz", "xkbz", "sfzj", "qsz", "zykfkcbj_cx", "sfgssxbk_cx", "zzz",
    "xf", "jys_id", "sfmt", "glms", "drcx_id", "sfdxqskjs", "sfapdjs",
    "sylxdm", "bzkzym", "xnm", "xqm", "js", "kclxdm", "_search", "nd",
    "queryModel.showCount", "queryModel.currentPage", "queryModel.sortName",
    "queryModel.sortOrder", "time",
]

_COURSE_URL = "https://newjw.hdu.edu.cn/jwglxt/rwlscx/rwlscx_cxRwlsIndex.html?doType=query&gnmkdm=N1548"

# 教师相关字段：按教学班汇总时多位教师的值逐位拼接。
# jzgxx 用 ';'，其余用 ','（与教务系统页面的汇总展示一致）。
_TEACHER_JOIN_FIELDS = {
    "jzgxx": ";",
    "jsmc": ",", "jgh": ",", "jscsrq": ",", "jsxb": ",", "jsbm": ",",
    "zcmc": ",", "xykh": ",", "zcjbmc": ",", "zwlbmc": ",", "js_xbxx": ",",
    "sfzj": ",",
}


def merge_teacher_rows(items):
    """把按教师拆分的行合并回按教学班汇总（以教务系统页面展示为准）。

    同一教学班每位教师一行时，教师相关字段按位拼接（见
    _TEACHER_JOIN_FIELDS），非教师字段取第一行，row_id 重新编号。
    若响应本身就是汇总行（每个教学班一行），本函数为无操作。
    """
    groups = {}
    order = []
    for item in items:
        key = item.get("jxbmc", "")
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(item)

    merged = []
    for i, key in enumerate(order, start=1):
        rows = groups[key]
        row = dict(rows[0])
        if len(rows) > 1:
            for field, sep in _TEACHER_JOIN_FIELDS.items():
                if field in row:
                    row[field] = sep.join(str(r.get(field, "")) for r in rows)
        row["row_id"] = i
        merged.append(row)
    return merged


def query_courses(client, xuenian, xueqi, jxbmc="", timeout=DEFAULT_TIMEOUT):
    """
    查询「任务落实」课程列表，返回按教学班汇总的课程 dict 列表。
    xuenian: 学年，如 "2026"（秋季学期所在年份）
    xueqi:   学期，"1"=秋季 / "2"=春季
    jxbmc:   教学班名称模糊搜索，空 = 全量
    timeout: 请求超时秒数（服务端聚合慢，默认 600）
    """
    xqm = {"1": "3", "2": "12"}.get(xueqi)  # 学期内部码：1 -> 3，2 -> 12
    if xqm is None:
        raise CourseError('学期只能是 "1"（秋季）或 "2"（春季）')

    form = dict.fromkeys(_COURSE_FORM_KEYS, "")  # 其余查询条件全部留空
    form.update({
        "xnmc": f"{xuenian}-{int(xuenian) + 1}",  # 2026 -> 2026-2027
        "xqmc": xueqi,
        "xnm": xuenian,
        "xqm": xqm,
        "jxbmc": jxbmc,
        "cxfs": "1",        # 查询方式：按教学班汇总（双教师课程不拆行）
        "ywtk": "0",
        "sfddsk": "0",
        "_search": "false",
        "nd": str(int(time.time() * 1000)),
        "queryModel.showCount": "9999",  # 抓包为 15（分页）；一次取全量
        "queryModel.currentPage": "1",
        "queryModel.sortName": " ",      # 抓包原文：单个空格
        "queryModel.sortOrder": "asc",
        "time": "0",
    })

    result = client.post_form(_COURSE_URL, form, timeout=timeout)
    if NOT_LOGGED_IN in result:
        raise LoginError("登录已过期")
    if "无功能权限" in result:
        raise CourseError("任务落实查询未开放")
    try:
        items = json.loads(result)["items"]
    except (json.JSONDecodeError, KeyError, TypeError):
        # 响应不是预期 JSON（多半是会话失效跳到了错误页），按登录过期处理
        raise LoginError("登录已过期（响应异常）")
    return merge_teacher_rows(items)


# ---- 本地保存（对应 Go 版 SaveCourse）----

def save_local_courses(app_config, courses):
    path = Path(app_config.files.get("course_pool", "course.json"))
    path.write_text(json.dumps(courses, ensure_ascii=False, indent=2),
                    encoding="utf-8")


# ---- 对外入口（对应 Go 版 GetCourse 的在线分支）----

def fetch_courses(app_config):
    """在线拉取课程池并覆盖保存到 files.course_pool。

    何时更新由前端控制，这里不做本地缓存判断。
    容错：查询超时/网络错误自动重试（hdu.course_retries 次）；
    登录态过期交给 query_with_relogin 重登后整体重来。
    超时秒数由 hdu.course_timeout 配置（默认 600）。
    """
    hdu = app_config.hdu
    timeout = as_int(hdu.get("course_timeout"), DEFAULT_TIMEOUT)
    retries = max(0, as_int(hdu.get("course_retries"), 2))

    def query(client):
        return query_with_retry(
            lambda: query_courses(client, hdu["xuenian"], hdu["xueqi"],
                                  timeout=timeout),
            retries, "课程查询", CourseError)

    logger.info("正在从教务系统获取课程（服务端聚合慢，约 2 分钟，请耐心等待）...")
    courses = query_with_relogin(app_config, query)
    save_local_courses(app_config, courses)
    logger.info("已保存 %d 门课程到 %s",
                len(courses), app_config.files.get("course_pool"))
    return courses
