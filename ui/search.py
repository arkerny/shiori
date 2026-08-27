"""课程搜索语法：解析与匹配（纯逻辑，不依赖 Qt）。

语法概览（优先级 ! > | > 空格，即 非 > 或 > 且）：

  空格 → 且（AND）    计算机网络 肖周芳 = 同时包含“计算机网络”与“肖周芳”
  |    → 或（OR）      肖周|王晓 = 包含“肖周”或“王晓”
  !    → 非（NOT）     !肖周芳 = 不包含“肖周芳”；!1-2节 = 不包含“1-2节”

宽容：先剥离 | 两侧空格再解析，故 “肖周 | 王晓 | 赵云” 同样有效。
  “肖周|王晓 赵云”    = (肖周 OR 王晓) AND 赵云
  “肖周 | 王晓 | 赵云” = 肖周 OR 王晓 OR 赵云

作用域：! 仅对“课程名 / 教师姓名 / 教师工号 / 上课时间 / 校区”生效——例如
        !实验 排除课程名含“实验”者、!下沙 排除该校区课程；! 不对“开课学院 /
        教学班名称 / 教学班组成 / 课程代码 / 学分 / 其它可见字段”生效。
        | 仅对“时间 / 教师”字段有效，即含 | 的组不会命中课程名等——
        例如“计网|数据库”在时间/教师中找不到，结果为不匹配。

匹配模式（按字段）：
  子序列：课程名(kcmc)、开课学院(kkbm)，支持简写——“计网”→“计算机网络”、“计院”→“计算机学院”
  包含  ：教师姓名(jsmc)——中文模糊“肖周”匹配“肖周芳”，且支持拼音首字母
          缩写（前缀严格，“肖周芳”->xzf，“xz”命中、“xzf”命中、“xf”不命中）
          （任课教师 jzgxx 含学院括注等噪声，不参与搜索）
  包含  ：校区(xiaoqmc)，模糊
  全文  ：教师工号(jgh，多工号如“01034,41015”拆开后逐个全文匹配)、课程代码(kch)、
          学分(xf)，必须整串相等（大小写不敏感）
  教学班：教学班名称(jxbmc)，有无学年学期前缀的全文匹配——
          “A0100591-01” 与 “(2026-2027-1)-A0100591-01” 互为可搜
  班级号：教学班组成(jxbzc)，按分号拆分后对单个班级号全文匹配——
          值“23010111;23010112”可用“23010111”命中，但“2301011”不行
  时间  ：上课时间(sksj)，星期⇄周 归一后包含

可见性：课程名/开课学院/教师(含工号)/时间/校区/课程代码/教学班名称/教学班组成/学分
        即使列被隐藏也参与搜索；其余字段仅当列可见时参与（避免隐藏编号字段误命中）。
        教师姓名与教师工号视作同一教师类，搜其一即可命中。
"""

import re

try:
    from pypinyin import lazy_pinyin, Style as _PinyinStyle
    _HAS_PINYIN = True
except ImportError:  # 未装 pypinyin 时静默降级，教师名仍按中文包含匹配
    _HAS_PINYIN = False

_PINYIN_CACHE = {}  # value(str) -> 首字母串，教师名重复率高，缓存避免重复计算

# 多教师分隔符：逗号（中英文）、顿号、分号、斜杠、空白
_NAME_SEPS = re.compile(r"[,，、;；/\s]+")


def _pinyin_initials(value):
    """返回汉字串的拼音首字母（小写），如“肖周芳”->“xzf”。非汉字字符原样保留。"""
    if not _HAS_PINYIN:
        return ""
    cached = _PINYIN_CACHE.get(value)
    if cached is not None:
        return cached
    parts = lazy_pinyin(value, style=_PinyinStyle.FIRST_LETTER, errors="default")
    initials = "".join(parts).lower()
    _PINYIN_CACHE[value] = initials
    return initials


def _teacher_initials_hit(value, token):
    """多位教师时按分隔符拆名，任一教师的首字母以 token 为前缀即命中。

    整串计算会把分隔符混进缩写且只能匹配第一位教师，如
    “诸葛雯,张婷婷”整串 ->“zgw,ztt”，查“ztt”（第二位）无法前缀命中；
    拆名后各自 ->“zgw”/“ztt”，两位均可查。
    """
    for name in _NAME_SEPS.split(value):
        if name and _pinyin_initials(name).startswith(token):
            return True
    return False


