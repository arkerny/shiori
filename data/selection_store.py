import json


def load_selected_courses(path):
    """从 JSON 文件读取已选课程列表，返回 list[dict]。文件缺失或解析失败时返回空列表。"""
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def save_selected_courses(path, courses):
    """把已选课程列表（list[dict]，完整课程信息）写入 JSON 文件。"""
    with open(path, "w", encoding="utf-8") as f:
        json.dump(list(courses), f, ensure_ascii=False, indent=4)
