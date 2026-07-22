# Data Nexus 设计文档（唯一真相源）

> 一张本体图、一张语义任务图、一张物理执行图——联结数据、知识、智能体与行动。
>
> 本文定义 Data Nexus 的目标架构。配套 UI 规范见 [data_nexus_ui_design.md](data_nexus_ui_design.md)。

## 0. 文档状态与已确定决策

本项目仍处于设计阶段，本轮查询代数与执行计划采用 **clean break**：实现时直接替换旧结构，不保留旧 SQG、`QuerySpec`、`PROJECT` 拆分节点、历史运行记录或缓存的兼容分支。

> **实现状态（2026-07-22）**：本章定义的 clean-break 核心已落地：graph v3 relation/metric、typed Expression/Predicate、业务粒度 SQG、Semantic Binding、Bound Logical Plan、Fragment PEP、`realizes` 逻辑结果映射、同源融合、跨源 Source + DuckDB Compute、可信 N:1 预聚合、typed SQL Server/DuckDB renderer、Optimizer artifacts 和前端双图浏览。**未修改数据库表结构**；Optimizer 三步产物复用已有 `nexus.run_stage.logs` 保存。

已经确定的边界：

1. **SQG 是面向人的“解决问题思路 DAG”**，不是关系代数树。
2. 一个 SQG 节点是一项可独立命名、可产生中间结论的业务任务；节点粒度以人在图上能一眼理解为准。
3. 节点内部使用强类型规格完整表达范围、维度、统计、排名和结果契约；不能因为执行效率把多个独立业务任务预先合并。
4. `FILTER`、`JOIN`、`ALIGN`、`SORT`、`LIMIT`、`PROJECT` 不作为用户可见 SQG 算子。
5. 多个 SQG 任务是否共享扫描、JOIN、聚合或同一条查询，由 Optimizer 决定。
6. PEP 是物理 Fragment DAG；一个物理 Fragment 可以通过 `realizes` 实现多个 SQG 结果，不再生成“合并节点 + PROJECT 拆分节点”。
7. 跨源关系属于一个业务任务内部的语义依赖，不拆成 SQG 节点；Optimizer 根据本体关系生成 Source/Exchange/Compute Fragment。
8. `ASK` 和 `ACT` 各保持一个高层算子。确定性计算必须由 `AGGREGATE` 或 `CALCULATE` 完成，不能交给 ASK 口算。
9. 本体关系必须记录方向性基数、可选性和完整性来源。用户新建或编辑关系时必须明确选择；无法确认时必须显式选择“未知”，优化器按保守策略处理。

术语：

| 术语 | 定义 |
|---|---|
| **Ontology** | 业务概念、属性、指标、关系、能力及物理绑定构成的语义图 |
| **SQG** | Semantic Query Graph，面向人的高层业务任务 DAG |
| **Bound Logical Plan** | Optimizer 内部使用的关系计划；不作为用户思路图展示 |
| **PEP** | Physical Execution Plan，按执行位置切分后的物理 Fragment DAG |
| **Source Instance** | 一个具体的 Resolver 注册实例，如某个 SQL 库或某组 CSV，而不是笼统的 resolver 类型 |
| **Fragment** | 可在同一执行位置一次编译/执行的最大物理子计划 |
| **Exchange** | Fragment 之间的数据传输、物化或广播边界 |
| **Logical Result** | SQG 节点产生的业务结果，由 PEP 的 `realizes` 映射到物理输出 |

---

## 1. 总体架构与运行管线

### 1.1 三张图

Data Nexus 同时维护三种不同目的的图：

```text
Ontology：系统知道什么、概念如何关联、落在哪些源
    ↓
SQG：解决用户问题需要完成哪些业务步骤
    ↓
PEP：这些步骤在哪里执行、如何融合、如何交换数据
```

三张图不能混用：

- Ontology 不记录某一次查询的执行策略。
- SQG 不出现表名、SQL、Resolver、JOIN 或临时表。
- PEP 可以自由融合 SQG 节点，但必须保留逻辑输出映射和血缘。

### 1.2 五阶段运行管线

```text
用户问题
  → Initializer：选择本体、准备可用概念/指标/能力上下文
  → Compiler：自然语言 → typed SQG
  → Optimizer：SQG → Bound Logical Plan → PEP
  → Coordinator：按 PEP 分波并行执行，维护逻辑结果注册表
  → Generator：确定性表格/Markdown 答案 + 血缘 + 动作回执
```

可选 Harness 位于整条管线之外，用于评估一轮结果并决定是否重新编译；它不是 SQG 或 PEP 算子。

### 1.3 不变量

1. 逻辑层只引用 concept id 和逻辑节点输出。
2. 物理绑定只由 Ontology/Binding 提供，Compiler 不猜表名和列名。
3. JOIN 路径只从本体 relation 推导，禁止按同名列自动关联。
4. 任何优化都必须证明结果 schema、grain、domain、NULL 规则和精确性不变。
5. 数值、日期、排名和派生值必须可复算；LLM 只负责理解和表达。
6. 用户权限在源头强制；不同用户安全域的扫描不得融合或共享缓存。

---

## 2. 本体与关系模型

### 2.1 Graph 存储形态

一份本体仍以单块 graph JSON 保存，运行时摊平成 `Concept + Binding`。目标结构：

```jsonc
{
  "version": 3,
  "entities": [],
  "relations": [],
  "metrics": [],
  "derivations": [],
  "actions": [],
  "resolvers": []
}
```

概念 kind：

| kind | 含义 | 物理绑定 |
|---|---|---|
| `entity` | 业务对象或事件集合 | 表、文件、端点对象 |
| `attribute` | entity 的字段 | 列或字段路径 |
| `relation` | entity 之间可导航的业务关系 | 无；端点属性各自有绑定 |
| `metric` | 可治理、可复算的业务指标 | 无；使用 typed expression |
| `derivation` | 产物之间的血缘/派生关系 | 可选能力绑定 |
| `action` | 具名业务动作 | Action Resolver |

多本体运行时，所有 concept id 使用 `ontology_id::concept.id` 命名空间；物理表名、列名和 Resolver 名不加此前缀。跨本体没有 relation 时，不允许在一个结构化查询任务中直接聚合。

### 2.2 Entity 与 Attribute

```jsonc
{
  "id": "entity.fact_order",
  "name": "订单",
  "resolver": "sales_csv",
  "table": "fact_order.csv",
  "key": "order_id",
  "attributes": [
    {
      "id": "attribute.fact_order.amount",
      "name": "销售额",
      "column": "amount",
      "role": "measure",
      "dtype": "number",
      "additivity": "additive",
      "constraints": {
        "nullable": false,
        "unique": false,
        "primary_key": false,
        "source": "imported"
      }
    }
  ]
}
```

属性语义：

- `role`: `dimension | measure`。
- `dtype`: `number | text | date | datetime | bool | unknown`。
- `additivity`: `additive | semi_additive | non_additive`，仅用于 measure。
- `constraints` 是源结构事实，用于关系推断和优化证明，不替代 relation。
- `resolver` 是具体 Source Instance 名；两个实体都使用 SQL Resolver 类型，并不代表它们同源。

### 2.3 Metric 使用 typed expression

Metric 不再使用需要字符串解析的 SQL-like `expr`，改为方言中立表达式 AST：

```jsonc
{
  "id": "metric.gross_profit",
  "name": "毛利",
  "expression": {
    "kind": "aggregate",
    "function": "SUM",
    "value": {
      "kind": "binary",
      "operator": "SUBTRACT",
      "left": { "kind": "attribute", "concept": "attribute.fact_order.amount" },
      "right": { "kind": "attribute", "concept": "attribute.fact_order.cost" }
    },
    "nulls": "IGNORE"
  },
  "result_type": "decimal",
  "unit": "CNY"
}
```

表达式类型至少包括：

- `attribute`、`literal`、`node_output`；
- `binary`：加减乘除、`SAFE_DIVIDE`；
- `case`、`coalesce`、`cast`；
- `time_bucket`；
- `aggregate`；
- 必要时的窗口表达式。

所有表达式先做类型检查，再由 SQL Server、DuckDB 或其他方言 Renderer 渲染。

### 2.4 Relation：方向性 Multiplicity + Optionality + Integrity

关系是 Optimizer 进行 JOIN、预聚合和行数推断的唯一依据。目标结构：

