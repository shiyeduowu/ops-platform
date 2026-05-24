# -*- coding: utf-8 -*-
"""公共工具函数"""


def next_version(current: str | None) -> str:
    """
    计算下一个配置版本号

    Args:
        current: 当前版本号，如 "v1", "v2", "v1.1"

    Returns:
        下一个版本号
    """
    if not current:
        return "v1"
    if current.startswith("v") and current[1:].isdigit():
        return f"v{int(current[1:]) + 1}"
    return f"{current}.1"
