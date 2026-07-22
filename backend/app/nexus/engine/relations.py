"""Relation-graph utilities retaining direction, multiplicity and integrity."""

from __future__ import annotations

from collections import deque
from typing import Optional

from nexus.core.models import ConceptKind
from nexus.core.relations import RelationContract


def relation_edges(ontology) -> list[RelationContract]:
    out: list[RelationContract] = []
    for concept in ontology.list_concepts():
        if concept.kind != ConceptKind.relation:
            continue
        attrs = concept.attrs or {}
        payload = {
            "id": concept.id,
            "name": concept.name,
            "from": attrs.get("from"),
            "to": attrs.get("to"),
            "multiplicity": attrs.get("multiplicity"),
            "integrity": attrs.get("integrity"),
            "temporal": attrs.get("temporal"),
            "semantics": concept.semantics,
            "synonyms": concept.synonyms,
        }
        try:
            out.append(RelationContract.model_validate(payload))
        except Exception:
            continue
    return out


def _adjacency(edges: list[RelationContract]) -> dict[str, list[tuple[str, RelationContract]]]:
    graph: dict[str, list[tuple[str, RelationContract]]] = {}
    for edge in edges:
        frm, to = edge.from_.entity, edge.to.entity
        graph.setdefault(frm, []).append((to, edge))
        graph.setdefault(to, []).append((frm, edge))
    return graph


def _bfs_path(adjacency, sources: set[str], targets: set[str]):
    visited = set(sources)
    parent: dict[str, tuple[str, RelationContract]] = {}
    queue = deque(sources)
    while queue:
        current = queue.popleft()
        if current in targets:
            path = []
            node = current
            while node in parent:
                previous, relation = parent[node]
                path.append((node, relation))
                node = previous
            path.reverse()
            return path
        for neighbor, relation in adjacency.get(current, []):
            if neighbor not in visited:
                visited.add(neighbor)
                parent[neighbor] = (current, relation)
                queue.append(neighbor)
    return None


def join_tree(ontology, required) -> Optional[tuple[list[str], list[RelationContract]]]:
    """Return a deterministic relation tree connecting required entities."""
    required_entities = list(dict.fromkeys(required))
    if not required_entities:
        return [], []
    adjacency = _adjacency(relation_edges(ontology))
    ordered = [required_entities[0]]
    tree_nodes = {required_entities[0]}
    tree_edges: list[RelationContract] = []
    remaining = set(required_entities[1:])
    while remaining:
        path = _bfs_path(adjacency, tree_nodes, remaining)
        if path is None:
            return None
        for entity, relation in path:
            if entity not in tree_nodes:
                tree_nodes.add(entity)
                ordered.append(entity)
                tree_edges.append(relation)
        remaining -= tree_nodes
    return ordered, tree_edges


def connected(ontology, required) -> bool:
    return join_tree(ontology, required) is not None
