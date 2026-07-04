import json


def sanitize_for_json(obj):
    """递归处理对象，将 JSON 不可序列化的类型替换为可读占位符。

    - bytes → "bytes[size]"
    - 其他类型由 json.dumps(default=str) 兜底处理
    """
    if isinstance(obj, bytes):
        return f"bytes[{len(obj)}]"
    elif isinstance(obj, dict):
        return {k: sanitize_for_json(v) for k, v in obj.items()}
    elif isinstance(obj, (list, tuple)):
        sanitized = [sanitize_for_json(item) for item in obj]
        return type(obj)(sanitized)
    return obj


def to_json(obj) -> str:
    """序列化为 JSON 字符串。失败则抛异常。

    用于关键数据路径（node_output、initial_context 等需要反序列化还原的场景）。
    """
    return json.dumps(obj, ensure_ascii=False, default=str)


def to_json_safe(obj) -> str:
    """序列化为 JSON 字符串，失败则 str() 兜底。

    用于纯日志/辅助信息路径（pipeline_output、runtime_info 等只展示不还原的场景）。
    """
    try:
        return json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        return str(obj)
