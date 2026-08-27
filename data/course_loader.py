import json
import logging

logger = logging.getLogger(__name__)


def load_courses_from_file(path):
    """从 JSON 文件加载课程数据，返回 list[dict]。

    文件不存在或解析失败时返回空列表，保证调用方总能拿到一个可迭代的列表。
    """
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        logger.debug("课程池文件不存在（首次启动属正常）：%s", path)
        return []
    except json.JSONDecodeError as e:
        logger.warning("课程池文件解析失败，按空课程池处理：%s（%s）", path, e)
        return []
    return data if isinstance(data, list) else []