```jsonc
{
  "id": "relation.order_customer",
  "name": "订单所属客户",
  "from": {
    "entity": "entity.fact_order",
    "attribute": "attribute.fact_order.customer_id"
  },
  "to": {
    "entity": "entity.dim_customer",
    "attribute": "attribute.dim_customer.customer_id"
  },
  "multiplicity": {
    "from_to": { "min": 1, "max": 1 },
    "to_from": { "min": 0, "max": "many" }
  },
  "integrity": {
    "mode": "ENFORCED",
    "source": "DATABASE_FOREIGN_KEY",
    "constraint_name": "FK_order_customer",
    "confidence": 1.0
  },
  "temporal": null,
  "semantics": "每张订单属于一个客户"
}
```

方向定义无歧义：

- `from_to`：一行 from 最少/最多匹配多少行 to。
- `to_from`：一行 to 最少/最多匹配多少行 from。
- `min=0` 表示该方向可选，`min=1` 表示必选。
- `min=unknown` 表示用户明确选择“不知道是否必须匹配”，优化器不得假设参与完整性。
- `max=1 | many | unknown` 表示方向性基数。

常见映射：

| UI 关系类型 | `from_to.max` | `to_from.max` |
|---|---:|---:|
| 多对一 N:1 | 1 | many |
| 一对多 1:N | many | 1 |
| 一对一 1:1 | 1 | 1 |
| 多对多 N:M | many | many |
| 未知 | unknown | unknown |

`integrity.mode`：

- `ENFORCED`：源系统真实约束且可信；
- `DECLARED`：业务人员明确声明，但源系统不强制；
- `INFERRED`：系统根据样本/列特征推断；
- `UNKNOWN`：无法保证，优化器不得做依赖基数的激进改写。

`temporal` 用于缓慢变化维、历史组织关系等：

```jsonc
{
  "fact_time": "attribute.fact_order.order_date",
  "valid_from": "attribute.customer_region.valid_from",
  "valid_to": "attribute.customer_region.valid_to"
}
```

#### Relation 不固定 JOIN 类型

本体描述业务事实，不固定每次查询都使用 INNER 或 LEFT JOIN。实际 JOIN 语义由任务的 domain policy 决定：

- `EXCLUDE_UNMATCHED`：未匹配事实不进入结果；
- `KEEP_AS_UNKNOWN`：保留并归入“未知”；
- `ERROR_ON_UNMATCHED`：发现未匹配即报告数据质量问题。

Relation 的可选性帮助 Optimizer 判断风险，但不能机械替代查询语义。

### 2.5 关系录入和导入

用户手工新建/编辑关系时必须完成：

1. 选择 from entity 和属性；
2. 选择 to entity 和属性；
3. 选择关系类型 N:1、1:N、1:1、N:M 或未知；
4. 分别回答“每条 from 是否必须匹配 to”和“每条 to 是否必须被 from 匹配”；答案为必须、可以没有或未知；
5. 确认完整性来源；
6. 阅读双向自然语言预览后保存。

SQL 导入可预填：

- FK + 被引用 PK/UNIQUE → from→to 最大 1；
- FK 列 NOT NULL → from→to 最小 1，否则 0；
- FK 列自身 UNIQUE → to→from 最大 1，否则 many；
- 真实 FK 约束 → `ENFORCED`；
- 复合外键必须作为一个整体关系导入。

CSV、API 或跨源关系通常无法自动证明。系统可以给候选和置信度，但用户必须确认；显式选择“未知”时仍可执行，只禁用不安全的预聚合、JOIN 重排和 fan-out 假设。

### 2.6 本体校验

发布或运行前至少检查：

- entity/attribute/metric/relation id 唯一；
- relation 端点属性存在且属于对应 entity；
- relation multiplicity 两个方向均已填写；
- `ENFORCED` 关系必须有可追溯的约束来源；
- N:M 建议显式建桥 entity；没有桥实体时标记高风险；
- metric expression 类型合法，统计函数与 additivity 兼容；
- 引用的 Resolver 存在、启用且属于本体允许集；
- relation 图能够连通一个结构化任务所引用的实体。

---

## 3. Resolver 与能力模型

### 3.1 统一能力接口

Resolver 负责具体执行位置的能力声明、编译和执行：

```python
class Resolver:
    def capabilities(self) -> Capabilities: ...
    def describe(self) -> SourceSchema: ...
    def compile(self, fragment) -> PlannedCall: ...
    def fetch(self, call, context) -> NodeResult: ...
```

类型示例：SQL、CSV/DuckDB、Web IQ、Agent、Action、REST、向量检索。

### 3.2 Source Instance

物理同源判断使用 Source Instance，而不是 resolver 类型：

```text
sql_sales_prod 与 sql_masterdata 都是 SQL，但不是同一 Source Instance。
csv_orders 与 csv_returns 都是 CSV，也可能使用不同凭据和位置。
```

Source Instance 标识至少包含：

- Resolver 注册名；
- 凭据/连接目标；
- 数据库或文件集合；
- 用户安全域；
- 快照/一致性语义。

只有这些要素兼容时才允许共享扫描或下推 JOIN。

### 3.3 Capabilities

能力不能只写“支持 AGGREGATE”，还要让 Optimizer 能判断具体下推：

```jsonc
{
  "logical_operators": ["SELECT", "AGGREGATE", "SEARCH", "BROWSE"],
  "relational": {
    "filter": ["EQ", "IN", "GT", "BETWEEN", "LIKE"],
    "join": ["INNER", "LEFT"],
    "aggregates": ["SUM", "COUNT", "AVG", "MIN", "MAX", "MEDIAN", "PERCENTILE"],
    "time_grains": ["DAY", "WEEK", "MONTH", "QUARTER", "YEAR"],
    "window": true,
    "top_n": true,
    "conditional_aggregate": true,
    "temporary_table": false
  },
  "limits": {
    "max_parameters": 2100,
    "max_concurrency": 8
  },
  "cost": {
    "typical_latency_ms": 300,
    "egress_cost": 0.2
  },
  "user_scoped": true
}
```

缺失能力不是错误：Optimizer 可以把不支持的部分提升到 Compute Fragment。

---

## 4. SQG：面向人的高层语义任务 DAG

### 4.1 节点粒度

一个步骤成为 SQG 节点，应同时满足多数条件：

- 能用一句业务语言清楚命名；
- 产生可独立查看、验证或复用的中间结论；
- 后续步骤会消费该结论；
- 用户能从 DAG 直接理解“为什么需要这一步”。

因此：

```text
合理：华东2024年销售额 → 生成报告 → 发邮件
过细：扫描订单 → 过滤年份 → JOIN 区域 → SUM → SORT → LIMIT
过粗：查询所有数据并生成报告
```

### 4.2 高层算子集

| 算子 | 业务含义 |
|---|---|
| `SELECT` | 查询、列举或查找结构化业务对象/字段 |
| `AGGREGATE` | 完成一项统计、分组或排名任务 |
| `CALCULATE` | 对上游结果进行确定性比较、对齐、算术或选择 |
| `SEARCH` | 搜索公开 Web 信息 |
| `BROWSE` | 读取明确 URL/文档 |
| `ASK` | 根据已有结果生成解释、总结或报告 |
| `ACT` | 执行邮件、工单、写回等业务动作 |

不是 SQG 算子：

- `FILTER`：属于 SELECT/AGGREGATE 的 `scope`；
- `JOIN`：由本体 relation 和 Optimizer 推导；
- `SORT/LIMIT`：属于 `ranking` 或 `selection`；
- `ALIGN`：属于 CALCULATE 的输入对齐契约；
- `PROJECT/SHAPE`：属于结果契约或物理 Fragment 内部操作。

### 4.3 节点公共外壳

SQG 是 discriminated union，`operator` 决定 `spec` 的强类型：

```jsonc
{
  "id": "east_sales",
  "operator": "AGGREGATE",
  "name": "华东2024年销售额",
  "depends_on": [],
  "inputs": {},
  "spec": {}
}
```

规则：