def _strip_pipe_spaces(text):
    """剥离 | 两侧的空白（含空格/制表/换行等），使 “a | b | c” 视作 “a|b|c”（规则B）。

    | 周围的空白无语义；而真正分隔 AND 项的空白必然出现在 | 组之外。
    故逐字符扫描，仅删除紧邻 | 的空白字符。
    """
    out = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch == "|":
            while out and out[-1].isspace():  # 去掉左侧尾随空白
                out.pop()
            out.append("|")
            i += 1
            while i < n and text[i].isspace():  # 跳过右侧空白
                i += 1
            continue
        out.append(ch)
        i += 1
    return "".join(out)


def _is_subsequence(needle, hay):
    """needle 是否为 hay 的子序列（支持课程名缩写，如“计网”→“计算机网络”）。"""
    it = iter(hay)
    return all(ch in it for ch in needle)


def _norm_time(s):
    """时间字段归一：星期⇄周，使“周一”匹配“星期一…”。"""
    return s.replace("星期", "周")


def _strip_xnjq(s):
    """剥离教学班名称开头的学年学期前缀，如“(2026-2027-1)-A0100591-01”→“A0100591-01”。

    用于“有无学年学期前缀全文匹配”：搜索词与原值或去前缀值之一相等即命中。
    """
    return re.sub(r"^\([^()]*\)-", "", s)


def parse_query(text):
    """将搜索文本解析为 AND 项列表。

    返回 list[group]，每个 group = (is_operator, [(negated, token), ...])。
    - group 之间为且（AND）；group 内为或（OR）。
    - is_operator：该组出现 | —— 整组只在时间/教师字段匹配（| 不支持课程名）。
      独立的 !（无 |）不算 operator，仍在全部字段匹配（含课程名），仅取反。
    优先级 ! > | > 空格；规则B：先剥离 | 两侧空格。
    """
    if not isinstance(text, str):
        return []
    # 全角符号归一
    t = text.replace("！", "!").replace("｜", "|").replace("　", " ")
    t = _strip_pipe_spaces(t)
    and_parts = [p for p in t.split() if p]
    groups = []
    for part in and_parts:
        or_parts = part.split("|")
        has_pipe = len(or_parts) > 1
        terms = []
        for raw in or_parts:
            negated = False
            while raw.startswith("!"):
                negated = not negated
                raw = raw[1:]
            token = raw.lower()
            if token:
                terms.append((negated, token))
        if not terms:
            continue
        is_operator = has_pipe  # 仅 | 限定到时间/教师；独立 ! 仍在全部字段匹配
        groups.append((is_operator, terms))
    return groups


