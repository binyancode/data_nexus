"""Clean-break optimizer: typed SQG -> binding -> logical IR -> fragment PEP."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

from nexus.core.expressions import (
    AggregateExpr, AggregateFunction, AttributeExpr, CaseExpr, ColumnExpr, LiteralExpr, Predicate,
    aggregate_functions, combine_conjuncts, expression_attributes, OutputExpr,
    predicate_attributes, predicate_key, split_conjuncts,
)
from nexus.core.intermediate import (
    BoundLogicalPlan, OptimizationTrace, PlanCandidate, RuleDecision,
    SemanticBindingArtifact, SemanticTaskBinding,
)
from nexus.core.logical import (
    ActNode, AggregateNode, AskNode, BrowseNode, CalculateNode, MetricMeasure,
    Operator, OrderKey, SearchNode, SelectNode, SQG, StatisticMeasure,
)
from nexus.core.models import ExecContext, topo_waves
from nexus.core.physical import (
    CapabilityFragment, ComputeFragment, ComputeInput, LogicalOutputBinding,
    ExchangeFragment, PhysicalExecutionPlan, QueryIR, QueryJoin, QueryOutput, QuerySource,
    SourceFragment,
)
from nexus.engine.binder import Binder, BindingError


class Optimizer:
    def __init__(self, ontology, registry=None, allowed: Optional[set] = None,
                 compute_engine_name: str = "duckdb",
                 compute_engine_type: str = "duckdb",
                 compute_capabilities: Optional[dict] = None):
        self.ontology = ontology
        self.registry = registry
        self.allowed = set(allowed) if allowed is not None else None
        self.compute_engine_name = compute_engine_name
        self.compute_engine_type = compute_engine_type
        self.compute_capabilities = compute_capabilities or {}
        self.binder = Binder(ontology)
        self.trace = OptimizationTrace()

    def _allowed(self, name: str | None) -> bool:
        return bool(name) and (self.allowed is None or name in self.allowed)

    def plan(self, sqg: SQG, ctx: Optional[ExecContext] = None) -> PhysicalExecutionPlan:
        binding, logical = self.binder.bind(sqg)
        if ctx is not None:
            ctx.stage_logs["artifacts"] = {
                "semantic_binding": binding.model_dump(mode="json"),
                "bound_logical_plan": logical.model_dump(mode="json"),
            }
        plan = self._physical(sqg, binding, logical)
        self._bind_compute_engine(plan)
        self._waves(plan)
        self.trace.selected_plan = "selected"
        self.trace.candidates.append(PlanCandidate(
            id="selected", strategy="fragment_pep",
            logical_nodes=list(logical.outputs), selected=True,
            reason="lowest safe plan among generated candidates",
        ))
        if ctx is not None:
            ctx.stage_logs["artifacts"].update({
                "physical_execution_plan": plan.model_dump(mode="json"),
                "optimization_trace": self.trace.model_dump(mode="json"),
            })
        return plan

    def _bind_compute_engine(self, plan: PhysicalExecutionPlan) -> None:
        supported = set(self.compute_capabilities.get("aggregates") or [])
        for fragment in plan.nodes:
            if not isinstance(fragment, ComputeFragment):
                continue
            required = set()
            for output in fragment.query.outputs:
                required |= {
                    str(getattr(value, "value", value))
                    for value in aggregate_functions(output.aggregate)
                }
            missing = required - supported if supported else set()
            if missing:
                raise BindingError(
                    f"计算引擎 {self.compute_engine_name!r} ({self.compute_engine_type}) "
                    f"不支持聚合函数：{', '.join(sorted(missing))}"
                )
            fragment.engine = self.compute_engine_name
        plan.context.update({
            "compute_engine_name": self.compute_engine_name,
            "compute_engine_type": self.compute_engine_type,
            "compute_capabilities": self.compute_capabilities,
        })

    def _physical(self, sqg: SQG, binding: SemanticBindingArtifact,
                  logical: BoundLogicalPlan) -> PhysicalExecutionPlan:
        task_bindings = {task.logical_node: task for task in binding.tasks}
        structured = [node for node in sqg.nodes if isinstance(node, (SelectNode, AggregateNode))]
        plan_nodes: list[Any] = []
        physical_for_logical: dict[str, str] = {}

        grouped: dict[tuple, list] = defaultdict(list)
        for task in structured:
            task_binding = task_bindings[task.id]
            if len(task_binding.source_instances) == 1 and not self._requires_compute(task, task_binding, logical):
                grouped[self._fusion_key(task, task_binding)].append(task)
            else:
                fragments = self._cross_source(task, task_binding, logical)
                plan_nodes.extend(fragments)
                physical_for_logical[task.id] = fragments[-1].id

        for group in grouped.values():
            if len(group) > 1 and all(isinstance(task, AggregateNode) for task in group):
                fragments = self._fused_aggregates(group, task_bindings, logical)
                plan_nodes.extend(fragments)
                for task in group:
                    physical_for_logical[task.id] = next(
                        fragment.id for fragment in reversed(fragments)
                        if any(item.logical_node == task.id for item in fragment.realizes)
                    )
            else:
                for task in group:
                    fragment = self._single_source(task, task_bindings[task.id], logical)
                    plan_nodes.append(fragment)
                    physical_for_logical[task.id] = fragment.id

        for task in sqg.nodes:
            if isinstance(task, (SelectNode, AggregateNode)):
                continue
            dependencies = list(dict.fromkeys(
                physical_for_logical[dep] for dep in task.depends_on if dep in physical_for_logical
            ))
            fragment = self._calculate(task, dependencies) if isinstance(task, CalculateNode) \
                else self._capability(task, dependencies)
            plan_nodes.append(fragment)
            physical_for_logical[task.id] = fragment.id

        contracts = {task.id: task.spec.result for task in sqg.nodes if hasattr(task.spec, "result")}
        return PhysicalExecutionPlan(
            nodes=plan_nodes, logical_results=contracts,
            context={"parallelism": 4, "logical_to_physical": physical_for_logical},
        )

    def _requires_compute(self, task, binding: SemanticTaskBinding,
                          logical: BoundLogicalPlan) -> bool:
        if not isinstance(task, AggregateNode):
            return False
        expression = self._logical_aggregate(task.id, logical).aggregate
        required = aggregate_functions(expression)
        resolver = self._resolver(binding.source_instances[0])
        supported = set((resolver.capabilities().get("relational") or {}).get("aggregates") or [])
        missing = required - supported
        if missing:
            self.trace.rules.append(RuleDecision(
                rule="source_aggregate_pushdown", outcome="rejected", logical_nodes=[task.id],
                reason="source does not support required aggregate(s)",
                details={"missing": sorted(missing), "source": resolver.name},
            ))
        return bool(missing)

    def _fusion_key(self, task, binding: SemanticTaskBinding) -> tuple:
        dimensions = [d.model_dump_json() for d in task.spec.dimensions] if isinstance(task, AggregateNode) else []
        domain_policy = task.spec.domain_policy.unmatched if isinstance(task, AggregateNode) else "EXCLUDE_UNMATCHED"
        return (
            tuple(binding.source_instances), tuple(entity.concept for entity in binding.entities),
            tuple(relation.concept for relation in binding.relations), tuple(dimensions), domain_policy,
        )

    @staticmethod
    def _aliases(binding: SemanticTaskBinding) -> dict[str, str]:
        return {entity.concept: f"t{index}" for index, entity in enumerate(binding.entities)}

    def _query_sources(self, binding: SemanticTaskBinding):
        aliases = self._aliases(binding)
        sources = {
            entity.concept: QuerySource(
                entity=entity.concept, object_name=entity.object_name,
                alias=aliases[entity.concept], source_instance=entity.source_instance,
            ) for entity in binding.entities
        }
        return aliases, sources

    def _query_joins(self, binding: SemanticTaskBinding, aliases, sources,
                     unmatched_policy: str = "EXCLUDE_UNMATCHED") -> list[QueryJoin]:
        joins: list[QueryJoin] = []
        joined = {binding.entities[0].concept}
        remaining = list(binding.relations)
        while remaining:
            progressed = False
            for relation in list(remaining):
                frm, to = relation.from_entity, relation.to_entity
                if frm in joined and to not in joined:
                    target, left_ids, right_ids = to, relation.from_attributes, relation.to_attributes
                    traversal_min, traversal_max = relation.from_to.min, relation.from_to.max
                elif to in joined and frm not in joined:
                    target, left_ids, right_ids = frm, relation.to_attributes, relation.from_attributes
                    traversal_min, traversal_max = relation.to_from.min, relation.to_from.max
                else:
                    continue
                joins.append(QueryJoin(
                    relation=relation.concept, source=sources[target],
                    left=[self.binder.bind_expression(AttributeExpr(concept=value), aliases) for value in left_ids],
                    right=[self.binder.bind_expression(AttributeExpr(concept=value), aliases) for value in right_ids],
                    join_type=self._join_type(relation, traversal_min, unmatched_policy),
                    cardinality=str(traversal_max),
                ))
                joined.add(target)
                remaining.remove(relation)
                progressed = True
            if not progressed:
                raise BindingError("relation tree could not be oriented")
        return joins

    @staticmethod
    def _logical_aggregate(task_id: str, logical: BoundLogicalPlan):
        return next(node for node in logical.nodes
                    if task_id in node.origin_sqg_nodes and node.kind.value == "AGGREGATE")

    def _aggregate_parts(self, task: AggregateNode, binding: SemanticTaskBinding,
                         logical: BoundLogicalPlan):
        aliases, sources = self._query_sources(binding)
        logical_node = self._logical_aggregate(task.id, logical)
        dimensions = [
            QueryOutput(name=name, expression=self.binder.bind_expression(expr, aliases))
            for name, expr in logical_node.dimensions
        ]
        aggregate = self.binder.bind_expression(logical_node.aggregate, aliases)
        predicate = self.binder.bind_predicate(task.spec.scope, aliases)
        result_predicate = task.spec.result_filter
        order: list[OrderKey] = []
        limit = None
        if task.spec.ranking:
            order = [
                OrderKey(field=task.spec.ranking.by, direction=task.spec.ranking.direction, nulls="LAST"),
                *task.spec.ranking.tie_breakers,
            ]
            limit = task.spec.ranking.take
        return aliases, sources, dimensions, aggregate, predicate, result_predicate, order, limit

    def _single_source(self, task, binding: SemanticTaskBinding,
                       logical: BoundLogicalPlan) -> SourceFragment:
        aliases, sources = self._query_sources(binding)
        if isinstance(task, SelectNode):
            outputs = [
                QueryOutput(name=field.output,
                            expression=self.binder.bind_expression(AttributeExpr(concept=field.concept), aliases))
                for field in task.spec.fields
            ]
            query = QueryIR(
                source=sources[binding.entities[0].concept],
                joins=self._query_joins(binding, aliases, sources),
                predicate=self.binder.bind_predicate(task.spec.scope, aliases),
                outputs=outputs, distinct=task.spec.distinct,
            )
        else:
            _, _, dimensions, aggregate, predicate, result_predicate, order, limit = \
                self._aggregate_parts(task, binding, logical)
            query = QueryIR(
                source=sources[binding.entities[0].concept],
                joins=self._query_joins(binding, aliases, sources, task.spec.domain_policy.unmatched), predicate=predicate,
                dimensions=dimensions,
                outputs=[QueryOutput(name=task.spec.measure.output, aggregate=aggregate)],
                result_predicate=result_predicate, order_by=order, limit=limit,
            )
        resolver = self._resolver(binding.source_instances[0])
        fragment_id = f"p_{task.id}"
        fragment = SourceFragment(
            id=fragment_id, name=task.name, source_instance=resolver.name,
            query=query, call={"node_id": fragment_id, **resolver.compile(query)},
            realizes=[LogicalOutputBinding(logical_node=task.id, physical_result="result_set")],
        )
        self.trace.rules.append(RuleDecision(
            rule="single_source_pushdown", outcome="applied", logical_nodes=[task.id],
            reason="all required entities are in one source instance",
        ))
        return fragment

    def _fused_aggregates(self, tasks: list[AggregateNode], bindings: dict[str, SemanticTaskBinding],
                          logical: BoundLogicalPlan) -> list[Any]:
        base_binding = bindings[tasks[0].id]
        aliases, sources = self._query_sources(base_binding)
        dimensions = []
        aggregates: list[tuple[AggregateNode, AggregateExpr, Predicate | None]] = []
        for task in tasks:
            _, _, task_dimensions, aggregate, predicate, _, _, _ = \
                self._aggregate_parts(task, bindings[task.id], logical)
            dimensions = dimensions or task_dimensions
            aggregates.append((task, aggregate, predicate))

        conjunct_sets = [
            {predicate_key(value): value for value in split_conjuncts(predicate)}
            for _, _, predicate in aggregates
        ]
        common_keys = set(conjunct_sets[0])
        for values in conjunct_sets[1:]:
            common_keys &= set(values)
        common = [conjunct_sets[0][key] for key in sorted(common_keys)]
        outputs = []
        for index, (task, aggregate, _) in enumerate(aggregates):
            remaining = [value for key, value in conjunct_sets[index].items() if key not in common_keys]
            branch_filter = combine_conjuncts(remaining)
            if branch_filter is not None:
                aggregate = self._condition_expression(aggregate, branch_filter)
            outputs.append(QueryOutput(name=task.id, aggregate=aggregate))
        query = QueryIR(
            source=sources[base_binding.entities[0].concept],
            joins=self._query_joins(base_binding, aliases, sources, tasks[0].spec.domain_policy.unmatched),
            predicate=combine_conjuncts(common), dimensions=dimensions, outputs=outputs,
        )
        resolver = self._resolver(base_binding.source_instances[0])
        fragment_id = "p_fused_" + "_".join(task.id for task in tasks)
        direct_tasks = [task for task in tasks if task.spec.ranking is None and task.spec.result_filter is None]
        fragment = SourceFragment(
            id=fragment_id, name="融合取数：" + " + ".join(task.name for task in tasks),
            source_instance=resolver.name, query=query,
            call={"node_id": fragment_id, **resolver.compile(query)},
            realizes=[
                LogicalOutputBinding(logical_node=task.id,
                                     logical_field=task.spec.measure.output,
                                     physical_field=task.id)
                for task in direct_tasks
            ],
        )
        self.trace.rules.extend([
            RuleDecision(rule="common_predicate_extraction", outcome="applied",
                         logical_nodes=[task.id for task in tasks],
                         reason=f"extracted {len(common)} common conjunct(s)"),
            RuleDecision(rule="multi_measure_fusion", outcome="applied",
                         logical_nodes=[task.id for task in tasks],
                         reason="same source, relation path and grain"),
        ])
        fragments: list[Any] = [fragment]
        for task in tasks:
            if task in direct_tasks:
                continue
            table = f"x_{task.id}_shared"
            source = QuerySource(entity=fragment.id, object_name=table, alias="s0", source_instance="compute")
            dimension_outputs = [
                QueryOutput(name=dimension.name,
                            expression=ColumnExpr(source="s0", name=dimension.name))
                for dimension in dimensions
            ]
            value_name = task.spec.measure.output
            result_predicate = self._post_predicate(task.spec.result_filter, "s0", value_name, value_name)
            order = ([OrderKey(field=value_name, direction=task.spec.ranking.direction),
                      *task.spec.ranking.tie_breakers] if task.spec.ranking else [])
            branch_query = QueryIR(
                source=source, dimensions=dimension_outputs,
                outputs=[QueryOutput(name=value_name,
                                     expression=ColumnExpr(source="s0", name=task.id))],
                predicate=result_predicate, order_by=order,
                limit=task.spec.ranking.take if task.spec.ranking else None,
            )
            branch_id = f"p_{task.id}_post"
            fragments.append(ComputeFragment(
                id=branch_id, name=task.name,
                inputs=[ComputeInput(table=table, from_fragment=fragment.id)],
                query=branch_query, depends_on=[fragment.id],
                realizes=[LogicalOutputBinding(logical_node=task.id, physical_result="result_set")],
            ))
        return fragments

    def _post_predicate(self, predicate, source: str, physical_value: str, logical_value: str):
        if predicate is None:
            return None
        def bind_expression(expression):
            if getattr(expression, "kind", None) == "output":
                name = physical_value if expression.name == logical_value else expression.name
                return OutputExpr(name=name)
            return expression
        if getattr(predicate, "kind", None) == "comparison":
            return predicate.model_copy(update={
                "left": bind_expression(predicate.left), "right": bind_expression(predicate.right),
            })
        if getattr(predicate, "kind", None) in ("and", "or"):
            return predicate.model_copy(update={
                "operands": [self._post_predicate(value, source, physical_value, logical_value)
                             for value in predicate.operands],
            })
        return predicate

    def _cross_source(self, task, binding: SemanticTaskBinding,
                      logical: BoundLogicalPlan) -> list[Any]:
        aliases = self._aliases(binding)
        logical_aggregate = self._logical_aggregate(task.id, logical) if isinstance(task, AggregateNode) else None
        preaggregate = self._preaggregate_candidate(task, binding, logical_aggregate)
        fragments: list[SourceFragment] = []
        source_entities: dict[str, list] = defaultdict(list)
        for entity in binding.entities:
            source_entities[entity.source_instance].append(entity)
        for index, (source_name, entities) in enumerate(source_entities.items()):
            root = entities[0]
            columns = [attribute for attribute in binding.attributes if attribute.source_instance == source_name]
            relation_attrs = {value for relation in binding.relations
                              for value in [*relation.from_attributes, *relation.to_attributes]}
            for attribute_id in relation_attrs:
                attribute = self.binder._attribute(attribute_id)
                if attribute.source_instance == source_name and all(a.concept != attribute_id for a in columns):
                    columns.append(attribute)
            outputs = [
                QueryOutput(name=f"{self._local(attribute.entity)}__{attribute.column}",
                            expression=ColumnExpr(source=aliases[attribute.entity], name=attribute.column))
                for attribute in columns
            ]
            source = QuerySource(entity=root.concept, object_name=root.object_name,
                                 alias=aliases[root.concept], source_instance=source_name)
            local_entity_ids = {entity.concept for entity in entities}
            local_joins = []
            for relation in binding.relations:
                if relation.from_entity not in local_entity_ids or relation.to_entity not in local_entity_ids:
                    continue
                target_entity = relation.to_entity if relation.from_entity == root.concept else relation.from_entity
                target = next(entity for entity in entities if entity.concept == target_entity)
                local_joins.append(QueryJoin(
                    relation=relation.concept,
                    source=QuerySource(entity=target.concept, object_name=target.object_name,
                                       alias=aliases[target.concept], source_instance=source_name),
                    left=[self.binder.bind_expression(AttributeExpr(concept=value), aliases)
                          for value in relation.from_attributes],
                    right=[self.binder.bind_expression(AttributeExpr(concept=value), aliases)
                           for value in relation.to_attributes],
                    join_type=self._join_type(
                        relation,
                        relation.from_to.min if relation.from_entity == root.concept else relation.to_from.min,
                        task.spec.domain_policy.unmatched if isinstance(task, AggregateNode) else "EXCLUDE_UNMATCHED",
                    ),
                    cardinality=f"{relation.to_from.max}:{relation.from_to.max}",
                ))
            local_predicates = []
            if isinstance(task, AggregateNode):
                for predicate in split_conjuncts(task.spec.scope):
                    predicate_sources = {self.binder._attribute(value).source_instance
                                         for value in predicate_attributes(predicate)}
                    if predicate_sources == {source_name}:
                        local_predicates.append(self.binder.bind_predicate(predicate, aliases))
            if preaggregate and preaggregate["source"] == source_name:
                boundary_attributes = [self.binder._attribute(value) for value in preaggregate["keys"]]
                dimensions = [
                    QueryOutput(name=f"{self._local(attribute.entity)}__{attribute.column}",
                                expression=ColumnExpr(source=aliases[attribute.entity], name=attribute.column))
                    for attribute in boundary_attributes
                ]
                partial = self.binder.bind_expression(logical_aggregate.aggregate, aliases)
                query = QueryIR(
                    source=source, joins=local_joins,
                    predicate=combine_conjuncts(local_predicates), dimensions=dimensions,
                    outputs=[QueryOutput(name="__partial_value", aggregate=partial)],
                )
            else:
                query = QueryIR(source=source, joins=local_joins,
                                predicate=combine_conjuncts(local_predicates), outputs=outputs)
            resolver = self._resolver(source_name)
            fragment_id = f"p_{task.id}_source_{index}"
            fragments.append(SourceFragment(
                id=fragment_id, name=f"取数 {source_name}", source_instance=source_name,
                query=query, call={"node_id": fragment_id, **resolver.compile(query)},
            ))

        compute_aliases: dict[str, str] = {}
        input_sources: list[QuerySource] = []
        compute_inputs: list[ComputeInput] = []
        exchanges: list[ExchangeFragment] = []
        for index, fragment in enumerate(fragments):
            table = f"x_{task.id}_{index}"
            exchange_id = f"p_{task.id}_exchange_{index}"
            exchanges.append(ExchangeFragment(
                id=exchange_id, name=f"交换 {fragment.source_instance}",
                mode="BROADCAST" if index > 0 else "MATERIALIZE",
                from_fragment=fragment.id, into=table, depends_on=[fragment.id],
            ))
            source = QuerySource(entity=fragment.id, object_name=table, alias=f"x{index}", source_instance="compute")
            input_sources.append(source)
            compute_inputs.append(ComputeInput(table=table, from_fragment=exchange_id))
            for entity in source_entities[fragment.source_instance]:
                compute_aliases[entity.concept] = source.alias
        joins = []
        root_source = compute_aliases[binding.entities[0].concept]
        joined_sources = {root_source}
        remaining_relations = [relation for relation in binding.relations
                               if compute_aliases[relation.from_entity] != compute_aliases[relation.to_entity]]
        while remaining_relations:
            progressed = False
            for relation in list(remaining_relations):
                frm_source, to_source = compute_aliases[relation.from_entity], compute_aliases[relation.to_entity]
                if frm_source in joined_sources and to_source not in joined_sources:
                    target_source, left_entity, right_entity = to_source, relation.from_entity, relation.to_entity
                    left_attrs, right_attrs = relation.from_attributes, relation.to_attributes
                    traversal_min, traversal_max = relation.from_to.min, relation.from_to.max
                elif to_source in joined_sources and frm_source not in joined_sources:
                    target_source, left_entity, right_entity = frm_source, relation.to_entity, relation.from_entity
                    left_attrs, right_attrs = relation.to_attributes, relation.from_attributes
                    traversal_min, traversal_max = relation.to_from.min, relation.to_from.max
                else:
                    continue
                target = next(source for source in input_sources if source.alias == target_source)
                joins.append(QueryJoin(
                    relation=relation.concept, source=target,
                    left=[ColumnExpr(source=compute_aliases[left_entity],
                                     name=f"{self._local(left_entity)}__{self.binder._attribute(attr).column}")
                          for attr in left_attrs],
                    right=[ColumnExpr(source=compute_aliases[right_entity],
                                      name=f"{self._local(right_entity)}__{self.binder._attribute(attr).column}")
                           for attr in right_attrs],
                    join_type=self._join_type(
                        relation, traversal_min,
                        task.spec.domain_policy.unmatched if isinstance(task, AggregateNode) else "EXCLUDE_UNMATCHED",
                    ),
                    cardinality=str(traversal_max),
                ))
                joined_sources.add(target_source)
                remaining_relations.remove(relation)
                progressed = True
            if not progressed:
                raise BindingError("cross-source relation tree could not be oriented")
        if not isinstance(task, AggregateNode):
            raise BindingError("cross-source SELECT is not supported")
        def compute_expr(expr):
            if isinstance(expr, AttributeExpr):
                attribute = self.binder._attribute(expr.concept)
                return ColumnExpr(source=compute_aliases[attribute.entity],
                                  name=f"{self._local(attribute.entity)}__{attribute.column}")
            if getattr(expr, "kind", None) == "binary":
                return expr.model_copy(update={"left": compute_expr(expr.left), "right": compute_expr(expr.right)})
            if getattr(expr, "kind", None) == "time_bucket":
                return expr.model_copy(update={"value": compute_expr(expr.value)})
            if isinstance(expr, AggregateExpr):
                return expr.model_copy(update={"value": compute_expr(expr.value) if expr.value else None})
            return expr

        dimensions = [QueryOutput(name=name, expression=compute_expr(expr))
                      for name, expr in logical_aggregate.dimensions]
        if preaggregate:
            partial_source = next(source.alias for source, fragment in zip(input_sources, fragments)
                                  if fragment.source_instance == preaggregate["source"])
            final_function = AggregateFunction.SUM if preaggregate["function"] == AggregateFunction.COUNT \
                else preaggregate["function"]
            aggregate = AggregateExpr(
                function=final_function,
                value=ColumnExpr(source=partial_source, name="__partial_value"),
            )
        else:
            aggregate = compute_expr(logical_aggregate.aggregate)
        query = QueryIR(
            source=input_sources[0], joins=joins, dimensions=dimensions,
            outputs=[QueryOutput(name=task.spec.measure.output, aggregate=aggregate)],
            result_predicate=self._compute_result_predicate(task.spec.result_filter,
                                                            task.spec.measure.output),
            order_by=([OrderKey(field=task.spec.ranking.by, direction=task.spec.ranking.direction),
                       *task.spec.ranking.tie_breakers] if task.spec.ranking else []),
            limit=task.spec.ranking.take if task.spec.ranking else None,
        )
        compute_id = f"p_{task.id}_compute"
        compute = ComputeFragment(
            id=compute_id, name=task.name, inputs=compute_inputs, query=query,
            depends_on=[exchange.id for exchange in exchanges],
            realizes=[LogicalOutputBinding(logical_node=task.id, physical_result="result_set")],
        )
        self.trace.rules.append(RuleDecision(
            rule="cross_source_fragmentation", outcome="applied", logical_nodes=[task.id],
            reason="task spans multiple source instances; source projection + temporary compute selected",
            details={"sources": binding.source_instances,
                     "compute_engine": self.compute_engine_name,
                     "compute_engine_type": self.compute_engine_type},
        ))
        return [*fragments, *exchanges, compute]

    def _compute_result_predicate(self, predicate, output_name):
        if predicate is None:
            return None
        def expression(value):
            if isinstance(value, OutputExpr):
                return OutputExpr(name=output_name if value.name == output_name else value.name)
            return value
        if getattr(predicate, "kind", None) == "comparison":
            return predicate.model_copy(update={"left": expression(predicate.left),
                                                "right": expression(predicate.right)})
        if getattr(predicate, "kind", None) in ("and", "or"):
            return predicate.model_copy(update={
                "operands": [self._compute_result_predicate(value, output_name)
                             for value in predicate.operands],
            })
        return predicate

    def _preaggregate_candidate(self, task, binding: SemanticTaskBinding, logical_aggregate):
        if not isinstance(task, AggregateNode) or not isinstance(logical_aggregate.aggregate, AggregateExpr):
            return None
        aggregate = logical_aggregate.aggregate
        if aggregate.function not in {AggregateFunction.SUM, AggregateFunction.COUNT,
                                      AggregateFunction.MIN, AggregateFunction.MAX}:
            return None
        subject = task.spec.subject.entity
        subject_source = self.binder._entity(subject).source_instance
        value_sources = {self.binder._attribute(value).source_instance
                         for value in expression_attributes(aggregate.value)}
        if value_sources and value_sources != {subject_source}:
            return None
        boundary_keys: list[str] = []
        for relation in binding.relations:
            from_source = self.binder._entity(relation.from_entity).source_instance
            to_source = self.binder._entity(relation.to_entity).source_instance
            if from_source == to_source:
                continue
            if from_source == subject_source:
                maximum = relation.from_to.max
                keys = relation.from_attributes
            elif to_source == subject_source:
                maximum = relation.to_from.max
                keys = relation.to_attributes
            else:
                continue
            if (maximum != 1 or relation.integrity_mode not in {"ENFORCED", "DECLARED"}
                    or relation.confidence < 1):
                self.trace.rules.append(RuleDecision(
                    rule="cross_source_preaggregation", outcome="rejected", logical_nodes=[task.id],
                    reason="relation cardinality/integrity does not prove a many-to-one boundary",
                    details={"relation": relation.concept, "max": maximum,
                             "integrity": relation.integrity_mode,
                             "confidence": relation.confidence},
                ))
                return None
            boundary_keys.extend(keys)
        if not boundary_keys:
            return None
        self.trace.rules.append(RuleDecision(
            rule="cross_source_preaggregation", outcome="applied", logical_nodes=[task.id],
            reason="decomposable aggregate and trusted many-to-one relation boundary",
            details={"source": subject_source, "group_keys": boundary_keys},
        ))
        return {"source": subject_source, "keys": list(dict.fromkeys(boundary_keys)),
                "function": aggregate.function}

    def _calculate(self, task: CalculateNode, dependencies: list[str]) -> CapabilityFragment:
        return CapabilityFragment(
            id=f"p_{task.id}", name=task.name, operator=Operator.CALCULATE,
            resolver="(compute)",
            call={"node_id": f"p_{task.id}", "mode": "calculate",
                  "spec": task.spec.model_dump(mode="json"),
                  "input_refs": {name: value.model_dump(mode="json")
                                 for name, value in task.inputs.items()}},
            depends_on=dependencies,
            realizes=[LogicalOutputBinding(logical_node=task.id, physical_result="result_set")],
        )

    def _capability(self, task, dependencies: list[str]) -> CapabilityFragment:
        resolver = self._concept_resolver(task)
        spec = task.spec.model_dump(mode="json", exclude_none=True)
        call = {
            "node_id": f"p_{task.id}", **spec,
            "input_refs": {name: value.model_dump(mode="json")
                           for name, value in task.inputs.items()},
        }
        if isinstance(task, SearchNode):
            call["mode"] = "search"
        elif isinstance(task, BrowseNode):
            call["mode"] = "browse"
        if isinstance(task, AskNode):
            call["prompt"] = spec["instruction"]
        return CapabilityFragment(
            id=f"p_{task.id}", name=task.name, operator=task.operator,
            resolver=resolver, call=call, depends_on=dependencies,
            realizes=[LogicalOutputBinding(logical_node=task.id, physical_result="result")],
        )

    def _concept_resolver(self, task) -> str:
        for resolver in self.registry.all_resolvers() if self.registry else []:
            if self._allowed(resolver.name) and task.operator.value in resolver.operators:
                return resolver.name
        raise BindingError(f"no resolver supports {task.operator.value}")

    @staticmethod
    def _join_type(relation, traversal_min, unmatched_policy: str):
        if unmatched_policy == "EXCLUDE_UNMATCHED":
            return "INNER"
        if unmatched_policy == "KEEP_AS_UNKNOWN":
            return "LEFT"
        if unmatched_policy == "ERROR_ON_UNMATCHED":
            if (traversal_min == 1 and relation.integrity_mode in {"ENFORCED", "DECLARED"}
                    and relation.confidence >= 1):
                return "INNER"
            raise BindingError(
                f"ERROR_ON_UNMATCHED requires trusted mandatory relation: {relation.concept}"
            )
        raise BindingError(f"unknown unmatched policy: {unmatched_policy}")

    def _condition_expression(self, expression, predicate):
        """Apply a task-local predicate to every aggregate leaf in a metric expression."""
        if isinstance(expression, AggregateExpr):
            return expression.model_copy(update={
                "filter": combine_conjuncts([*split_conjuncts(expression.filter), predicate])
            })
        if getattr(expression, "kind", None) == "binary":
            return expression.model_copy(update={
                "left": self._condition_expression(expression.left, predicate),
                "right": self._condition_expression(expression.right, predicate),
            })
        raise BindingError("conditional fusion requires aggregate-leaf metric expressions")

    def _resolver(self, name: str):
        if not self._allowed(name):
            raise BindingError(f"source is not allowed: {name}")
        resolver = self.registry.resolver(name) if self.registry else None
        if resolver is None:
            raise BindingError(f"resolver not found: {name}")
        return resolver

    @staticmethod
    def _local(concept_id: str) -> str:
        return concept_id.split("::")[-1].split(".")[-1]

    @staticmethod
    def _waves(plan: PhysicalExecutionPlan) -> None:
        waves = topo_waves(plan.nodes)
        for wave_no, nodes in enumerate(waves, start=1):
            for node in nodes:
                node.wave = wave_no
        plan.context["max_wave"] = len(waves)