- `id` 在一次 SQG 内唯一且稳定；
- `name` 是用户可读的任务名称；
- `depends_on` 表达控制依赖：当前节点必须等待哪些上游节点完成；有依赖不代表一定消费其输出；
- `inputs` 表达数据依赖：输入名映射到上游 `{node, output?, row?}`；不填 `output/row` 时接收完整结果；
- 每个 `inputs.*.node` 必须同时出现在 `depends_on`，但 `depends_on` 可以包含不传数据的控制依赖，即 `input nodes ⊆ depends_on`；
- 上游 output 保留原始类型，可以是表、行、列、标量、文档或文本；
- 所有没有下游消费者的终点节点都属于最终答案；即使 Compiler 漏写，SQG 校验也会自动补入 `outputs`，避免独立子问题已执行却不展示；
- `outputs` 还必须显式保留用户要求在页面查看的非终点节点。混合“查询 A、查询 B、把 C 发邮件”应输出 A、B 和动作回执；只有 C 进入邮件报告链路；
- SQG 不包含 `resolver`、表名、列名、SQL、wave 或物理节点 id。

### 4.4 Typed Predicate 与 Scope

所有范围条件使用表达式 AST：

```jsonc
{
  "kind": "and",
  "operands": [
    {
      "kind": "time_range",
      "attribute": "attribute.fact_order.order_date",
      "start": "2024-01-01",
      "end_exclusive": "2025-01-01",
      "timezone": "Asia/Shanghai"
    },
    {
      "kind": "comparison",
      "left": { "kind": "attribute", "concept": "attribute.dim_region.area" },
      "operator": "EQ",
      "right": { "kind": "literal", "value": "华东", "data_type": "text" }
    }
  ]
}
```
  "id": "ratio",
  "operator": "CALCULATE",
  "name": "计算中位数与平均数之比",
  "depends_on": ["monthly_median", "monthly_average"],

支持 `and/or/not`、比较、`in`、`between`、空值、字符串匹配和显式时间区间。日期月/季/年必须编译成半开区间；不能依赖方言隐式转换。

