"""Semantic binding and logical lowering for typed high-level SQG tasks."""

from __future__ import annotations

import copy
from collections import defaultdict
from typing import Any

from nexus.core.expressions import (
    AggregateExpr, AttributeExpr, BinaryExpr, CaseExpr, ColumnExpr, ComparisonPredicate,
    EXPRESSION_ADAPTER,
    Expression, FunctionExpr, InPredicate, LiteralExpr, NotPredicate, NullPredicate,
    OrPredicate, AndPredicate, Predicate, TimeBucketExpr, TimeRangePredicate, UnaryExpr,
    expression_attributes, predicate_attributes,
)
from nexus.core.intermediate import (
    BoundAttribute, BoundEntity, BoundLogicalNode, BoundLogicalPlan, BoundOperator,
    BoundRelation, RelationMultiplicity, SemanticBindingArtifact, SemanticTaskBinding,
)
from nexus.core.logical import (
    ActNode, AggregateNode, AttributeDimension, CalculateNode, MetricMeasure, Operator,
    OrderKey, SQG, SearchNode, BrowseNode, AskNode, SelectNode, StatisticMeasure, TimeDimension,
)
from nexus.core.models import ConceptKind
from nexus.engine.relations import join_tree


class BindingError(ValueError):
    pass


class Binder:
    def __init__(self, ontology):
        self.ontology = ontology
        self._entities: dict[str, BoundEntity] = {}
        self._attributes: dict[str, BoundAttribute] = {}
        self._alias_seq = 0

    def bind(self, sqg: SQG) -> tuple[SemanticBindingArtifact, BoundLogicalPlan]:
        tasks: list[SemanticTaskBinding] = []
        logical_nodes: list[BoundLogicalNode] = []
        outputs: dict[str, str] = {}
        for task in sqg.nodes:
            if isinstance(task, (SearchNode, BrowseNode, AskNode, ActNode)):
                node_id = f"bl_{task.id}_capability"
                logical_nodes.append(BoundLogicalNode(
                    id=node_id, kind=BoundOperator.CAPABILITY, name=task.name,
                    inputs=[outputs[d] for d in task.depends_on if d in outputs],
                    origin_sqg_nodes=[task.id], capability=task.operator.value,
                ))
                outputs[task.id] = node_id
                tasks.append(SemanticTaskBinding(logical_node=task.id))
                continue
            if isinstance(task, CalculateNode):
                node_id = f"bl_{task.id}_calculate"
                logical_nodes.append(BoundLogicalNode(
                    id=node_id, kind=BoundOperator.CALCULATE, name=task.name,
                    inputs=[outputs[d] for d in task.depends_on if d in outputs],
                    origin_sqg_nodes=[task.id],
                    expressions=[(output.name, output.expression) for output in task.spec.outputs],
                    grain=list(task.spec.result.grain), result_fields=list(task.spec.result.fields),
                ))
                outputs[task.id] = node_id
                tasks.append(SemanticTaskBinding(logical_node=task.id))
                continue
            if isinstance(task, SelectNode):
                task_binding, nodes, output = self._bind_select(task)
            elif isinstance(task, AggregateNode):
                task_binding, nodes, output = self._bind_aggregate(task)
            else:
                raise BindingError(f"unsupported SQG task: {type(task).__name__}")
            tasks.append(task_binding)
            logical_nodes.extend(nodes)
            outputs[task.id] = output
        return SemanticBindingArtifact(tasks=tasks), BoundLogicalPlan(nodes=logical_nodes, outputs=outputs)

    def _binding(self, concept_id: str, kind: str):
        for binding in self.ontology.get_bindings(concept_id):
            if binding.kind == kind:
                return binding
        raise BindingError(f"concept has no {kind} binding: {concept_id}")

    def _entity(self, entity_id: str) -> BoundEntity:
        if entity_id in self._entities:
            return self._entities[entity_id]
        concept = self.ontology.get_concept(entity_id)
        if concept is None or concept.kind != ConceptKind.entity:
            raise BindingError(f"entity not found: {entity_id}")
        binding = self._binding(entity_id, "table")
        entity = BoundEntity(
            concept=entity_id, object_name=binding.expr or "", source_instance=binding.resolver,
            key=(concept.attrs or {}).get("key"),
        )
        self._entities[entity_id] = entity
        return entity

    def _attribute(self, attribute_id: str) -> BoundAttribute:
        if attribute_id in self._attributes:
            return self._attributes[attribute_id]
        concept = self.ontology.get_concept(attribute_id)
        if concept is None or concept.kind != ConceptKind.attribute:
            raise BindingError(f"attribute not found: {attribute_id}")
        entity_id = (concept.attrs or {}).get("entity")
        entity = self._entity(entity_id)
        binding = self._binding(attribute_id, "column")
        attribute = BoundAttribute(
            concept=attribute_id, entity=entity_id, column=binding.expr or "",
            source_instance=entity.source_instance, data_type=(concept.attrs or {}).get("dtype") or "unknown",
            role=(concept.attrs or {}).get("role") or "dimension",
            additivity=(concept.attrs or {}).get("additivity"),
        )
        self._attributes[attribute_id] = attribute
        return attribute

    def _metric(self, metric_id: str) -> Expression:
        concept = self.ontology.get_concept(metric_id)
        if concept is None or concept.kind != ConceptKind.metric:
            raise BindingError(f"metric not found: {metric_id}")
        expression = (concept.attrs or {}).get("expression")
        if not expression:
            raise BindingError(f"metric has no typed expression: {metric_id}")
        parsed = EXPRESSION_ADAPTER.validate_python(expression)
        return parsed

    def _entities_for(self, attributes: set[str]) -> list[str]:
        entities: list[str] = []
        for attribute_id in sorted(attributes):
            entity = self._attribute(attribute_id).entity
            if entity not in entities:
                entities.append(entity)
        return entities

    def _relation(self, raw) -> BoundRelation:
        return BoundRelation(
            concept=raw.id,
            from_entity=raw.from_.entity,
            from_attributes=list(raw.from_.attributes),
            to_entity=raw.to.entity,
            to_attributes=list(raw.to.attributes),
            from_to=RelationMultiplicity(**raw.multiplicity.from_to.model_dump()),
            to_from=RelationMultiplicity(**raw.multiplicity.to_from.model_dump()),
            integrity_mode=raw.integrity.mode,
            confidence=raw.integrity.confidence,
            temporal=raw.temporal.model_dump() if raw.temporal else None,
        )

    def _task_binding(self, task_id: str, attributes: set[str], metric_ids: list[str],
                      root_entity: str) -> SemanticTaskBinding:
        required = self._entities_for(attributes)
        if root_entity not in required:
            self._entity(root_entity)
            required.insert(0, root_entity)
        else:
            required = [root_entity, *[entity for entity in required if entity != root_entity]]
        tree = join_tree(self.ontology, required)
        if tree is None:
            raise BindingError(f"entities are not connected for task {task_id}: {required}")
        ordered, relations = tree
        entities = [self._entity(entity) for entity in ordered]
        bound_attributes = [self._attribute(attribute) for attribute in sorted(attributes)]
        sources = list(dict.fromkeys(entity.source_instance for entity in entities))
        return SemanticTaskBinding(
            logical_node=task_id, entities=entities, attributes=bound_attributes,
            metrics=metric_ids, relations=[self._relation(relation) for relation in relations],
            source_instances=sources,
        )

    def _scan_nodes(self, task_id: str, task_name: str, binding: SemanticTaskBinding,
                    predicate: Predicate | None) -> tuple[list[BoundLogicalNode], str]:
        nodes: list[BoundLogicalNode] = []
        scan_ids: dict[str, str] = {}
        for index, entity in enumerate(binding.entities):
            scan_id = f"bl_{task_id}_scan_{index}"
            scan_ids[entity.concept] = scan_id
            nodes.append(BoundLogicalNode(
                id=scan_id, kind=BoundOperator.SCAN, name=f"扫描 {entity.concept}",
                origin_sqg_nodes=[task_id], entity=entity,
                source_candidates=[entity.source_instance], cardinality="many",
            ))
        current = scan_ids[binding.entities[0].concept]
        for index, relation in enumerate(binding.relations):
            target = relation.to_entity if relation.to_entity != binding.entities[0].concept else relation.from_entity
            target_scan = scan_ids.get(target)
            if target_scan and target_scan != current:
                relate_id = f"bl_{task_id}_relate_{index}"
                nodes.append(BoundLogicalNode(
                    id=relate_id, kind=BoundOperator.RELATE, name=f"关联 {relation.concept}",
                    inputs=[current, target_scan], origin_sqg_nodes=[task_id], relation=relation,
                    cardinality=relation.from_to.max if isinstance(relation.from_to.max, str) else str(relation.from_to.max),
                ))
                current = relate_id
        if predicate is not None:
            filter_id = f"bl_{task_id}_filter"
            nodes.append(BoundLogicalNode(
                id=filter_id, kind=BoundOperator.FILTER, name=f"筛选 {task_name}", inputs=[current],
                origin_sqg_nodes=[task_id], predicate=predicate,
            ))
            current = filter_id
        return nodes, current

    def _bind_select(self, task: SelectNode):
        attrs = {field.concept for field in task.spec.fields} | predicate_attributes(task.spec.scope)
        binding = self._task_binding(task.id, attrs, [], task.spec.subject.entity)
        nodes, current = self._scan_nodes(task.id, task.name, binding, task.spec.scope)
        project_id = f"bl_{task.id}_project"
        nodes.append(BoundLogicalNode(
            id=project_id, kind=BoundOperator.DISTINCT if task.spec.distinct else BoundOperator.PROJECT,
            name=task.name, inputs=[current], origin_sqg_nodes=[task.id],
            expressions=[(field.output, AttributeExpr(concept=field.concept)) for field in task.spec.fields],
            grain=list(task.spec.result.grain), result_fields=list(task.spec.result.fields),
        ))
        return binding, nodes, project_id

    def _bind_aggregate(self, task: AggregateNode):
        dimensions: list[tuple[str, Expression]] = []
        attrs = predicate_attributes(task.spec.scope) | predicate_attributes(task.spec.result_filter)
        for dimension in task.spec.dimensions:
            if isinstance(dimension, AttributeDimension):
                expression: Expression = AttributeExpr(concept=dimension.concept)
                attrs.add(dimension.concept)
            elif isinstance(dimension, TimeDimension):
                expression = TimeBucketExpr(
                    value=AttributeExpr(concept=dimension.attribute), grain=dimension.grain,
                    calendar=dimension.calendar, timezone=dimension.timezone,
                )
                attrs.add(dimension.attribute)
            dimensions.append((dimension.output, expression))

        metric_ids: list[str] = []
        if isinstance(task.spec.measure, MetricMeasure):
            aggregate = self._metric(task.spec.measure.metric)
            metric_ids.append(task.spec.measure.metric)
        elif isinstance(task.spec.measure, StatisticMeasure):
            statistic = task.spec.measure.statistic
            aggregate = AggregateExpr(
                function=statistic.function, value=task.spec.measure.value,
                distinct=statistic.distinct, percentile=statistic.percentile,
                method=statistic.method, accuracy=statistic.accuracy, nulls=statistic.nulls,
            )
        else:
            raise BindingError(f"unsupported measure for {task.id}")
        attrs |= expression_attributes(aggregate)
        self._validate_aggregate_expression(aggregate)
        binding = self._task_binding(task.id, attrs, metric_ids, task.spec.subject.entity)
        nodes, current = self._scan_nodes(task.id, task.name, binding, task.spec.scope)
        aggregate_id = f"bl_{task.id}_aggregate"
        nodes.append(BoundLogicalNode(
            id=aggregate_id, kind=BoundOperator.AGGREGATE, name=task.name, inputs=[current],
            origin_sqg_nodes=[task.id], dimensions=dimensions, aggregate=aggregate,
            grain=[name for name, _ in dimensions], result_fields=list(task.spec.result.fields),
            domain=task.spec.domain_policy.unmatched,
        ))
        current = aggregate_id
        if task.spec.result_filter is not None:
            result_filter_id = f"bl_{task.id}_result_filter"
            nodes.append(BoundLogicalNode(
                id=result_filter_id, kind=BoundOperator.FILTER, name=f"结果筛选 {task.name}",
                inputs=[current], origin_sqg_nodes=[task.id], predicate=task.spec.result_filter,
                grain=[name for name, _ in dimensions],
            ))
            current = result_filter_id
        if task.spec.ranking is not None:
            rank = task.spec.ranking
            top_id = f"bl_{task.id}_top_n"
            order = [OrderKey(field=rank.by, direction=rank.direction, nulls="LAST"), *rank.tie_breakers]
            nodes.append(BoundLogicalNode(
                id=top_id, kind=BoundOperator.TOP_N, name=task.name, inputs=[current],
                origin_sqg_nodes=[task.id], order_by=order, limit=rank.take,
                grain=[name for name, _ in dimensions], result_fields=list(task.spec.result.fields),
            ))
            current = top_id
        return binding, nodes, current

    def _validate_aggregate_expression(self, expression: Expression) -> None:
        if isinstance(expression, AggregateExpr):
            referenced = expression_attributes(expression.value)
            for attribute_id in referenced:
                attribute = self._attribute(attribute_id)
                if expression.function.value in {"SUM", "AVG"} and attribute.data_type != "number":
                    raise BindingError(f"{expression.function.value} requires numeric attribute: {attribute_id}")
                if expression.function.value == "SUM" and attribute.additivity == "non_additive":
                    raise BindingError(f"SUM is forbidden for non-additive attribute: {attribute_id}")
            return
        if isinstance(expression, BinaryExpr):
            self._validate_aggregate_expression(expression.left)
            self._validate_aggregate_expression(expression.right)

    def bind_expression(self, expr: Expression, aliases: dict[str, str]) -> Expression:
        if isinstance(expr, AttributeExpr):
            attribute = self._attribute(expr.concept)
            return ColumnExpr(source=aliases[attribute.entity], name=attribute.column)
        if isinstance(expr, BinaryExpr):
            return expr.model_copy(update={
                "left": self.bind_expression(expr.left, aliases),
                "right": self.bind_expression(expr.right, aliases),
            })
        if isinstance(expr, UnaryExpr):
            return expr.model_copy(update={"operand": self.bind_expression(expr.operand, aliases)})
        if isinstance(expr, FunctionExpr):
            return expr.model_copy(update={"arguments": [self.bind_expression(v, aliases) for v in expr.arguments]})
        if isinstance(expr, TimeBucketExpr):
            return expr.model_copy(update={"value": self.bind_expression(expr.value, aliases)})
        if isinstance(expr, AggregateExpr):
            return expr.model_copy(update={
                "value": self.bind_expression(expr.value, aliases) if expr.value else None,
                "filter": self.bind_predicate(expr.filter, aliases) if expr.filter else None,
            })
        if isinstance(expr, CaseExpr):
            return expr.model_copy(update={
                "branches": [branch.model_copy(update={
                    "when": self.bind_predicate(branch.when, aliases),
                    "then": self.bind_expression(branch.then, aliases),
                }) for branch in expr.branches],
                "otherwise": self.bind_expression(expr.otherwise, aliases) if expr.otherwise else None,
            })
        return copy.deepcopy(expr)

    def bind_predicate(self, predicate: Predicate | None, aliases: dict[str, str]) -> Predicate | None:
        if predicate is None:
            return None
        if isinstance(predicate, TimeRangePredicate):
            value = self.bind_expression(AttributeExpr(concept=predicate.attribute), aliases)
            predicates = []
            if predicate.start is not None:
                predicates.append(ComparisonPredicate(left=value, operator="GTE", right=LiteralExpr(value=predicate.start)))
            if predicate.end_exclusive is not None:
                predicates.append(ComparisonPredicate(left=value, operator="LT", right=LiteralExpr(value=predicate.end_exclusive)))
            return predicates[0] if len(predicates) == 1 else AndPredicate(operands=predicates)
        if isinstance(predicate, ComparisonPredicate):
            return predicate.model_copy(update={
                "left": self.bind_expression(predicate.left, aliases),
                "right": self.bind_expression(predicate.right, aliases),
            })
        if isinstance(predicate, InPredicate):
            return predicate.model_copy(update={
                "value": self.bind_expression(predicate.value, aliases),
                "values": [self.bind_expression(v, aliases) for v in predicate.values],
            })
        if isinstance(predicate, NullPredicate):
            return predicate.model_copy(update={"value": self.bind_expression(predicate.value, aliases)})
        if isinstance(predicate, AndPredicate):
            return predicate.model_copy(update={"operands": [self.bind_predicate(v, aliases) for v in predicate.operands]})
        if isinstance(predicate, OrPredicate):
            return predicate.model_copy(update={"operands": [self.bind_predicate(v, aliases) for v in predicate.operands]})
        if isinstance(predicate, NotPredicate):
            return predicate.model_copy(update={"operand": self.bind_predicate(predicate.operand, aliases)})
        return copy.deepcopy(predicate)
