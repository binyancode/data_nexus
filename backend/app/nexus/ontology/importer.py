"""importer：从一个 sql resolver 探测选定的表，产出可并入画板的 graph 片段。

不写 DB——返回 JSON 片段给前端并入画板，再由前端整份保存（BFF）。
- 每张表 → 一个 entity（+ table 落点 + key）
- 每列   → 一个 attribute（+ column 落点）
- 选中集合内的外键 → relation
"""

from __future__ import annotations

import re


def _local(table: str) -> str:
    """schema.table → 去 schema 的本地名（用于 id）。"""
    name = table.split(".")[-1]
    return re.sub(r"[^A-Za-z0-9_]", "_", name)


# 常见度量列（无 role，作指标输入）；其余默认作维度可过滤
_MEASURE_HINT = re.compile(r"(amount|amt|cost|qty|quantity|price|revenue|sales|total|sum|count|num)", re.I)


def build_fragment(resolver_name: str, describe: dict, primary_keys: dict,
                   foreign_keys: list, tables: list[str]) -> dict:
    """产出 {entities, relations}（metrics/derivations/actions 由用户后加）。"""
    selected = set(tables)
    entities = []
    ent_by_table: dict[str, str] = {}

    for i, table in enumerate(tables):
        cols = describe.get(table, [])
        pk = primary_keys.get(table, [])
        eid = f"entity.{_local(table)}"
        ent_by_table[table] = eid
        attributes = []
        for c in cols:
            col = c["column"]
            aid = f"attribute.{_local(table)}.{col}"
            is_pk = col in pk
            role = None if (is_pk or _MEASURE_HINT.search(col)) else col
            attributes.append({
                "id": aid, "name": col, "column": col,
                "role": role, "synonyms": [], "semantics": None,
            })
        entities.append({
            "id": eid, "name": _local(table), "semantics": None, "synonyms": [],
            "resolver": resolver_name, "table": table,
            "key": pk[0] if pk else None,
            "attributes": attributes,
            "layout": {"x": 80 + (i % 3) * 340, "y": 80 + (i // 3) * 320},
        })

    relations = []
    for fk in foreign_keys:
        ft, tt = fk["from_table"], fk["to_table"]
        if ft in selected and tt in selected and ft != tt:
            fe, te = ent_by_table[ft], ent_by_table[tt]
            relations.append({
                "id": f"relation.{_local(ft)}_{_local(tt)}",
                "name": f"{_local(ft)}-{_local(tt)}", "semantics": None, "synonyms": [],
                "from_entity": fe, "from_key": fk["from_col"],
                "to_entity": te, "to_key": fk["to_col"],
            })

    return {"entities": entities, "relations": relations}
