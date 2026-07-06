"""本体预检查：在"使用本体"前校验其可用性。

返回问题列表（空列表 = 通过）。规则可持续扩展；当前规则：
  1. 本体必须至少配置一个 resolver（数据源 / 能力源），否则无法使用。
  2. 本体引用的 resolver 必须存在且已启用（在 registry 内）。
"""

from __future__ import annotations


def ontology_resolver_names(graph: dict) -> set[str]:
    """本体使用的 resolver 名集合。

    优先取显式的 graph.resolvers（{name,type} 或 name）；
    兼容老本体：从实体的 resolver 绑定推导（老本体无 resolvers 字段）。
    """
    names: set[str] = set()
    if not isinstance(graph, dict):
        return names
    for r in graph.get("resolvers", []) or []:
        if isinstance(r, dict) and r.get("name"):
            names.add(r["name"])
        elif isinstance(r, str):
            names.add(r)
    for e in graph.get("entities", []) or []:
        if e.get("resolver"):
            names.add(e["resolver"])
    return names


def validate_ontology(onto, registry=None) -> list[str]:
    """预检查本体，返回问题列表（空 = 通过）。"""
    problems: list[str] = []
    graph = getattr(onto, "graph", None) or {}

    # 规则 1：必须至少有一个 resolver（数据源 / 能力源）
    names = ontology_resolver_names(graph)
    if not names:
        problems.append("本体未配置任何数据源或能力源（resolver），无法使用。请先导入实体或挂载能力源。")
        return problems  # 无源时后续规则无意义，提前返回

    # 规则 2：引用的 resolver 必须存在且启用
    if registry is not None:
        missing = sorted(n for n in names if registry.resolver(n) is None)
        if missing:
            problems.append("本体引用的源不存在或未启用：" + "、".join(missing))

    return problems
