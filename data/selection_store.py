import json
import logging

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
