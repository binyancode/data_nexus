"""关系图工具：在本体「实体-关系」图上，求把一组实体连通的连接树（可含中间表）。

- 编译器用它做连通性校验（支持**间接关系**：A—B—C 只有 A、C 被引用也算连通）。
- 优化器用它生成 JOIN：把路径上的**中间表**也连进来；并据整条链上的
  resolver 判定是否跨源（链上任一实体非同源即按跨源处理）。

采用「最短路启发式」求 Steiner 树近似：以第一个实体为根，反复用 BFS 把最近的
一个尚未连入的目标实体（连同其路径上的中间实体）并进树，直至覆盖全部目标。
"""

from __future__ import annotations

from collections import deque
from typing import Optional

# 一条关系边：(from_entity, from_key, to_entity, to_key)


def relation_edges(ontology) -> list:
    """列出本体里所有有效的 relation 边。"""
    out: list[tuple] = []
    for c in ontology.list_concepts():
        kind = c.kind.value if hasattr(c.kind, "value") else str(c.kind)
        if kind != "relation":
            continue
        a = c.attrs or {}
        fe, te = a.get("from_entity"), a.get("to_entity")
        fk, tk = a.get("from_key"), a.get("to_key")
        if fe and te and fk and tk:
            out.append((fe, fk, te, tk))
    return out


def _adjacency(edges: list) -> dict:
    adj: dict[str, list] = {}
    for e in edges:
        fe, _fk, te, _tk = e
        adj.setdefault(fe, []).append((te, e))
        adj.setdefault(te, []).append((fe, e))
    return adj


def _bfs_path(adj: dict, sources: set, targets: set) -> Optional[list]:
    """从 sources 集出发 BFS，找最近的一个 targets 实体，返回该目标回到 source 的路径：
    list of (entity, edge)，不含 source 本身，靠近 source 的在前。找不到返回 None。"""
    visited = set(sources)
    parent: dict = {}                       # entity -> (prev_entity, edge)
    q = deque(sources)
    while q:
        cur = q.popleft()
        if cur in targets:
            path = []
            node = cur
            while node in parent:
                prev, edge = parent[node]
                path.append((node, edge))
                node = prev
            path.reverse()
            return path
        for nb, edge in adj.get(cur, []):
            if nb not in visited:
                visited.add(nb)
                parent[nb] = (cur, edge)
                q.append(nb)
    return None


def join_tree(ontology, required) -> Optional[tuple[list, list]]:
    """求把 required 里所有实体连通的一棵树（含必要的中间实体）。

    返回 (ordered_entities, tree_edges)：
      - ordered_entities：按连接顺序排列的实体（含中间实体），第一个是根；其后每个
        实体都由 tree_edges 里对应的边连到前面已在树中的某个实体。
      - tree_edges[i] 连接 ordered_entities[i+1] 到某个更早的实体（边=(fe,fk,te,tk)）。
    存在不可达的 required 实体（无任何通路）→ 返回 None。
    """
    req = list(dict.fromkeys(required))     # 去重保序
    if not req:
        return [], []
    adj = _adjacency(relation_edges(ontology))

    ordered = [req[0]]
    tree_nodes = {req[0]}
    tree_edges: list = []
    remaining = set(req[1:])
    while remaining:
        path = _bfs_path(adj, tree_nodes, remaining)
        if path is None:
            return None
        for ent, edge in path:
            if ent not in tree_nodes:
                tree_nodes.add(ent)
                ordered.append(ent)
                tree_edges.append(edge)
        remaining -= tree_nodes
    return ordered, tree_edges


def connected(ontology, required) -> bool:
    """required 里的实体能否（含间接关系）全部连通。"""
    return join_tree(ontology, required) is not None