def field_categories(columns):
    """把列分类为 (mode, fields, allow_operator, allow_not) 规格列表。

    columns: list[dict]，每项含 {name, field, visible}（建议传全部列，非仅可见列）。
    特殊字段无论是否可见都纳入；普通字段仅可见时纳入，以免隐藏编号字段误命中。

    mode 取值：
      subseq   课程名(kcmc)/开课学院(kkbm)，子序列匹配（支持简写）
      teacher  教师姓名(jsmc)，中文模糊包含 + 拼音首字母缩写（前缀严格）
               （任课教师 jzgxx 含学院括注等噪声，不参与搜索）
      contains 校区(xiaoqmc)/其它可见字段，模糊包含
      teacher_id 教师工号(jgh)，多工号按分隔符拆开后逐个全文匹配
      exact    课程代码(kch)/学分(xf)，全文匹配
      jxbmc    教学班名称，有无学年学期前缀的全文匹配
      jxbzc    教学班组成，按分号拆分后对单个班级号全文匹配
      time     上课时间，星期⇄周 归一后包含匹配
    allow_operator：是否允许出现在 | 组（| 仅限时间/教师）。
    allow_not：! 是否对该类生效。! 仅对 课程名/教师(含工号)/时间/校区 生效，
      不对 开课学院/教学班名称/教学班组成/课程代码/学分/其它可见字段 生效。
    """
    groups = {}  # (mode, allow_op, allow_not) -> list[field]，保序去重

    def add(field, mode, allow_op, allow_not):
        lst = groups.setdefault((mode, allow_op, allow_not), [])
        if field not in lst:
            lst.append(field)

    for c in columns:
        field = c.get("field", "")
        name = c.get("name", "")
        if not field:
            continue
        if field == "kcmc" or name in ("课程名称", "课程名"):
            add(field, "subseq", False, True)            # 课程名：! 可用
        elif field == "kkbm" or "学院" in name:
            add(field, "subseq", False, False)           # 开课学院：! 不可用
        elif field == "jgh" or name == "教师工号":
            add(field, "teacher_id", True, True)           # 多工号按分隔符拆开全文匹配
        elif field == "jsmc" or name == "教师姓名":
            add(field, "teacher", True, True)
        elif field == "jzgxx" or name == "任课教师":
            pass  # jzgxx 含学院括注等噪声，不参与搜索（教师由 jsmc/jgh 覆盖）
        elif field == "sksj" or "时间" in name:
            add(field, "time", True, True)
        elif field == "xiaoqmc" or "校区" in name:
            add(field, "contains", False, True)         # 校区：! 可用
        elif field == "kch" or name == "课程代码":
            add(field, "exact", False, False)
        elif field == "jxbmc" or name in ("教学班名称", "教学班"):
            add(field, "jxbmc", False, False)
        elif field == "jxbzc" or name == "教学班组成":
            add(field, "jxbzc", False, False)
        elif field == "xf" or name == "学分":
            add(field, "exact", False, False)
        elif c.get("visible"):
            add(field, "contains", False, False)        # 其它可见：! 不可用
    return [(mode, fields, allow_op, allow_not)
            for (mode, allow_op, allow_not), fields in groups.items()]


def _hit_fields(course, token, fields, mode):
    """在指定字段集合中按匹配模式查找 token 是否命中某一字段。"""
    for f in fields:
        raw = course.get(f)
        if raw is None:  # 显式 null 视为空，避免 str(None)=="None" 造成误命中
            continue
        value = str(raw).lower()
        if not value:
            continue
        if mode == "subseq":
            if _is_subsequence(token, value):
                return True
        elif mode == "time":
            if _norm_time(token) in _norm_time(value):
                return True
        elif mode == "exact":
            if token == value:
                return True
        elif mode == "jxbmc":
            if token == value or token == _strip_xnjq(value):
                return True
        elif mode == "teacher":
            # 教师：中文模糊包含，或拼音首字母缩写（前缀严格，如“肖周芳”->xzf，“xz”命中，“xf”不命中）
            # 多位教师（逗号/顿号/分号分隔）时逐个教师匹配
            if token in value:
                return True
            if token.isascii() and token.isalpha() and _teacher_initials_hit(value, token):
                return True
        elif mode == "teacher_id":
            # 教师工号：全文匹配；多工号（如“01034,41015”）按分隔符拆开后逐个全文匹配
            if any(token == p.strip() for p in _NAME_SEPS.split(value)):
                return True
        elif mode == "jxbzc":
            if any(token == p.strip() for p in value.split(";")):
                return True
        else:  # contains
            if token in value:
                return True
    return False


def _group_matches(course, terms, is_operator, specs):
    """单个 AND 项（| 组）是否命中：组内为或。

    specs: field_categories 返回的 [(mode, fields, allow_op, allow_not)]。
    - is_operator（含 |）：仅使用 allow_op 为 True 的类（时间/教师）。
    - 取反项（!）：仅在该类 allow_not 为 True 时才参与，故 ! 不作用于
      开课学院/教学班名称/教学班组成/课程代码/学分/其它可见字段。
    """
    for negated, token in terms:
        hit = False
        for mode, fields, allow_op, allow_not in specs:
            if is_operator and not allow_op:
                continue
            if negated and not allow_not:
                continue
            if _hit_fields(course, token, fields, mode):
                hit = True
                break
        if negated:
            hit = not hit
        if hit:  # 组内或：任一命中即整组命中
            return True
    return False


def course_matches(course, groups, cats):
    """课程需命中全部 AND 项（组间且），每组内为或。

    对非 dict 的畸形数据条目直接判为不命中，避免 AttributeError 中断整次过滤。
    """
    if not isinstance(course, dict):
        return False
    for is_operator, terms in groups:
        if not _group_matches(course, terms, is_operator, cats):
            return False
    return True
