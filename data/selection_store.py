import json
import logging
import shutil

logger = logging.getLogger(__name__)


def load_selected_courses(path):
    """从 JSON 文件读取已选课程列表，返回 list[dict]。文件缺失或解析失败时返回空列表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.debug("已选课程文件不存在（首次启动属正常）：%s", path)
        return []
    except json.JSONDecodeError as e:
        logger.warning("已选课程文件解析失败，按空列表处理：%s（%s）", path, e)
        return []
    return data if isinstance(data, list) else []


def save_selected_courses(path, courses):
    """把已选课程列表（list[dict]，完整课程信息）写入 JSON 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(courses), f, ensure_ascii=False, indent=4)


def has_content(path):
    """已选课程文件是否已有内容：存在、可解析且为非空列表。

    解析失败或读取异常按“已有内容”保守处理——调用方据此绝不覆盖。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            text = f.read()
    except FileNotFoundError:
        return False
    except OSError:
        return True
    if not text.strip():
        return False
    try:
        return bool(json.loads(text))
    except json.JSONDecodeError:
        return True


def apply_audit_marks(selected, jiaowu_path, key_field="jxbmc"):
    """按教务个人课表把免听标记（zxbj）盖到已选课记录上，返回新列表。

    已选记录可能取自课程池（无 zxbj 字段），免听的权威来源是教务文件：
    在教务记录中的，zxbj 以教务为准；不在其中的，清掉记录上可能过期的
    标记（如早前保存遗留）。不修改入参、不写盘。
    """
    try:
        with open(jiaowu_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.debug("教务课表文件不存在，免听标记不生效：%s", jiaowu_path)
        return selected
    except json.JSONDecodeError as e:
        logger.warning("教务课表文件解析失败，免听标记不生效：%s（%s）", jiaowu_path, e)
        return selected
    except OSError as e:
        logger.warning("教务课表文件读取失败，免听标记不生效：%s（%s）", jiaowu_path, e)
        return selected
    if not isinstance(data, list):
        return selected
    by_key = {c.get(key_field, ""): c for c in data if isinstance(c, dict)}

    out = []
    for c in selected:
        if not isinstance(c, dict):
            out.append(c)
            continue
        src = by_key.get(c.get(key_field, ""))
        if src is not None:
            zxbj = str(src.get("zxbj", "")).strip()
            if zxbj:
                c = {**c, "zxbj": zxbj}
            elif "zxbj" in c:
                c = {k: v for k, v in c.items() if k != "zxbj"}
        elif "zxbj" in c:  # 不在教务记录中：清掉过期标记
            c = {k: v for k, v in c.items() if k != "zxbj"}
        out.append(c)
    return out


def seed_from_jiaowu(selected_path, jiaowu_path):
    """已选课程无内容时，用教务课表文件整文件复制作初始已选。

    两者同为课程 dict 列表（格式一致），直接复制。已选已有内容时
    绝不改动；教务文件缺失/为空/解析异常、复制失败时返回 False。
    """
    if has_content(selected_path):
        return False
    try:
        with open(jiaowu_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, list) or not data:
        return False
    try:
        shutil.copyfile(jiaowu_path, selected_path)
    except OSError as e:
        logger.warning("从 %s 复制到 %s 失败：%s", jiaowu_path, selected_path, e)
        return False
    logger.info("已选课程无内容，已从教务课表 %s 复制初始化", jiaowu_path)
    return True