### 4.5 SELECT Spec
  "spec": {
    "alignment": {
      "keys": ["order_month"],
      "domain": "INNER",
      "scalar_broadcast": true
```
    "outputs": [
      {
        "name": "median_avg_ratio",
        "expression": {
          "kind": "binary",
          "operator": "SAFE_DIVIDE",
          "left": { "kind": "node_output", "input": "median", "field": "median_amount" },
          "right": { "kind": "node_output", "input": "average", "field": "average_amount" },
          "zero_division": "NULL"
        }
      }
    ],
    "selection": {
      "kind": "MIN_BY",
      "field": "median_avg_ratio",
      "take": 1,
      "nulls": "LAST"
    },
    "result": {
      "kind": "TABLE",
      "name": "中位数与平均值比最低的月份",
      "grain": ["order_month"]
    }
  "dimensions": [
    {
      "kind": "attribute",
      "concept": "attribute.dim_region.area",
      "output": "region"
    }
  ],
  "measure": {
    "metric": "metric.sales_amount",
    "output": "sales_amount"
  },
  "ranking": {
    "by": "sales_amount",
    "direction": "DESC",
    "take": 3,
    "ties": "EXCLUDE",
    "tie_breakers": [
      { "field": "region", "direction": "ASC" }
    ]
  },
  "domain_policy": { "unmatched": "ERROR_ON_UNMATCHED" },
  "result": {
    "kind": "RANKING",
    "name": "销售额排名前三的区域",
    "grain": ["region"]
  }
}
```

没有预定义 metric 时可以使用 ad-hoc statistic：

```jsonc
{
  "value": { "kind": "attribute", "concept": "attribute.fact_order.amount" },
  "statistic": {
    "function": "PERCENTILE",
    "percentile": 0.5,
    "method": "CONTINUOUS",
    "accuracy": "EXACT",
    "nulls": "IGNORE"
  },
  "output": "median_amount"
}
```

通用统计函数至少支持：

- `SUM`、`COUNT`、`COUNT_DISTINCT`、`AVG`、`MIN`、`MAX`；
- `MEDIAN`、`PERCENTILE`；
- `VARIANCE`、`STDDEV`；
- 可扩展的近似统计，但必须显式标注 `accuracy=APPROXIMATE`。

时间维度使用显式 grain：

```jsonc
{
  "kind": "time",
  "attribute": "attribute.fact_order.order_date",
  "grain": "MONTH",
  "calendar": "GREGORIAN",
  "timezone": "Asia/Shanghai",
  "output": "order_month"
}
```

`result_filter`、`ranking` 是该业务统计任务的完整语义，不代表必须渲染成 SQL HAVING/TOP。

### 4.7 CALCULATE Spec

CALCULATE 用于“人能理解为一个独立思考步骤”的确定性计算。内部允许对齐、公式、排序和选择，但 UI 仍显示一个节点。

```jsonc
{
  "inputs": {
    "median": { "node": "monthly_median" },
    "average": { "node": "monthly_average" }
  },
  "alignment": {
    "keys": ["order_month"],
    "domain": "INNER",
    "scalar_broadcast": true
  },
  "outputs": [
    {
      "name": "median_avg_ratio",
      "expression": {
        "kind": "binary",
        "operator": "SAFE_DIVIDE",
        "left": { "kind": "node_output", "input": "median", "field": "median_amount" },
        "right": { "kind": "node_output", "input": "average", "field": "average_amount" },
        "zero_division": "NULL"
      }
    }
  ],
  "selection": {
    "kind": "MIN_BY",
    "field": "median_avg_ratio",
    "take": 1,
    "nulls": "LAST"
  },
  "result": {
    "kind": "TABLE",
    "name": "中位数与平均值比最低的月份",
    "grain": ["order_month"]
  }
}
```

如果两个输入 grain 不可对齐且未声明广播规则，编译失败，不能让 ASK 猜测对应关系。

### 4.8 SEARCH、BROWSE、ASK、ACT

这四个算子保持简单：

```jsonc
{ "operator": "SEARCH", "spec": { "query": "...", "max_results": 10 } }
{ "operator": "BROWSE", "spec": { "url": "https://...", "max_length": 30000 } }
{ "operator": "ASK", "spec": { "instruction": "根据输入生成销售报告", "format": "MARKDOWN" } }
{ "operator": "ACT", "spec": { "action": "EMAIL.SEND", "recipient": "颜斌" } }
```

依赖上游结果的 SEARCH 必须用节点级 `inputs` 接收 output，不能把“销量最高的产品”等抽象指代直接发给搜索服务：

```jsonc
{
  "operator": "SEARCH",
  "depends_on": ["top_product"],
  "inputs": {
    "product_name": { "node": "top_product", "output": "product", "row": 0 }
  },
  "spec": {
    "query": "{product_name} 最新新闻",
    "max_results": 10
  }
}
```

Compiler 校验 input node 属于 `depends_on`、选择的 output 存在于上游 Result Contract，以及文本中的 `{input_name}` 已声明。Coordinator 保留输入原始类型；仅当目标参数是格式字符串时才转成文本。单纯的 `depends_on` 只控制顺序，不会自动传递数据。

约束：

- ASK 只能解释和组织输入，不得重新计算数值、排名或比率；
- ACT 的收件人解析、重名校验、幂等和具体 API 调用属于 Action Resolver 内部契约；
- EMAIL.SEND 必须从 ASK 选择单个文本标量：`{"node":"report","output":"value","row":0}`；完整表不能直接填入 `{report}` 文本参数；
- 若 ACT 无法唯一解析对象，应失败并返回明确业务错误，不应由 SQG 拆出多个技术节点。

### 4.9 Result Contract

每个结构化节点必须有可验证的结果契约：

- `kind`: `SCALAR | TABLE | RANKING | DOCUMENT | TEXT | ACTION`；
- `fields`: 业务字段名、类型、单位和可空性；
- `grain`: 一行由哪些语义键唯一确定；
- `domain`: 覆盖范围和未匹配策略；
- `ordering`: 若结果有业务顺序，说明排序键；
- `lineage`: 字段来自哪些 concept/逻辑节点。

Compiler 给出业务别名和预期形态，类型检查器根据本体和表达式推导其余字段并验证。

---

## 5. Initializer 与 Compiler

### 5.1 Initializer

职责：

1. 根据问题和用户显式选择确定一个或多个候选本体；
2. 合并 namespaced concept catalog；
3. 准备可用 Resolver/operator/statistic 能力；
4. 准备指标、关系、属性描述及必要的 RAG 上下文；
5. 将本体选择与上下文交给 Compiler。

路由缓存：相同规范化问题 + 相同候选本体集合使用一小时滑动过期；命中后续期。缓存只保存路由决定，不缓存用户数据。

### 5.2 Compiler

Compiler 的职责是形成业务任务图，而不是决定查询融合：

1. 拆解用户子意图；
2. 映射 concept id；
3. 按业务任务粒度创建节点；
4. 生成各节点 typed spec；
5. 建立业务依赖；
6. 运行结构与语义校验；
7. 失败时把结构化错误反馈给 LLM 重新编译。

编译器明确禁止：

- 为节省查询把“华东销售额”和“华南销售额”合成一个 SQG 节点；
- 生成物理表、列、SQL、JOIN；
- 把确定性计算写进 ASK prompt；
- 用未声明关系连接同名字段。

### 5.3 编译期校验

至少包括：

- DAG 无环、依赖存在；
- operator 与 spec discriminated union 匹配；
- concept 存在且类型正确；
- scope predicate 类型可比较；
- group dimension 与 statistic 合法；
- additivity、时间 grain、精确性要求合法；
- 一个结构化任务引用的实体在 relation 图中连通；
- CALCULATE 输入 grain 可对齐；
- TopN/极值选择具有确定性 tie-breaker；
- ASK/ACT 能力在本体允许集中可用。

Compiler 缓存只缓存校验成功、非空的 SQG；键至少包含规范化问题、本体 id 集合、本体内容指纹和可用算子/统计能力，一小时滑动过期。本体内容变化必须使缓存失效。

---

## 6. Optimizer：SQG 到 PEP

### 6.1 三步 Lowering

Optimizer 内部按三步工作：

```text
Typed SQG
  → Semantic Binding：concept → entity/attribute/metric/relation/source
  → Bound Logical Plan：Scan/Filter/Relate/Derive/Aggregate/Window/TopN
  → Physical PEP：Source Fragment + Exchange + Compute Fragment + ASK/ACT
```

三个箭头后的产物都必须保存，不能只保存最终 PEP：

| 步骤 | 持久化产物 | 回答的问题 |
|---|---|---|
| Semantic Binding | `semantic_binding` | 每个 concept 解析成了什么 entity/attribute/metric，选择了哪些 relation path 和 Source candidates？ |
| Bound Logical Plan | `bound_logical_plan` | 在不考虑执行位置和方言时，逻辑上究竟要做哪些 Scan/Filter/Join/Aggregate/TopN？ |
| Physical Planning | `physical_execution_plan` | 最终在哪里执行、如何融合/下推、如何 Exchange，哪些物理输出实现哪些 SQG 结果？ |

#### IR 是什么

IR = **Intermediate Representation（中间表示）**。它是 Compiler/Optimizer 在“用户友好的 SQG”和“可执行 PEP/SQL”之间使用的一种**结构化、强类型、可序列化的数据模型**，不是某段 SQL，也不是临时 Python 对象。

`Bound Logical Plan` 可逐词理解：

- **Bound**：SQG 中的 concept 已绑定到规范化 metric expression、entity、attribute、relation path 和候选 Source Instance；不再是模糊业务词。
- **Logical**：只表达“必须做什么运算”，还没有决定“在哪个引擎、用哪种 JOIN 算法、是否广播、生成什么方言 SQL”。
- **Plan**：运算以有依赖的树/DAG 表达。
- **IR**：供类型检查、grain/domain/cardinality 推导、规则改写、成本估算和物理切分共同使用的中间语言。

例如 SQG 上只有“销售额排名前三的区域”，Bound Logical Plan 可以是：

```text
TOP_N 3 BY sales_amount DESC
  └─ AGGREGATE SUM(amount) BY region
       └─ RELATE relation.order_customer, relation.customer_region
            ├─ FILTER/SCAN entity.fact_order
            ├─ SCAN entity.dim_customer
            └─ SCAN entity.dim_region
```

它比 SQG 细，适合优化器推理；又没有 SQL 方言、Fragment 和 Exchange，仍不是 PEP。

#### Optimizer Artifact 契约

三个产物使用稳定 id 串联，并带统一外壳：

```jsonc
{
  "artifact_id": "opt_01_bound_logical_plan",
  "run_id": "...",
  "stage": "optimizer",
  "artifact_type": "bound_logical_plan",
  "schema_version": 3,
  "producer_version": "optimizer-3",
  "state": "complete",
  "input_artifact_id": "opt_00_semantic_binding",
  "input_hash": "...",
  "content": {},
  "diagnostics": [],
  "created_at": "2026-07-22T00:00:00Z"
}
```

要求：

1. `artifact_type ∈ semantic_binding | bound_logical_plan | physical_execution_plan | optimization_trace`。
2. `state ∈ complete | partial | failed`；即使某步失败，也保存已形成的 partial content 和 diagnostics，便于排错。
3. 节点使用稳定 id，并保存 `origin_sqg_nodes`、`input_artifact_id` 和前后映射，使 UI 可以跨三层高亮。
4. artifact 必须是方言中立 JSON；Compiled SQL/API call 仍记录在 PEP 节点运行详情中。
5. 缓存命中时仍为本次 run 保存一份 artifact 引用/快照，并标记 `cache_hit`、原 artifact 和版本，保证历史可复现。
6. 凭据、token 和敏感 literal 必须脱敏；artifact 浏览遵循 run 的访问控制。

除三份阶段结果外，Optimizer 还应保存 `optimization_trace`：

- 应用了哪些规则；
- 哪些规则因 grain/domain/cardinality/权限/能力不满足而被拒绝；
- 生成了哪些物理候选；
- 每个候选的 rows/bytes/cost；
- 最终选择某个 PEP 的原因。

三份结果用于看“每一步变成了什么”，trace 用于解释“为什么这样变”。

### 6.2 PEP 节点类型

| kind | 含义 |
|---|---|
| `SOURCE_FRAGMENT` | 在一个 Source Instance 内可一次编译执行的最大子计划 |
| `EXCHANGE` | 跨执行位置传输、物化、广播或参数化键传递 |
| `COMPUTE_FRAGMENT` | 在 DuckDB/计算引擎执行 JOIN、聚合、窗口或派生计算 |
| `ASK` | 一次 Agent/LLM 调用 |
| `ACT` | 一次 Action Resolver 调用 |

Fragment 内部可以包含多个关系算子，但默认 PEP 图把它显示为一个执行单元；点击节点再查看内部 operator tree。

`operator_tree` 本身也是 discriminated typed IR，至少包含：

| 内部算子 | 关键字段 |
|---|---|
| `SCAN` | Source object、snapshot、required columns |
| `FILTER` | typed Predicate + input |
| `JOIN` | relation id、join semantics、left/right、已证明的 cardinality |
| `PROJECT/DERIVE` | 命名 typed Expression 列表 |
| `AGGREGATE` | group keys、partial/final aggregate state、input |
| `WINDOW` | partition/order/window expression |
| `TOP_N` | typed order keys、take、ties、input |

物理字段使用 `ColumnRef`，常量使用 typed literal，任何节点都不保存待解析的 SQL 表达式字符串。本文后续 PEP 示例中的 `"region=华东"`、`"sales_amount DESC"` 等字符串只是为了阅读简洁的**摘要写法**；正式模型必须使用对应 typed Predicate/Order Expression，最终 SQL 只存在于 Renderer 产出的 compiled call 中。

### 6.3 PEP Schema

```jsonc
{
  "version": 3,
  "nodes": [
    {
      "id": "p_region_metrics",
      "kind": "SOURCE_FRAGMENT",
      "source_instance": "sales_sql",
      "operator_tree": {},
      "depends_on": [],
      "wave": 1,
      "realizes": [
        {
          "logical_node": "east_sales",
          "logical_field": "value",
          "physical_field": "east_sales"
        }
      ],
      "estimates": { "rows": 1, "bytes": 64, "cost": 0.12 }
    }
  ],
  "context": {
    "parallelism": 4,
    "security_domain": "user:yanbin",
    "logical_outputs": {}
  }
}
```

`realizes` 是逻辑/物理隔离的关键：

- 一个 PEP 节点可以实现多个 SQG 节点；
- 一个 SQG 节点也可能由多个 PEP Fragment 协作实现，最终映射由最后一个 Fragment 发布；
- Coordinator 使用映射注册逻辑结果；
- 不需要 PROJECT 物理节点。

### 6.4 融合策略

#### A. 扫描和公共子计划共享

满足以下条件时可共享：

- 相同 Source Instance、用户安全域和快照；
- 相同或可兼容的实体域/关系路径；
- 表达式和 NULL/时区/精确性规则兼容。

即使最终 group、HAVING 或 TopN 不同，也可以共享前缀后分支，不能再用“有 TopN 就完全禁止融合”的粗规则。

#### B. 同范围多测度融合

多个 SQG AGGREGATE 具有相同 scope 和 grain 时，一次扫描/分组输出多列：

```sql
SELECT region,
       SUM(amount) AS sales_amount,
       SUM(amount - cost) AS gross_profit
FROM ...
WHERE ...
GROUP BY region
```

#### C. 不同范围条件聚合

提取公共谓词到扫描层，差异谓词进入条件聚合：

```text
华东2024销售额
华南2024销售额
```

优化为：

```sql
WHERE order_date >= 2024-01-01
  AND order_date < 2025-01-01
  AND region IN ('华东','华南')

SUM(CASE WHEN region='华东' THEN amount END)
SUM(CASE WHEN region='华南' THEN amount END)
```

公共谓词是规范化 predicate AST 的公共合取项，不通过字符串比较得出。

#### D. 聚合共享、后处理分支

“销售额前三地区”和“毛利后三地区”可以共享扫描、关系和同 grain 聚合，然后各自排序和截断。SQG 仍保留两个业务节点。

#### E. 纵向下推

同一 Source Instance 支持时，可以把：

```text
Filter → TimeBucket → Aggregate → ResultFilter → TopN → Derive
```

编译成一条 SQL/查询；不支持的后缀提升到 Compute Fragment。

### 6.5 融合合法性

Optimizer 必须证明：

- grain 相同或显式可对齐；
- domain 和未匹配策略不变；
- 关系基数不会导致 fan-out；
- 公共谓词提取不产生原任务不存在的分组行；
- `NULL`、空集合、除零语义一致；
- time bucket 的时区、日历和粒度一致；
- exact/approximate 要求一致；
- 安全域和数据快照一致；
- 中间没有阻塞语义，如 DISTINCT、窗口、非确定函数或先 TopN 后聚合。

无法证明时保留独立计划，正确性优先于少一次扫描。

### 6.6 下推顺序

通常按以下顺序形成候选：

1. 列裁剪；
2. 单源谓词下推；
3. 同源 entity JOIN 下推；
4. 可证明安全的源内预聚合；
5. 完整聚合、时间桶和派生表达式下推；
6. 聚合后过滤下推；
7. 全局排序/TopN 下推；
8. 不支持部分放入 Compute Fragment。

下推由 capabilities 和语义证明共同决定；能力支持不代表一定下推。

### 6.7 成本选择

候选 PEP 至少比较：

- 估算行数、行宽和传输字节；
- 过滤选择率、分组基数；
- 源端 CPU/并发压力；
- 网络和 egress 成本；
- DuckDB 内存及溢写风险；
- 往返次数和典型延迟；
- 是否需要重复扫描；
- 源的信任、时效和用户权限能力。

缺少统计信息时采用保守规则，并把选择原因记录进 optimizer logs。

---

## 7. 跨源实体与关系处理

### 7.1 基本原则

1. SQG 节点只引用业务 metric/dimension，不写 JOIN 和数据源。
2. Optimizer 从引用概念提取实体，通过 relation 图求连接树。
3. Bound Logical Plan 标注每个 Scan 所属 Source Instance。
4. 同一 Source Instance 的连续子树先合并成 Source Fragment。
5. 跨 Source Instance 边形成 Exchange；最终在 Compute Fragment 或支持联邦能力的源完成。
6. 当前式“各源取数 → DuckDB JOIN → 聚合”作为通用兜底，但不是唯一策略。

### 7.2 跨源候选策略

#### 策略 A：投影/过滤后拉取，本地 JOIN

最通用。每个源只取必要列和满足本源谓词的行，Exchange 到 DuckDB 完成 JOIN、聚合和 TopN。

适用于无法证明预聚合安全、统计函数不可分解或关系复杂的场景。

#### 策略 B：事实侧预聚合

若事实→维度是可信 many-to-one，并且统计量可分解，则事实源先按 JOIN key 汇总，再跨源 JOIN：

```text
订单明细 5000 行
  → 按 customer_id SUM(amount) 约 1000 行
  → Exchange
  → 关联 customer→region
  → 按 region 再 SUM
```

#### 策略 C：维度先查 + Semi-Join 下推

当过滤位于小维表时：

1. 维度源先查满足条件的 key；
2. 通过参数列表、临时表或批量表值把 key 推给事实源；
3. 事实源只扫描相关数据。

必须考虑参数上限、key 数量和源是否支持临时表。

#### 策略 D：广播小表

小维表可以广播到计算引擎，或在目标源支持临时表时推入事实源做 JOIN。

#### 策略 E：联邦/远程 JOIN

只有 Resolver 明确声明联邦能力、权限和一致性满足要求时使用；不能因为两个实体都叫 SQL 就假设可跨库 JOIN。

### 7.3 聚合可分解性

| 统计量 | 可下推的部分状态 | 最终合并 |
|---|---|---|
| SUM | partial sum | SUM(partial_sum) |
| COUNT | partial count | SUM(partial_count) |
| MIN/MAX | partial extreme | MIN/MAX(partial) |
| AVG | SUM + COUNT | total_sum / total_count |
| VARIANCE/STDDEV | count + sum + sum_sq 或稳定状态 | merge state 后 finalize |
| 精确 MEDIAN/PERCENTILE | 通常不可仅合并分组中位数 | 拉明细或由同一引擎完整计算 |
| 近似分位数 | 可合并 sketch，前提是源支持同一算法 | merge sketch 后 finalize |

预聚合还必须满足：

- JOIN 不会复制事实行；
- 未匹配策略保持一致；
- 时间有效关系在预聚合 grain 中仍可正确关联；
- 度量 additivity 允许沿该维度汇总。

### 7.4 全局 TopN

TopN 必须应用于完整的全局聚合结果。禁止把各源/分片各自 Top 3 直接合并后当成全局 Top 3，除非使用可证明的分布式候选算法并进行最终全局排序。

### 7.5 示例：销售额排名前三的区域

SQG 仍只有一个业务节点：

```jsonc
{
  "id": "top_regions",
  "operator": "AGGREGATE",
  "name": "销售额排名前三的区域",
  "spec": {
    "subject": { "entity": "entity.fact_order" },
    "dimensions": [
      {
        "kind": "attribute",
        "concept": "attribute.dim_region.area",
        "output": "region"
      }
    ],
    "measure": { "metric": "metric.sales_amount", "output": "sales_amount" },
    "ranking": {
      "by": "sales_amount",
      "direction": "DESC",
      "take": 3,
      "ties": "EXCLUDE",
      "tie_breakers": [{ "field": "region", "direction": "ASC" }]
    },
    "domain_policy": { "unmatched": "ERROR_ON_UNMATCHED" },
    "result": { "kind": "RANKING", "grain": ["region"] }
  },
  "depends_on": []
}
```

假设：

```text
fact_order.csv --customer_id--> SQL dim_customer --region_id--> SQL dim_region
```

推荐 PEP：

```text
CSV Source Fragment：按 customer_id 预聚合 SUM(amount)
             │ Exchange
             ├──────────────┐
SQL Source Fragment：dim_customer JOIN dim_region，输出 customer_id→region
             │ Exchange     │
             └──────────────┤
DuckDB Compute Fragment：JOIN → 按 region 再 SUM → 全局 Top 3
```

对应的物理契约示意：

```jsonc
{
  "nodes": [
    {
      "id": "s_sales_by_customer",
      "kind": "SOURCE_FRAGMENT",
      "source_instance": "orders_csv",
      "operator_tree": {
        "kind": "AGGREGATE",
        "group_by": ["customer_id"],
        "outputs": [{ "name": "customer_sales", "aggregate": "SUM", "value": "amount" }],
        "input": { "kind": "SCAN", "entity": "entity.fact_order" }
      },
      "depends_on": [],
      "realizes": []
    },
    {
      "id": "s_customer_region",
      "kind": "SOURCE_FRAGMENT",
      "source_instance": "masterdata_sql",
      "operator_tree": {
        "kind": "PROJECT",
        "fields": ["customer_id", "region_id", "area"],
        "input": {
          "kind": "JOIN",
          "relation": "relation.customer_region",
          "left": { "kind": "SCAN", "entity": "entity.dim_customer" },
          "right": { "kind": "SCAN", "entity": "entity.dim_region" }
        }
      },
      "depends_on": [],
      "realizes": []
    },
    {
      "id": "x_sales",
      "kind": "EXCHANGE",
      "mode": "MATERIALIZE",
      "from": "s_sales_by_customer",
      "to": "c_top_regions",
      "depends_on": ["s_sales_by_customer"],
      "realizes": []
    },
    {
      "id": "x_region_map",
      "kind": "EXCHANGE",
      "mode": "BROADCAST",
      "from": "s_customer_region",
      "to": "c_top_regions",
      "depends_on": ["s_customer_region"],
      "realizes": []
    },
    {
      "id": "c_top_regions",
      "kind": "COMPUTE_FRAGMENT",
      "engine": "duckdb",
      "operator_tree": {
        "kind": "TOP_N",
        "take": 3,
        "order": ["sales_amount DESC", "region ASC"],
        "input": {
          "kind": "AGGREGATE",
          "group_by": ["region_id", "area"],
          "outputs": [{ "name": "sales_amount", "aggregate": "SUM", "value": "customer_sales" }],
          "input": {
            "kind": "JOIN",
            "relation": "relation.order_customer",
            "left": { "kind": "INPUT", "exchange": "x_sales" },
            "right": { "kind": "INPUT", "exchange": "x_region_map" }
          }
        }
      },
      "depends_on": ["x_sales", "x_region_map"],
      "realizes": [{ "logical_node": "top_regions", "physical_result": "result_set" }]
    }
  ]
}
```

若 relation 基数未知、指标不可分解或存在时态关系，则退回：

```text
CSV 取 customer_id+amount
SQL 源内 JOIN customer+region 并取映射
DuckDB JOIN 明细 → 聚合 → 全局 Top 3
```

若本体明确声明 `fact_order.region_id` 直接关联 `dim_region.region_id`，Optimizer 可以选择更短路径；不能仅因字段同名自行替换。

---

## 8. Coordinator、结果与 Generator

### 8.1 Coordinator

职责：

- 按 PEP `depends_on/wave` 分波执行；
- 波内并行，遵守 Source Instance 并发限制；
- 执行 Exchange 和 Compute Fragment；
- 重试可恢复的源连接失败；
- 上游失败时跳过依赖节点；
- 根据 `realizes` 把物理结果注册为逻辑 SQG 结果；
- 为 ASK/ACT 组装结构化输入；
- 增量写运行状态和血缘。

逻辑结果注册表示例：

```jsonc
{
  "east_sales": {
    "schema": [{ "name": "value", "type": "decimal", "unit": "CNY" }],
    "rows": [{ "value": 12000000 }],
    "physical_origin": "p_region_metrics.east_sales"
  }
}
```

因此 ASK 仍依赖 `east_sales` 等 SQG id，而不需要感知它们实际来自同一物理查询。

### 8.2 NodeResult 与血缘

结果不再依赖通用 `label/value` 猜测语义：

```jsonc
{
  "logical_node": "top_regions",
  "schema": [
    { "name": "region", "type": "text", "role": "dimension" },
    { "name": "sales_amount", "type": "decimal", "unit": "CNY", "role": "measure" }
  ],
  "grain": ["region"],
  "rows": [],
  "lineage": [
    {
      "field": "sales_amount",
      "concepts": ["metric.sales_amount"],
      "sources": ["sales_csv:fact_order.csv"],
      "physical_fragments": ["p_sales_by_customer", "p_top_regions"]
    }
  ]
}
```

Lineage 同时记录：逻辑节点、物理 Fragment、源对象、查询/参数摘要、关系路径、优化改写和精确/近似标志。

### 8.3 Generator

- 结构化数据结果优先确定性渲染 Markdown 表格；
- ASK 输出要求 Markdown；
- Generator 不修改任何确定性数值；
- Web 结果保留 URL、标题、摘要和完整内容血缘；
- 前端使用 Markdown parser + DOM sanitizer 渲染。

### 8.4 ACT

Action Resolver 负责：

- 业务对象解析和唯一性校验；
- 参数校验；
- 幂等键；
- 权限与审计；
- 副作用执行和回执。

Harness 重试时不得重复产生副作用；同一 run/逻辑节点/有效载荷使用稳定幂等键。

---

## 9. 权限、缓存、连接与可靠性

### 9.1 权限

- `as_user` 从认证 token 获取，不信任请求体；
- `user_scoped` Resolver 以用户身份执行 RLS/数据权限；
- 不同用户或安全域的数据扫描、缓存和中间结果禁止复用；
- Optimizer 只能在策略允许时下推敏感字段；
- PEP 和日志对参数、凭据、个人信息脱敏。

### 9.2 缓存

- Initializer 路由缓存：规范化问题 + 候选本体集合；一小时滑动过期；
- Compiler SQG 缓存：问题 + 本体 id + 本体内容指纹 + 可用能力；只缓存成功计划；一小时滑动过期；
- PEP 缓存可后续增加，但键必须包含 Source capabilities/version、用户安全域、统计版本和本体指纹；
- 数据结果默认不跨用户缓存。

### 9.3 数据库连接

SQL Resolver 使用线程安全、自愈连接池：

- 连接复用；
- 空闲/最大寿命回收；
- 借出前健康检查；
- 可识别连接错误时丢弃并重试一次；
- 进程关闭时统一释放。

### 9.4 Compute

跨源计算默认使用 DuckDB。设计上支持：

- Arrow/批式 Exchange；
- 内存阈值和磁盘溢写；
- Fragment 级临时表生命周期；
- 取消、超时和资源上限；
- 不把大规模全量拉取作为无提示默认计划。

---

## 10. 存储、API 与可观测性

### 10.1 核心存储

- `nexus.ontology`：一份本体一行，graph JSON；
- `nexus.resolvers`：Source/Agent/Action 注册实例；
- `nexus.llms`：Initializer/Compiler 使用的规划模型；
- `nexus.app_credential` + Key Vault：非敏感元数据与密文分离；
- `nexus.run`、`nexus.run_stage`、`nexus.run_node`：运行记录。
- 不新增 artifact 表：Initializer/Compiler/Optimizer 的中间产物写入已有 `nexus.run_stage.logs`；Optimizer 至少保存 semantic binding、bound logical plan、PEP 和 optimization trace。

### 10.2 五阶段运行记录

`run_stage.stage`：

```text
initializer → compiler → optimizer → coordinator → generator
```

- Initializer output：选中的本体和上下文摘要；
- Compiler output：typed SQG；
- Optimizer output：最终 PEP；三步完整产物和 trace 存该 optimizer stage 的 `logs.artifacts`；
- Coordinator output：逻辑结果注册表摘要；
- Generator output：答案和 lineage。

`run_node` 记录 PEP 执行节点状态；结构来自 optimizer stage 的 PEP JSON，状态按 `node_id` 覆盖。融合后的物理节点可通过 `realizes` 关联多个 SQG 节点。

### 10.3 LLM 调用与 Token 日志

不新增数据库表或字段，统一复用现有 JSON 日志列：

- Initializer、Compiler：`nexus.run_stage.logs.llm_calls[]`；
- Coordinator 内 ASK：同时写入 `nexus.run_node.logs.llm_calls[]`，并汇总到 coordinator 的 `run_stage.logs.llm_calls[]`；
- Optimizer、Generator 当前不调用 LLM，其 Stage Token 为 0。

每次调用保存：

```jsonc
{
  "purpose": "ontology_routing | sqg_compilation | ask_generation",
  "metadata": { "attempt": 1 },
  "provider": "azure_openai",
  "llm_name": "default",
  "model": "实际响应模型",
  "deployment": "Azure deployment",
  "request_id": "...",
  "response_id": "...",
  "finish_reason": "stop",
  "started_at": "...",
  "duration_ms": 1234,
  "input": { "messages": [], "response_format": null },
  "output": { "content": "...", "parsed": {} },
  "usage": {
    "input_tokens": 1200,
    "cached_input_tokens": 1024,
    "uncached_input_tokens": 176,
    "cache_write_input_tokens": 0,
    "output_tokens": 85,
    "reasoning_tokens": 40,
    "total_tokens": 1285,
    "input_token_details": {},
    "output_token_details": {}
  }
}
```

其中 `cached_input_tokens` 直接取 LLM Provider 返回的 Prompt Cache usage（Azure/OpenAI 的 `prompt_tokens_details.cached_tokens`），不是 Initializer/SQG/PEP 应用缓存。Provider 未返回某字段时保留 `null`，不得自行估算。

日志不得包含 endpoint、API key、Authorization 或其它凭据；输入输出内容遵循 run 访问控制。

### 10.4 Optimizer Artifact 存储（复用 run_stage.logs）

当前实现不改变数据库表结构。四类 artifact 使用统一外壳后，按 key 写入 optimizer 行的 `logs.artifacts`：

| 字段 | 含义 |
|---|---|
| `artifact_id` | 稳定唯一 id |
| `run_id` | 所属运行 |
| `stage` | 产出阶段，当前主要为 optimizer |
| `artifact_type` | `semantic_binding / bound_logical_plan / physical_execution_plan / optimization_trace` |
| `sequence` | 同类型多版本/中间快照顺序；最终产物通常为 0 或标记 `is_final` |
| `state` | `complete / partial / failed` |
| `schema_version` | artifact JSON schema 版本 |
| `producer_version` | 生成它的引擎版本 |
| `input_artifact_id` | 上一步 artifact，形成可遍历链 |
| `input_hash` | 输入快照摘要，用于复现和缓存诊断 |
| `summary` | 列表页使用的有界摘要 |
| `content` | 完整 JSON；大内容允许压缩/对象存储，但 API 行为不变 |
| `diagnostics` | 校验错误、警告、规则拒绝原因 |
| `created_at` | 生成时间 |

写入要求：

- 每一步完成后立即落库，不等整个 Optimizer 结束；
- 异常处理先写 partial/failed artifact，再结束 optimizer stage；
- artifact 不可在运行后原地修改；重试或重规划产生新 sequence；
- 默认保留与 run 相同周期；删除 run 时级联删除或归档；
- BFF 已返回 `run_stage.logs`；UI 在 Optimizer 标签内按 artifact key 切换浏览。若未来单次计划体积达到需要独立分页/对象存储的规模，再单独评审数据库结构，不在本次实现中隐式新增表。

Optimizer stage output 示例：

```jsonc
{
  "artifacts": {
    "semantic_binding": { "artifact_type": "semantic_binding", "tasks": [] },
    "bound_logical_plan": { "artifact_type": "bound_logical_plan", "nodes": [] },
    "physical_execution_plan": { "artifact_type": "physical_execution_plan", "nodes": [] },
    "optimization_trace": { "artifact_type": "optimization_trace", "rules": [] }
  }
}
```

### 10.5 API

主要接口：

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/v1/ask` | 启动一次运行，返回 run id |
| GET | `/api/v1/runs/{run_id}` | 读取阶段、节点、结果和血缘 |
| POST | `/api/v1/compile` | 编译预览 typed SQG |
| GET/POST | `/api/v1/ontologies` | 本体读写/发布 |
| POST | `/api/v1/ontologies/import-preview` | 探测实体、属性、关系候选 |
| GET/POST | `/api/v1/resolvers` | Source/Agent/Action 管理 |
| GET/POST | `/api/v1/credentials` | 凭据管理，密文进 Key Vault |

统一响应信封保持 `{state, message, data}`。

---

## 11. 完整示例：销售报告并发邮件

问题：

> 查询华东和华南2024年的销售额和毛利，再列出销量前三的产品，把报告邮件方式发颜斌。

### 11.1 SQG

该图保持用户友好的七个步骤：

```text
华东2024年销售额 ─┐
华东2024年毛利   ─┤
华南2024年销售额 ─┼→ 生成销售报告结论 → 发送报告邮件给颜斌
华南2024年毛利   ─┤
2024年销量前三产品 ┘
```

```jsonc
{
  "version": 3,
  "question": "查询华东和华南2024年的销售额和毛利，再列出销量前三的产品，把报告邮件方式发颜斌",
  "nodes": [
    {
      "id": "east_sales",
      "operator": "AGGREGATE",
      "name": "华东2024年销售额",
      "spec": {
        "subject": { "entity": "entity.fact_order" },
        "scope": {
          "kind": "and",
          "operands": [
            { "kind": "time_range", "attribute": "attribute.fact_order.order_date", "start": "2024-01-01", "end_exclusive": "2025-01-01", "timezone": "Asia/Shanghai" },
            { "kind": "comparison", "left": { "kind": "attribute", "concept": "attribute.dim_region.area" }, "operator": "EQ", "right": { "kind": "literal", "value": "华东", "data_type": "text" } }
          ]
        },
        "dimensions": [],
        "measure": { "metric": "metric.sales_amount", "output": "value" },
        "result": { "kind": "SCALAR", "name": "华东2024年销售额", "unit": "CNY" }
      },
      "depends_on": []
    },
    {
      "id": "east_profit",
      "operator": "AGGREGATE",
      "name": "华东2024年毛利",
      "spec": {
        "subject": { "entity": "entity.fact_order" },
        "scope": {
          "kind": "and",
          "operands": [
            { "kind": "time_range", "attribute": "attribute.fact_order.order_date", "start": "2024-01-01", "end_exclusive": "2025-01-01", "timezone": "Asia/Shanghai" },
            { "kind": "comparison", "left": { "kind": "attribute", "concept": "attribute.dim_region.area" }, "operator": "EQ", "right": { "kind": "literal", "value": "华东", "data_type": "text" } }
          ]
        },
        "dimensions": [],
        "measure": { "metric": "metric.gross_profit", "output": "value" },
        "result": { "kind": "SCALAR", "name": "华东2024年毛利", "unit": "CNY" }
      },
      "depends_on": []
    },
    {
      "id": "south_sales",
      "operator": "AGGREGATE",
      "name": "华南2024年销售额",
      "spec": {
        "subject": { "entity": "entity.fact_order" },
        "scope": {
          "kind": "and",
          "operands": [
            { "kind": "time_range", "attribute": "attribute.fact_order.order_date", "start": "2024-01-01", "end_exclusive": "2025-01-01", "timezone": "Asia/Shanghai" },
            { "kind": "comparison", "left": { "kind": "attribute", "concept": "attribute.dim_region.area" }, "operator": "EQ", "right": { "kind": "literal", "value": "华南", "data_type": "text" } }
          ]
        },
        "dimensions": [],
        "measure": { "metric": "metric.sales_amount", "output": "value" },
        "result": { "kind": "SCALAR", "name": "华南2024年销售额", "unit": "CNY" }
      },
      "depends_on": []
    },
    {
      "id": "south_profit",
      "operator": "AGGREGATE",
      "name": "华南2024年毛利",
      "spec": {
        "subject": { "entity": "entity.fact_order" },
        "scope": {
          "kind": "and",
          "operands": [
            { "kind": "time_range", "attribute": "attribute.fact_order.order_date", "start": "2024-01-01", "end_exclusive": "2025-01-01", "timezone": "Asia/Shanghai" },
            { "kind": "comparison", "left": { "kind": "attribute", "concept": "attribute.dim_region.area" }, "operator": "EQ", "right": { "kind": "literal", "value": "华南", "data_type": "text" } }
          ]
        },
        "dimensions": [],
        "measure": { "metric": "metric.gross_profit", "output": "value" },
        "result": { "kind": "SCALAR", "name": "华南2024年毛利", "unit": "CNY" }
      },
      "depends_on": []
    },
    {
      "id": "top_products",
      "operator": "AGGREGATE",
      "name": "2024年销量前三产品",
      "spec": {
        "subject": { "entity": "entity.fact_order" },
        "scope": { "kind": "time_range", "attribute": "attribute.fact_order.order_date", "start": "2024-01-01", "end_exclusive": "2025-01-01", "timezone": "Asia/Shanghai" },
        "dimensions": [
          { "kind": "attribute", "concept": "attribute.dim_product.product_name", "output": "product" }
        ],
        "measure": {
          "value": { "kind": "attribute", "concept": "attribute.fact_order.quantity" },
          "statistic": { "function": "SUM", "nulls": "IGNORE" },
          "output": "sales_quantity"
        },
        "ranking": {
          "by": "sales_quantity",
          "direction": "DESC",
          "take": 3,
          "ties": "EXCLUDE",
          "tie_breakers": [{ "field": "product", "direction": "ASC" }]
        },
        "result": { "kind": "RANKING", "name": "2024年销量前三产品", "grain": ["product"] }
      },
      "depends_on": []
    },
    {
      "id": "report",
      "operator": "ASK",
      "name": "生成销售报告结论",
      "spec": {
        "instruction": "根据输入生成简洁的2024年销售报告，保留全部数值，不重新计算或修改输入数据。",
        "format": "MARKDOWN"
      },
      "depends_on": ["east_sales", "east_profit", "south_sales", "south_profit", "top_products"],
      "inputs": {
        "east_sales": { "node": "east_sales" },
        "east_profit": { "node": "east_profit" },
        "south_sales": { "node": "south_sales" },
        "south_profit": { "node": "south_profit" },
        "top_products": { "node": "top_products" }
      }
    },
    {
      "id": "send_email",
      "operator": "ACT",
      "name": "发送报告邮件给颜斌",
      "spec": {
        "action": "EMAIL.SEND",
        "recipient": "颜斌"
      },
      "depends_on": ["report"],
      "inputs": { "report": { "node": "report", "output": "value", "row": 0 } }
    }
  ],
  "outputs": ["send_email"]
}
```

### 11.2 典型 PEP

Optimizer 可以把前四个指标融合成一次条件聚合；Top 产品使用另一 grain，典型计划单独查询；ASK/ACT 保持一个节点：

```jsonc
{
  "version": 3,
  "nodes": [
    {
      "id": "p_region_metrics",
      "kind": "SOURCE_FRAGMENT",
      "source_instance": "sales_source",
      "operator_tree": {
        "kind": "AGGREGATE",
        "input": {
          "kind": "FILTER",
          "predicate": "2024公共时间范围 AND region IN (华东,华南)",
          "input": { "kind": "SCAN", "entity": "entity.fact_order" }
        },
        "outputs": [
          { "name": "east_sales", "aggregate": "SUM", "value": "amount", "filter": "region=华东" },
          { "name": "east_profit", "aggregate": "SUM", "value": "amount-cost", "filter": "region=华东" },
          { "name": "south_sales", "aggregate": "SUM", "value": "amount", "filter": "region=华南" },
          { "name": "south_profit", "aggregate": "SUM", "value": "amount-cost", "filter": "region=华南" }
        ]
      },
      "depends_on": [],
      "wave": 1,
      "realizes": [
        { "logical_node": "east_sales", "logical_field": "value", "physical_field": "east_sales" },
        { "logical_node": "east_profit", "logical_field": "value", "physical_field": "east_profit" },
        { "logical_node": "south_sales", "logical_field": "value", "physical_field": "south_sales" },
        { "logical_node": "south_profit", "logical_field": "value", "physical_field": "south_profit" }
      ]
    },
    {
      "id": "p_top_products",
      "kind": "SOURCE_FRAGMENT",
      "source_instance": "sales_source",
      "operator_tree": {
        "kind": "TOP_N",
        "take": 3,
        "order": ["sales_quantity DESC", "product ASC"],
        "input": {
          "kind": "AGGREGATE",
          "group_by": ["product"],
          "outputs": [{ "name": "sales_quantity", "aggregate": "SUM", "value": "quantity" }],
          "input": { "kind": "FILTER", "predicate": "2024时间范围", "input": { "kind": "SCAN", "entity": "entity.fact_order" } }
        }
      },
      "depends_on": [],
      "wave": 1,
      "realizes": [{ "logical_node": "top_products", "physical_result": "result_set" }]
    },
    {
      "id": "p_report",
      "kind": "ASK",
      "resolver": "report_agent",
      "depends_on": ["p_region_metrics", "p_top_products"],
      "wave": 2,
      "inputs": {
        "east_sales": "logical:east_sales",
        "east_profit": "logical:east_profit",
        "south_sales": "logical:south_sales",
        "south_profit": "logical:south_profit",
        "top_products": "logical:top_products"
      },
      "realizes": [{ "logical_node": "report", "physical_result": "markdown" }]
    },
    {
      "id": "p_send_email",
      "kind": "ACT",
      "resolver": "email_action",
      "depends_on": ["p_report"],
      "wave": 3,
      "call": {
        "action": "EMAIL.SEND",
        "recipient": "颜斌",
        "content": "logical:report"
      },
      "idempotency": { "scope": "run+logical_node+payload" },
      "realizes": [{ "logical_node": "send_email", "physical_result": "receipt" }]
    }
  ]
}
```

PEP 允许进一步共享 `p_region_metrics` 和 `p_top_products` 的底层扫描，但只有成本模型判断共享物化比两条源查询更优时才采用；SQG 不发生任何变化。

---

## 12. 实施范围与验收

### 12.1 Clean-break 改造范围

后端：

- 用 discriminated typed SQG models 替换 `SQGNode.params`；
- 新增 typed Predicate/Expression/Statistic/Dimension/ResultContract；
- 新增高层 CALCULATE；删除 SQG `FILTER/JOIN/PROJECT`；
- Metric 改为 structured expression；
- Relation 增加方向性 multiplicity、optionality、integrity、temporal；
- Optimizer 新增 Bound Logical Plan 和 Fragment PEP；
- 删除旧 `QuerySpec.value_expr/label_expr/selects`、P1/P2 正则融合和 PROJECT 拆分；
- SQL Server 与 DuckDB 使用共享 typed IR、独立方言 Renderer；
- Coordinator 使用 `realizes` 注册逻辑结果；
- Generator 根据 explicit result schema 渲染。

前端：

- SQG 图只显示高层业务任务；
- PEP 图显示 Fragment/Exchange 和融合映射；
- 关系编辑器强制选择基数与可选性；
- relation edge 显示 N:1、1:N、1:1、N:M 及可选状态；
- 节点详情展示 typed spec/result contract/operator tree；
- 五阶段运行时间线。

数据：

- 设计阶段不迁移旧 SQG、PEP、QuerySpec、缓存或历史运行 JSON；
- 更新本体 graph version；现有开发本体按新 schema 重新生成或一次性转换；
- 生产数据变更必须另行评审，不在兼容层中隐式处理。

### 12.2 测试矩阵

必须覆盖：

1. 同 scope 多测度单扫描；
2. 不同 scope 公共谓词提取 + 条件聚合；
3. 不同 TopN 共享前缀后分支；
4. 月/季/年 grain 与时区；
5. median/percentile/variance；
6. CALCULATE 对齐、广播、除零、最低/最高选择；
7. many-to-one 安全预聚合；
8. one-to-many/many-to-many fan-out 防护；
9. optional relation 三种 unmatched policy；
10. 跨源 fallback、预聚合、semi-join、全局 TopN；
11. 一个物理 Fragment `realizes` 多个 SQG 节点；
12. ASK 不重算、ACT 幂等；
13. 权限域隔离、缓存失效、连接恢复；
14. SQL Server 与 DuckDB 结果等价；
15. Semantic Binding、Bound Logical Plan、PEP 三份 artifact 在成功、partial failure、缓存命中时均可保存和串联浏览；
16. optimization trace 能说明规则应用/拒绝和候选成本；
17. UI 关系必填校验和 SQG/IR/PEP 联动视图。

### 12.3 验收判据

- 用户从 SQG 图能直接复述系统的解题步骤；
- SQG JSON 中没有 Resolver、物理对象或关系代数技术节点；
- 每次 Optimizer 运行都能浏览 Semantic Binding、Bound Logical Plan、PEP 以及选择理由；
- PEP 清楚展示执行位置、Exchange、融合和 logical output bindings；
- 跨源计划不会因 JOIN fan-out 重复计算指标；
- 未知 relation 基数时 Optimizer 自动退回保守策略；
- 所有确定性数字均可从 typed plan 和 lineage 复算；
- 新增统计函数或数据源主要扩展 typed IR/Capabilities/Renderer，不需要修改 Compiler 的业务粒度原则。

### 12.4 当前验证基线

- Backend：`python -m unittest discover -s test -p "test_*.py"`，31 tests；
- Python：`python -m compileall -q app`；
- Frontend：`npm run build`（含 `vue-tsc --build`）；
- BFF：`dotnet build DataNexus.Server/DataNexus.Server.csproj -c Release`。

当前实现没有执行任何 DDL，也没有修改生产或开发数据库数据。本体 graph v3 仍存放于原 `nexus.ontology.graph` JSON 列；运行 artifacts 仍存放于原 `nexus.run_stage.logs`。

旧本体的一次性转换入口位于：**本体管理 → 打开旧本体 → 顶部黄色提示 →「转换为 graph v3」**。转换先在浏览器内生成草稿，不立即写库；用户必须逐条确认 relation 的基数/可选性/integrity，并审阅无法自动解析的 metric。只有点击“保存”后，才覆盖原 `nexus.ontology.graph` JSON；不修改数据库表结构。
