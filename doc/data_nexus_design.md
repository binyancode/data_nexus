# Data Nexus 设计文档（唯一真相源）

> 一张图 · 一个协议 · 一种查询 —— 联结一切数据、智能体与行动
>
> 本文档是 Data Nexus 的**唯一设计文档**，覆盖三部分：**第一部分平台/概念设计**（第 0–15 节）、**第二部分后端工程实现**（第 16–29 节）、**第三部分前端设计**（第 30 节）。领域模型只在第一部分定义一次，后端/前端一律引用，避免多处漂移。
>
> 配套 `doc/nexus_platform_ppt.html`（19 页设计稿）必须与本文一致。

---

## 目录

0. [阅读顺序与核心心智模型](#0-阅读顺序与核心心智模型)
1. [背景与目标](#1-背景与目标)
2. [总体架构蓝图](#2-总体架构蓝图)
3. [知识层：本体（Concept + Binding）](#3-知识层本体concept--binding)
4. [知识层：自动生成本体](#4-知识层自动生成本体)
5. [能力层：Resolver](#5-能力层resolver)
6. [查询语言：SQG（语义查询图）](#6-查询语言sqg语义查询图)
7. [运行引擎](#7-运行引擎)
8. [权限与治理](#8-权限与治理)
9. [分层架构](#9-分层架构)
10. [端到端示例](#10-端到端示例)
11. [落地路径 P0–P4](#11-落地路径-p0p4)
12. [复用现有代码资产](#12-复用现有代码资产)
13. [价值](#13-价值)
14. [待深挖问题](#14-待深挖问题)
15. [附录：完整 JSON 样例](#15-附录完整-json-样例)

**第二部分 · 后端工程实现**：16 目标与形态 · 17 技术选型 · 18 总体架构 · 19 本体存储(Azure SQL) · 20 API · 21 SDK · 22 配置与容器 · 23 LLM · 24 可观测性 · 25 错误处理 · 26 测试 · 27 目录结构 · 28 开发阶段 P0–P4 · 29 风险

**第三部分 · 前端设计**：30 前端设计（待补）

---

## 0. 阅读顺序与核心心智模型

Data Nexus 的知识层是一张**语义图（ER / 知识图谱）**，运行层是一条**逻辑 → 物理 → 执行**的查询管线。

### 0.1 知识层：语义图（5 种 kind）

所有本体元素长成同一个形状，靠 `kind` 区分；**物理只落在 entity 和 attribute 两层**，其余纯语义。

| kind | 是什么 | 绑物理？ | 一句话 |
|---|---|---|---|
| **entity** | 业务对象 / 图的节点 | ✅ 绑到**表** | 销售、产品、客户、区域 |
| **attribute** | 隶属于一个 entity 的属性 | ✅ 绑到**列** | 数量、单价、区域名（唯一真正落物理处）|
| **relation** | 连接两 entity 的边 | ❌ 纯语义 | `attr=attr` + 方向 + 基数(1:1/1:n/n:1) |
| **metric** | 对 attribute 的聚合表达式 | ❌ 纯语义 | `SUM(attr.sales.qty * attr.product.price)` |
| **derivation** | 数据产物的上下游血缘边 | ❌ 纯语义 | A、B → C（可向上游追溯）|

> 物理彻底沉底：**Concept 层只用 concept_id 互相引用，看不到任何物理表**；表/列只出现在 entity/attribute 的 Binding 里。

### 0.2 能力层：Resolver（统一执行接口）

数据源 / 智能体 / 动作都实现同一个 Resolver 接口。**注意：Resolver 只出现在物理执行阶段，逻辑层完全不认识它。**

### 0.3 运行层：逻辑 → 物理 → 执行 三段管线

```
用户提问
  │
① Compiler   →  逻辑 SQG DAG        （语义算子 over concept_id；无物理、无 resolver）
  │
② Optimizer →  优化后的物理执行 DAG  （= 查询优化器：选源绑 resolver、下推 vs 内存、join 融合）
  │
③ Coordinator→  执行结果            （分波并行 + 内存 JOIN + 回填 + 合并 + 裁决）
  │
④ Generator  →  答案 + 血缘
  │
⑤ Harness    →  自检这轮是否合理；不合理 → 带着问题重来（外层 loop，≤ N 轮，见 §7.5）
```

**三条铁律**：
1. **逻辑 SQG 不含 resolver、不含物理表**——只有 concept_id + 算子。
2. **join 不是用户表达的，是引擎据 relation 推导的**：同源 → 融进下推 SQL；跨源 → 保留为内存 JOIN 节点。
3. **Optimizer = 查询优化器**：把逻辑计划优化成物理计划，resolver 到这里才第一次出现。

> 贯穿全文的示例问题：**「华东上季度毛利为什么下滑、跟华南比差在哪，给份说明，并把复盘任务派给区域负责人。」**

---

## 1. 背景与目标

### 1.1 痛点

老板问「华东上季度为什么下滑？并安排复盘」，今天需要人肉：打开数据库查数 → 翻 Excel → 搜文档 → 找人归因 → 手动建复盘任务。答案散在一堆系统里，每接一个新源都要单独开发，AI Agent 又是另一套接入方式。

### 1.2 目标

用户只需一句话，系统自动完成：

1. **找源 + 跨源查齐**：自动定位能回答的数据源并联合取数。
2. **综合结论 + 标明出处**：把多源结果合并成一份答案，附血缘。
3. **顺手执行**：需要时直接触发动作（如自动派复盘任务）。

一句话目标：**把「人肉跨系统」变成「提一句话」。**

---

## 2. 总体架构蓝图

```
┌───────────────────────────────────────────────────────────────┐
│ 知识层 · 语义图（静态）                                          │
│   entity / attribute（绑物理）· relation / metric / derivation（纯语义）│
└───────────────────────────────────────────────────────────────┘
        ▲ ① Compiler 查本体，产出逻辑 SQG（无 resolver/物理）
┌───────────────────────────────────────────────────────────────┐
│ 运行引擎（动态）                                                 │
│   逻辑SQG ─②Optimizer→ 物理DAG ─③Coordinator→ 结果 ─④Generator→ 答案│
└───────────────────────────────────────────────────────────────┘
        ▼ ②③ 查 Binding 选 Resolver、执行时调用 Resolver
┌───────────────────────────────────────────────────────────────┐
│ 能力层 · Resolver（静态，只在物理阶段出现）                       │
│   数据源 Resolver   Agent Resolver   动作 Resolver               │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. 知识层：语义图本体

知识层是一张语义图：**entity 是节点、attribute 挂在节点上、relation 是边、metric 是聚合、derivation 是血缘边**。五种 `kind` 共用同一外壳，各自加专属字段。

### 3.1 公共外壳

所有 Concept 都有：

```jsonc
{
  "id": "metric.gross_margin",   // 唯一标识，命名 kind.name
  "kind": "metric",              // entity|attribute|relation|metric|derivation
  "name": "毛利",                 // 业务显示名
  "semantics": "销售收入 - 销售成本", // 业务含义（供 LLM 消歧）
  "synonyms": ["毛利额", "gross margin"],
  "policy": { "sensitivity": "internal", "row_level": true }, // 权限（治理内生）
  "provenance": { "generated_by": "auto", "confidence": 0.93, "source_ref": "...", "updated_at": "..." }
}
```

> `provenance`（字段）= 单个概念的**物理出处**元数据；别和 `derivation`（kind，数据产物血缘边）混淆。

### 3.2 entity（实体，绑表）

图的节点；唯一（和 attribute 一起）真正落物理的地方。

```jsonc
{ "id": "entity.sales", "kind": "entity", "name": "销售" }
// 物理落在它的 Binding：entity.sales → dwh.fact_sales（表）
```

### 3.3 attribute（属性，绑列，必属于一个 entity）

```jsonc
{ "id": "attr.sales.quantity", "kind": "attribute", "name": "数量",
  "entity": "entity.sales",   // ★ 必填：属于哪个 entity
  "type": "int" }
// 物理落在它的 Binding：attr.sales.quantity → fact_sales.quantity（列）
```

### 3.4 metric（指标，表达式用 concept_id，纯语义）

metric 的表达式**只引用 attribute 的 concept_id，绝不出现物理表**：

```jsonc
{ "id": "metric.total_sales", "kind": "metric", "name": "总销售额",
  "type": "decimal",
  "expr": "SUM(attr.sales.quantity * attr.product.unit_price)" }
```

- 物理由引擎派生：把每个 `attr.*` 换成其 Binding 的列，再据 relation 补 join。
- **可选** Binding：某源直接提供该指标（如 `agent.sales` 直接答「总销售额」）——这是跨源融合的挂点。

### 3.5 relation（关系边：attr=attr + 方向 + 基数，纯语义）

join 的**唯一**来源。连接两个 attribute（外键列），带**基数**和**方向**：

```jsonc
{ "id": "rel.sales_product", "kind": "relation", "name": "销售↔产品",
  "left": "attr.sales.product_id",   // 都是 attribute 的 concept_id
  "right": "attr.product.id",
  "cardinality": "n:1",              // 1:1 | 1:n | n:1（n:m 用桥 entity 拆两段）
  "direction": "sales→product",
  "join_type": "inner" }             // inner|left|right|full，默认 inner
```

> **基数至关重要**：1:n 关系若先 join 再聚合会 fan-out 重复计数，引擎据此决定「先预聚合再 join」。

### 3.6 derivation（血缘边：A、B → C，纯语义）

数据产物间的上下游 DAG，支持**向上游追溯**：

```jsonc
{ "id": "deriv.reconciliation", "kind": "derivation", "name": "对账派生",
  "target": "entity.reconciliation",                       // 下游产物 C
  "sources": ["entity.sales_actual", "entity.sales_plan"], // 上游 A、B
  "transform": "对账 = 实际 对比 计划（按区域月度）",
  "direction": "A,B → C" }
```

用户问「C 的某数为什么这样」且含追溯意图时，引擎顺 derivation 边**自动生成查 A、B 的节点**。

### 3.7 Binding（只挂 entity / attribute）

Binding 把 **entity → 表、attribute → 列**。**不含 join**（join 归 relation）。

```jsonc
{
  "id": "bind.attr.sales.quantity.dwh",
  "concept_id": "attr.sales.quantity",   // 反向外键（唯一真相；Concept.bindings 为派生视图）
  "resolver": "dwh.sql",                 // 由哪个 Resolver 执行
  "kind": "column",                      // table | column | prompt | file | endpoint
  "expr": "fact_sales.quantity",         // column: 列；entity 用 table
  "confidence": 0.95
}
```

**要点**

1. **换库/加源只改 Binding，Concept 不动。**
2. **同一 Concept 可绑多个 Binding = 跨源融合**（一个 attribute/metric 绑多个源）。
3. **Binding 不再有 `joins` 字段**——表怎么连由 relation 声明、由引擎推导。
4. 对接目标因 Resolver 而异：SQL 源绑表/列/表达式；Agent 源绑「提问模板」；文件源绑路径；API 源绑端点。

### 3.8 编译示例（「总销售额」）

概念层（纯 concept_id）：`metric.total_sales = SUM(attr.sales.quantity * attr.product.unit_price)`，跨 `entity.sales`、`entity.product` → 引擎找 `rel.sales_product`（n:1）。物理由引擎组装：

```sql
-- 同源（sales、product 同库）→ 下推一条 SQL：
SELECT SUM(fact_sales.quantity * product.unit_price)
FROM fact_sales
JOIN product ON fact_sales.product_id = product.id;   -- 来自 rel.sales_product
```

跨源时改为：各源分别取数 → 内存按 `product_id` 做 hash join（n:1 无 fan-out）→ 算表达式（详见第 6、7 节）。

---

## 4. 知识层：自动生成本体

Concept/Binding 不能全靠手工输入，否则本体永远建不起来。做法：让 Resolver **探测源、抽样数据**，自动推断候选本体。

### 4.1 四步流程

```
① 探测 describe()  → 源自报出有哪些表/字段，再抽几行样例
② 理解            → 看列名/类型/去重数/样例值/外键
③ 生成候选        → Concept + Binding + 置信度
④ 确认            → 高置信自动收；低置信标红交人工
```

### 4.2 销售示例

探测到 `fact_sales(amount, gross_margin, region_id, order_date)`、`dim_region(region_id, region_name)` 及外键，自动推断：

- Concept：`entity.sales`（表 fact_sales）+ `attr.sales.gross_margin`（列）；`entity.region`（表 dim_region）+ `attr.region.name`（列）；由外键推出 `rel.sales_region`（n:1）。
- Binding：attribute → 列、entity → 表；relation 的键由外键推出（不落 Binding）。

### 4.3 跨源合并

SQL 里的「毛利」和 Agent 懂的「毛利」，系统识别为**同一概念**，自动合并成一个 Concept、绑两个 Binding = 跨源融合。

### 4.4 半自动原则

- 机器生成**候选**，人只**确认 / 改名**剩下的。
- 交给人的情形：含义歧义、度量可加性判断、敏感数据（敏感数据只抽脱敏统计）。
- 不同源探测方式不同：
  - **SQL**：信息最全（`INFORMATION_SCHEMA` + 外键 + 抽样）。
  - **文件**：靠列名匹配猜关联。
  - **Data Agent**：黑盒，改成直接问它「你能答哪些概念」，让它**自报能力清单**。

### 4.5 接口

```python
class Resolver(ABC):
    def describe(self) -> SourceSchema: ...   # 结构探测：表/字段/外键
    def sample(self, obj: str, n: int = 20) -> list[dict]: ...  # 抽样（脱敏）
```

---

## 5. 能力层：Resolver

### 5.1 统一接口（最关键的抹平）

数据源、AI 智能体、执行动作、甚至「人」（human-in-the-loop），都长成**同一个接口**。优化器眼里没有「源」和「Agent」之分，只有一堆**报了能力清单、竞标同一段查询的 Resolver**。

```python
class Resolver(ABC):
    id: str                       # e.g. "dwh.sql", "agent.sales", "ticket.http"

    def capabilities(self) -> Capabilities: ...
    #   报能力清单：能答哪些概念、成本、时效、信任分、是否支持用户级权限

    def plan(self, node: SQGNode, binding: Binding) -> PlannedCall: ...
    #   评估 + 把节点编译成「具体调用」（SQL / 检索 / 自然语言 / HTTP）

    def resolve(self, call: PlannedCall, ctx: ExecContext) -> ResolveResult: ...
    #   干活：真正执行，返回数据 / 答案+证据 / 回执

    # 自动建本体用（见第 4 节）
    def describe(self) -> SourceSchema: ...
    def sample(self, obj: str, n: int = 20) -> list[dict]: ...
```

三方法一句话：**capabilities() 报能力、plan() 评估+编译、resolve() 干活。**

- **数据 Resolver**：`resolve()` = 生成查询取数。
- **Agent Resolver**：`resolve()` = 用自然语言问它，返回答案 + 证据。
- **动作 Resolver**：`resolve()` = 执行副作用（派任务），返回回执。
- **人工介入 Resolver（human-in-the-loop）**：`resolve()` = 向用户发起请求 → **阻塞等待** → 返回用户的输入 / 审批 / 判断。与 Agent Resolver 同构，只是被问的对象是人。

### 5.2 Resolver 源类清单

| # | 源类型 | 性质 | 交互方式 | 说明 |
|---|---|---|---|---|
| 1 | 关系库 SQL / PG | 被动 · 确定 | 查询语言取数 | 结果确定可复算 |
| 2 | 向量库 / 知识库 | 被动 · 近似 | RAG 检索 | topk 召回，近似 |
| 3 | **Fabric IQ** ★ | 主动 · 黑盒 | 自然语言 `ask()` | 数据 / 语义本体智能体（Fabric）|
| 4 | **Foundry IQ** ★ | 主动 · 黑盒 | `ask()` | 知识接地 · RAG（Azure Foundry）|
| 5 | **Web IQ** ★ | 主动 · 黑盒 | `ask()` | Web + 自定义应用知识 |
| 6 | **Work IQ** ★ | 主动 · 黑盒 | `ask()` | M365 工作上下文（邮件/文档/会议）|
| 7 | REST / SaaS API | 被动 · 外部 | HTTP | 外部系统 |
| 8 | **动作：写回/审批/触发** ★ | 主动 · 有状态 | 副作用调用 | 分析即行动 |
| 9 | **人工介入 Human** ★ | 主动 · 阻塞 | 请人操作 → 等待 | 审批 / 补充信息 / 人工判断（human-in-the-loop）|

- **被动**：你用查询语言去取数、结果确定；**主动**：你把需求交给它、它自己去办。
- **★ 主动源是差异化**：四个 **Microsoft IQ**（Fabric / Foundry / Web / Work IQ，Ignite 2025 发布的企业智能层）、**写回动作**、**人工介入** —— 把智能体、动作、甚至「等人操作/审批」都纳入同一套 Resolver 接口。

### 5.3 能力清单（Capabilities）Schema

```jsonc
{
  "resolver": "dwh.sql",
  "concepts": ["metric.gross_margin", "metric.sales_amount", "dim.region"],
  "operators": ["SELECT", "FILTER", "AGGREGATE"], // 支持的源执行算子（JOIN 是引擎内存算子，不由源声明）
  "cost": 0.2,           // 相对成本 0~1
  "latency_ms": 300,     // 典型时延
  "trust": 0.98,         // 信任分（裁决权重）
  "user_scoped": true,   // ★ 是否支持用户级权限控制（行级安全/数据权限）
  "freshness": "realtime"
}
```

`user_scoped` 是第 8 节权限透传的开关。

### 5.4 竞标 / 路由

同一个 SQG 节点，可能有多个 Resolver 的能力清单覆盖它。优化器按 **信任 / 成本 / 时效** 加权打分，选中一个（或多个做交叉验证）。

```
score(resolver, node) = w_trust * trust
                      - w_cost  * cost
                      - w_lat   * norm(latency)
                      + w_cover * concept_coverage
```

---

## 6. 查询语言：SQG（语义查询图，逻辑）

SQG = **Semantic Query Graph** = 语义查询图。它是 **Compiler 产出的逻辑执行 DAG**：节点是算子（over concept_id）、边是依赖。

> **铁律：逻辑 SQG 不含 resolver、不含物理表**——只有 concept_id + 算子。选源、下推、join 融合等是 Optimizer 把它优化成**物理 DAG** 时的事（见第 7 节）。

### 6.1 算子（按执行位置分两类）

| 类别 | 算子 | 作用 |
|---|---|---|
| **源执行（下推给 Resolver）** | `SELECT` | 取属性 / 文档 |
| | `FILTER` | 约束（只看华东） |
| | `AGGREGATE` | 指标计算（对毛利求和） |
| | `ASK` ★ | 交给 Agent 回答（归因） |
| | `ACT` ★ | 执行动作 / 写回（建工单） |
| **引擎内存执行** | `JOIN` | 对**上游节点的结果**按 relation 的键做 hash join |

**关于 JOIN（关键）**：
- JOIN **不是用户表达的**，是引擎据 `relation` **自动推导**的；旧的 `TRAVERSE`（沿关系跳）说法废弃。
- **同源**：JOIN 被 Optimizer **融进下推 SQL**，不出现独立内存 JOIN 节点。
- **跨源**：保留为内存 JOIN 节点（其上的 AGGREGATE 也变内存执行）。

**核心结论**：问答（ASK）、写回（ACT）与取数/计算**同级**，所以「分析」和「行动」用同一套引擎。

### 6.2 SQGNode Schema（注意：无 resolver）

```jsonc
{
  "id": "n3",
  "op": "ASK",                       // SELECT|FILTER|AGGREGATE|JOIN|ASK|ACT
  "concept": "metric.total_sales",   // 该节点关心的 concept_id（ASK/ACT 可空）
  "filter": { "attr.region.name": "华东", "period": "2024Q1" }, // filter 也用 concept_id
  "groupBy": "attr.time.month",
  "query": "华东 毛利 下滑",          // SELECT 检索词
  "prompt": "毛利={n1} 趋势={n2}，解释下滑原因", // ASK 问法，{n} 是占位符
  "action": "create_ticket",         // ACT 动作
  "desc": "复盘：{n3}",              // ACT 动作描述（可回填 {n}）
  "deps": ["n1", "n2"]               // 依赖节点
}
```

> 看到了吗——**没有 `resolver` 字段**，也没有物理表名；`concept`/`filter`/`groupBy` 全是 concept_id。

### 6.3 SQG（整图）Schema

```jsonc
{
  "intent": "explain_and_act",
  "as_user": "zhangsan@beone",       // 当前用户（权限透传，见第 8 节）
  "nodes": [ /* SQGNode[] */ ]
}
```

> 占位符规则：任何 `deps` 非空的节点，其 `prompt`/`desc` 里用 `{nX}` 引用上游结果，**运行时回填**。

---

## 7. 运行引擎

一次提问：**逻辑 → 物理 → 执行** 三段（+ 生成器）：

```
提问 → ①Compiler   → 逻辑 SQG DAG（语义、无 resolver/物理）
     → ②Optimizer → 优化后的物理执行 DAG（= 查询优化器）
     → ③Coordinator→ 执行结果（分波并行 + 内存 JOIN + 回填 + 合并 + 裁决）
     → ④Generator  → 答案 + 血缘
```

### 7.1 编译器 Compiler（NL → 逻辑 SQG）

**输入**：自然语言 + 历史。**输出**：**逻辑 SQG**（DAG，over concept_id）。

职责：
1. 意图识别（`intent`）。
2. 概念消歧：把「总销售额」「华东」「上季度」映射到 concept_id。
3. 据 metric 表达式 / relation / filter 拆算子建 DAG，标注 `deps`；join 是**逻辑节点**（还没决定怎么执行）。
4. 注入 `as_user`。

**产出物只含 concept_id + 算子，不含 resolver、不含物理表。** 实现建议：LLM 受约束生成（给定 Concept 清单 + 算子 schema，输出 JSON）+ schema 校验。

### 7.2 优化器 Optimizer（逻辑 SQG → 物理 DAG）

Optimizer 不是简单「选个源」，而是把**逻辑计划优化成物理计划**——**resolver 到这里才第一次出现**。它做：

1. **选源竞标**：查每个节点 concept 的 Binding → 让候选 Resolver 按信任/成本/时效打分选中（见 5.4）。
2. **下推 vs 内存决策**：把**同源子树**（含 join）**融成一条下推 SQL**；**跨源**则保留为**内存 JOIN** 节点，并按需做 **semi-join 下推**（先取一侧的键，过滤另一侧，少搬数据）。
3. **编译成真实调用**：调 `resolver.plan(node, binding)` 生成 `call`（SQL / 检索 / 自然语言 / HTTP）；依赖别人的节点 `call` 里留 `{nX}` 占位符。
4. **权限透传**：若中标 Resolver `capabilities.user_scoped == true`，给该 plan 项打 `user_scoped: true`（见第 8 节）。

一句话：**Optimizer = 选源 + 下推/内存优化 + 编译成调用 + 权限透传。** 产出的物理 DAG（plan）是**第一个带 resolver 的东西**：

**物理执行计划 plan Schema**

```jsonc
{
  "as_user": "zhangsan@beone",
  "plan": [
    { "node": "n1", "resolver": "dwh.sql",
      "call": "SELECT SUM(gross_margin) ... WHERE region='华东' AND period='2024Q1'",
      "trust": 0.98, "user_scoped": true },
    { "node": "n2", "resolver": "dwh.sql",
      "call": "SELECT month, SUM(gross_margin) ... GROUP BY month",
      "user_scoped": true },
    { "node": "n4", "resolver": "kb.vector",
      "call": { "q": "华东 毛利 下滑 政策 原材料", "topk": 3 } },
    { "node": "n3", "resolver": "agent.sales",
      "call": { "ask": "毛利={n1} 趋势={n2}，请解释下滑原因并给证据" },
      "user_scoped": true },
    { "node": "n5", "resolver": "ticket.http",
      "call": { "POST": "/tickets", "body": { "assignee": "张三", "desc": "{n3}" } },
      "user_scoped": true }
  ]
}
```

一句话：**优化器 = 选源 + 把每个节点编译成真实调用 + 标注谁需要用户身份。**

### 7.3 协调器 Coordinator（分波并行 + 回填 + 合并 + 裁决）

真正跑完这张 DAG。按依赖**分波**，能并行的并行：

```
第 1 波（n1/n2/n4 无依赖 → 同时发出）
  n1 数仓 → 毛利 = 1200万（环比 -15%）
  n2 数仓 → 4月480 → 5月420 → 6月300
  n4 知识库 → 命中《价格政策》《涨价通报》
        ↓
第 2 波（n3，依赖 n1/n2）
  把 n1/n2 结果回填进 prompt → 调销售 Agent
  → 主因 = 大客户Q1减采30% + 原材料涨价（附引用证据）
        ↓
第 3 波（n5，依赖 n3）
  把 n3 说明回填进任务内容 → 调工单系统
  → 工单 #4521 已创建，派给张三（回执）
        ↓
合并 + 裁决
  合并：n1/n2/n3/n4 按主题（华东·毛利·上季度）拼成一份，n5 回执附上
  裁决：若某源毛利与 n1（数仓·信任0.98）冲突 → 以数仓为准，
        败者数字丢弃、文字保留；裁决记入血缘
```

**执行算法（伪代码）**

```python
def coordinate(plan, ctx):
    results = {}
    for wave in topo_waves(plan):          # 拓扑分波
        calls = [backfill(item, results) for item in wave]  # 用已完成结果回填占位符
        wave_results = parallel_map(lambda c: run_call(c, ctx), calls)  # 并行执行
        results.update(wave_results)
    merged = merge_by_concept(results)      # 按概念主键对齐合并
    verdict = arbitrate(merged)             # 冲突裁决（信任×时效×精度）
    return merged, verdict

def run_call(item, ctx):
    if item.user_scoped:
        ctx = ctx.with_user(item.as_user)   # ★ 透传当前用户
    return resolver_of(item).resolve(item.call, ctx)
```

**裁决规则**：数字类冲突按 `信任 × 时效 × 精度` 加权，取胜者数字；败者数字丢弃、文字（解释/证据）保留；整个裁决过程写入血缘。

**结果 result Schema**

```jsonc
{
  "n1": { "毛利": 12000000, "环比": -0.15, "source": "数仓", "trust": 0.98 },
  "n2": { "series": [480, 420, 300], "unit": "万" },
  "n4": { "docs": ["价格政策", "涨价通报"] },
  "n3": { "answer": "主因:大客户减采30%+原材料涨价",
          "evidence": ["n4#1"], "trust": 0.82 },
  "n5": { "ticket": "#4521", "assignee": "张三", "status": "created" },
  "verdict": { "毛利": "以 n1 为准(trust 0.98)", "loser": "某源 1180万 → 丢弃数字" }
}
```

一句话：**协调器 = 按 DAG 分波并行 + 上游结果运行时回填 + 结果合并 + 数字冲突按信任分裁决。**

### 7.4 生成器 Generator（答案 + 血缘）

**输入**：合并结果 + verdict。**输出**：最终答案（可流式）+ 血缘。

职责：
1. 用合并数据写出自然语言答案（可套用 `dbo.prompt_templates` 模板）。
2. 附血缘：每个数字/结论来自哪个节点、哪个 Resolver、信任分、裁决记录。
3. 附动作回执（如 n5 工单）。

### 7.5 评估回路 Harness（外层自我纠错，可选但推荐）

四段引擎跑完**不直接交付**：外面再套一层 **Harness**，对整轮执行打分——不合理就带着问题重跑一轮。这是 evaluator / critic 型的**外层 loop**。

**评估三件事**（Harness 检查一轮 DAG 执行是否合理）：
1. **是否报错 / 超时**：任一节点 `resolve()` 失败、超时、返回错误码。
2. **各节点输出是否合理**：空结果、越界值、自相矛盾、证据缺失、schema 不符。
3. **最终答案 / 动作是否靠谱**：答非所问、与问题不相关、动作有风险、缺少必要证据。

**分支**：
- **合理 → 交付**（答案 + 动作 + 血缘）。
- **不合理 → 重来一轮**：把「不合理点」+ **用户原问题** 拼成**新提示词**，回到 Compiler 重新编译执行（第 k → k+1 轮）。新提示词示例：`「上一轮 n6 归因缺证据、华南数字异常，请重查并补证据」+ 原问题`。

**收敛保护**：
- 外层循环有**最大轮数上限 N**（例：3 轮），防止空转 / 死循环。
- 到顶仍不合理 → 交付「尽力的结果 + 说明局限」，或**转人工介入 Resolver**（§5.2 第 9 行，human-in-the-loop）兜底。

```
用户问题(第k轮) → [Compiler→Optimizer→Coordinator→Generator] → 结果
       ↑                                                          │
       │                                                     Harness 评估
       │                                                          │
       └── 不合理：不合理点 + 原问题 → 新提示词(第k+1轮) ←──── 合理? ──否
                                                                  │是 → 交付
                                （整体 ≤ N 轮）
```

一句话：**Harness = 跑完再自检，不对就带着问题重想一遍，最多 N 轮，像人复核一样。**

---

## 8. 权限与治理

### 8.1 用户级权限透传（本平台重点）

有些 Resolver 自己带**用户级权限控制**（行级安全 / 数据权限）。设计原则：**权限在数据源头强制，不在应用层手工拼 where。**

流程：

1. Resolver 在 `capabilities()` 里声明 `user_scoped: true`。
2. 编译器在 SQG 顶部注入 `as_user`（当前登录用户）。
3. 优化器给中标的 user_scoped 节点打 `user_scoped: true`。
4. 协调器执行该节点时，把 `as_user` 通过 `ExecContext` 传给 Resolver。
5. Resolver 按用户身份自行过滤：
   - `dwh.sql`：行级安全（RLS）按用户过滤。
   - `agent.sales`：以该用户权限运行。
   - `ticket.http`：以其身份建单。
   - `kb.vector`（公共文档）：**不带** user_scoped，无需用户身份。

```python
@dataclass
class ExecContext:
    user: str | None          # 当前用户（user_scoped 时非空）
    trace_id: str
    cancellation_token: Any

    def with_user(self, user: str) -> "ExecContext": ...
```

好处：既安全（源头强制，不会漏），又省心（应用层不用为每个源手写权限 SQL）。

### 8.2 治理内生

权限（`policy`）和血缘（`provenance`）随每个 Concept 一起挂在本体上（见 3.1），横跨所有层，不是单独一层。可追溯是默认能力。

---

## 9. 分层架构

五层，每层只做一件事，只依赖下一层接口；治理作为竖切面贯穿全层。

| 层 | 名称 | 职责 | 对应组件 |
|---|---|---|---|
| L5 | 体验层 | 对话 · 画布 · 渲染 | 前端 Copilot UI / Renderer |
| L4 | 意图层 | 把请求翻成查询指令 | **Compiler** |
| L3 | 认知层（核心） | 调度 · 协调 · 生成 | **Optimizer / Coordinator / Generator** |
| L2 | 语义层 | 本体 + 各源能力清单 | **Concept / Binding / Capabilities** |
| L1 | 接入层 | 数据 / Agent / 动作 | **Resolver** |
| 竖切面 | 治理内生 | 权限 / 血缘 / 成本 | `policy` / `provenance` |

研发重心：**L3 认知层**。

---

## 10. 端到端示例

**问题**：「华东上季度毛利为什么下滑、跟华南比差在哪，给份说明，并把复盘任务派给区域负责人。」

| 阶段 | 产物 |
|---|---|
| ① Compiler | 逻辑 SQG（7 节点）：**n1 FILTER**(期间=上季度) / n2 华东毛利 / n3 华南毛利 / n4 趋势 / n5 佐证 / **n6 归因 ASK**(依赖 n2·n3·n4·n5) / **n7 派单 ACT**(依赖 n6) |
| ② Optimizer | plan：**n1·n2·n3·n4 同源 → 融成一条 dwh.sql 一次下推**（FILTER 期间折进 WHERE）、n5→kb.vector、n6→agent.sales、n7→ticket.http；依赖别人的留 {n} 占位符；标注 user_scoped |
| ③ Coordinator | 分波并行（1 条 SQL + n5 检索 → n6 回填调 Agent → n7 回填派单）+ 合并 + 裁决 |
| ④ Generator | 华东↓ vs 华南↑ 对比结论 + 趋势 + 归因 + 血缘 + 派任回执 |
| ⑤ Harness | 自检这轮是否合理；不合理 → 带着问题重来（≤ N 轮，见 §7.5） |

中标 Resolver（带信任分）：数仓 0.98、销售 Agent 0.82、知识库 0.75、动作（回执）。

**重点**：全程没有任何「针对某个源」的特殊分支，全是「算子 + Resolver 竞标 + 合并」。

（三段真实 JSON 见[第 15 节附录](#15-附录完整-json-样例)。）

---

## 11. 落地路径 P0–P4

分五步建，从简单到完整。先做最小的能用版本，再一步步加东西；每做完一步，都能单独演示一个用户用得上的功能。

| 阶段 | 一句话目标 | 这一步做什么 | 做完能演示 |
|---|---|---|---|
| **P0** | 先跑通一条路 | 本体 + Resolver 接口 + SQG 编译器，接一个 SQL 库 | 用一句话问一个数据库，拿到答案 + 血缘 |
| **P1** | 多个库一起答 | 再接一个向量 / 知识库，加合并与裁决 | 一个问题同时查多个库，答案对不上时自动裁决 |
| **P2** ★ | AI 也能当一个源 | 加 ASK 算子，接一个 Fabric IQ（Microsoft IQ） | 碰到「为什么」直接问分析 AI，它的回答照样接进来 |
| **P3** | 查完能直接动手 | 加 ACT 算子 + 动作 Resolver | 不只给答案，还能建工单、发通知、写回系统 |
| **P4** | 接新库少配置 | Resolver 探测新源，自动补本体映射 | 接新库时自动读表结构、补业务名词对应，少配置 |

原则：

- 每做完一步，都要能单独演示一个用得上的功能。
- **P0 就把三大接口（Concept / Resolver / SQG）定死**，之后只加实现、不改范式。

风险点：本体自动生成准确率、Agent 返回证据的结构化、跨源主键对齐。

---

## 12. 复用现有代码资产

本平台是当前 PowerBI Copilot 语义引擎的**超集**，大量资产可直接迁移：

| 现有资产（`backend/app/services/semantic_engine/`） | 迁移为 |
|---|---|
| `Orchestrator`（`orchestrator.py`） | **Optimizer 优化器** 的雏形（状态机 → DAG 调度） |
| `ToolProvider`（`provider.py`） | **Resolver** 接口（`get_tools`→`capabilities`，`execute`→`resolve`） |
| `ToolManifest` | **Capabilities** 能力清单 |
| `FrontChannelConnection`（`front_channel.py`） | 前端交互 / 流式输出（Generator 用） |
| Renderer 注册表（`src/components/copilot/renderers/`） | L5 体验层渲染 |
| `credential.py`（凭据系统） | Resolver 连接凭据 |
| `dbo.api_definitions` / `api_permissions` | 治理内生的权限底座 |
| `dbo.prompt_templates`（Jinja2） | Generator 答案模板 |
| `dbo.copilot_runs` / `copilot_run_steps` | 血缘 / 执行审计 |

映射要点：
- `ToolProvider.execute(tool_name, hints, history, session)` → `Resolver.resolve(call, ctx)`。
- `Orchestrator.next_action()`（线性状态机） → `Optimizer` 产出 plan + `Coordinator` 拓扑分波（升级为 DAG）。

---

## 13. 价值

### 13.1 五个价值

1. **加源零范式**：接新系统 = 写一个 Resolver，引擎不改。
2. **一种查询**：查数据 / 血缘 / 权限 / 问 Agent 全是同一种查询。
3. **分析即行动**：ASK 与 ACT 同级，洞察到执行同一引擎打通。
4. **治理内生**：权限和血缘随概念一起管，可追溯是默认。
5. **Agent 无缝**：多个智能体协同是 Resolver 竞标机制的自然结果。

判据：加任何新东西，本质只是「本体里加一个 Concept，或加一个 Resolver」，范式不变。

---

## 14. 待深挖问题

1. **本体存储选型**：属性图 vs RDF vs 关系库模拟；P0 用 SQL 模拟起步。
2. **SQG 算子代数 + 编译器**：把六个算子定义完整，设计 NL→SQG 的受约束生成。
3. **Resolver 竞标 / 路由算法**：「成本-信任-时效」加权模型，冲突裁决细则。
4. **自动建本体准确率**：结构探测 + 抽样 + LLM 推断的候选质量，减少人工确认。

---

## 15. 附录：完整 JSON 样例

以示例问题「华东上季度毛利为什么下滑、跟华南比差在哪，给说明并派复盘任务」为例，三段一一对应。

### ① 查询指令 SQG（编译器输出，`{n}` 是占位符）

```json
{
  "intent": "explain_and_act",
  "as_user": "zhangsan@beone",
  "nodes": [
    { "id": "n1", "op": "FILTER",
      "concept": "dim.period", "value": "上季度(2024Q1)" },
    { "id": "n2", "op": "AGGREGATE", "deps": ["n1"],
      "concept": "metric.gross_margin", "filter": { "地区": "华东" } },
    { "id": "n3", "op": "AGGREGATE", "deps": ["n1"],
      "concept": "metric.gross_margin", "filter": { "地区": "华南" } },
    { "id": "n4", "op": "AGGREGATE", "deps": ["n1"],
      "concept": "metric.gross_margin", "filter": { "地区": "华东" }, "groupBy": "月" },
    { "id": "n5", "op": "SELECT",
      "concept": "doc.evidence", "query": "华东 毛利 下滑" },
    { "id": "n6", "op": "ASK", "deps": ["n2", "n3", "n4", "n5"],
      "prompt": "毛利={n2} 华南={n3} 趋势={n4} 证据={n5}，解释华东为何下滑" },
    { "id": "n7", "op": "ACT", "deps": ["n6"],
      "action": "create_ticket", "desc": "{n6}" }
  ]
}
```

### ② 优化器 plan（翻译成 Resolver 调用 + 透传用户）

```json
{
  "as_user": "zhangsan@beone",
  "plan": [
    { "node": "n1+n2+n3+n4", "resolver": "dwh.sql", "fused": true,
      "call": "SELECT region, month, SUM(gross_margin) FROM fact_sales WHERE region IN('华东','华南') AND period='2024Q1' GROUP BY region, month",
      "trust": 0.98, "user_scoped": true },
    { "node": "n5", "resolver": "kb.vector",
      "call": { "q": "华东 毛利 下滑", "topk": 3 } },
    { "node": "n6", "resolver": "agent.sales",
      "call": { "ask": "毛利={n2} 华南={n3} 趋势={n4} 证据={n5}，解释下滑" },
      "user_scoped": true },
    { "node": "n7", "resolver": "ticket.http",
      "call": { "POST": "/tickets", "body": { "desc": "{n6}" } },
      "user_scoped": true }
  ]
}
```

> **FILTER(n1) + 3×AGGREGATE(n2·n3·n4) 同源 → 优化器融成一条 SQL（省 2 趟往返）**；`kb.vector` 是公共文档，不带 `user_scoped`；其余 Resolver 声明支持用户级权限，执行时收到 `as_user`。

### ③ 执行结果（协调器回填 + 裁决后）

```json
{
  "n2": { "毛利": 12000000, "环比": -0.15, "source": "数仓", "trust": 0.98 },
  "n3": { "毛利": 16000000, "环比": 0.04, "source": "数仓" },
  "n4": { "series": [480, 420, 300], "unit": "万" },
  "n5": { "docs": ["价格政策", "涨价通报"] },
  "n6": { "answer": "华东主因:大客户减采30%+原材料涨价；华南靠新品拉动未受冲击",
          "evidence": ["n5#1"], "trust": 0.82 },
  "n7": { "ticket": "#4521", "status": "created" },
  "verdict": { "毛利": "以 n2 为准(trust 0.98)", "loser": "某源 1180万 → 丢弃数字" }
}
```

> n1 FILTER 不产生独立结果（已折进 n2·n3·n4 的同一条 SQL 的 WHERE）。

**一句话总纲：SQG（问什么）→ plan（谁来答 · 怎么调 · 谁在问）→ result（答什么），三段一一对应。**

---
---

# 第二部分 · 后端工程实现

> 本部分讲「后端怎么落地」。**领域模型（Concept / Binding / Resolver / SQG / 运行引擎）不再重复定义，一律引用上文第 3、5、6、7 节。** 本部分只写后端特有内容：技术选型、架构、存储实现、API、SDK、配置、阶段。

## 16. 后端目标与两种形态

后端把用户一句话变成流水线：**提问 → 编译 → 调度 → 协调 → 生成 → 答案 + 血缘 + 动作回执**（模型见第 7 节）。交付两种形态，共用同一内核：

| 形态 | 载体 | 使用者 |
|---|---|---|
| **① REST API** | FastAPI 服务（`backend/app`） | 前端 UI、外部系统 HTTP |
| **② SDK** | `nexus` 包（框架无关，可 `pip` 安装） | 其他 Python 程序直接 `import` |

**核心约束**：引擎内核（`nexus` 包）不依赖任何 Web 框架；API 只是内核之上的薄适配。两种形态共用同一个 `NexusClient`，永不分叉。

## 17. 后端技术选型

| 关注点 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | LLM 编排 + 数据连接器生态最成熟 |
| Web 框架 | FastAPI + uvicorn | 异步原生、OpenAPI、SSE 流式 |
| 数据模型 | pydantic v2 | 校验 + LLM 结构化输出目标类型 |
| 并发 | asyncio | 协调器分波并行（`asyncio.gather`） |
| 主数据库 | **Azure SQL Database** | 本体 + 运行审计存储（生产） |
| DB 访问 | SQLAlchemy Core + pyodbc（ODBC Driver 18） | 对接 Azure SQL；本地可切 SQLite |
| LLM | openai SDK（兼容 Azure OpenAI） | 编译器结构化生成、生成器答案 |
| 容器 | 三层 Docker（base 含 msodbcsql18） | Azure SQL 需 ODBC 驱动 |

> 密钥走环境变量 / Key Vault，绝不入库、不进日志。

## 18. 后端总体架构

### 18.1 分层 → 模块映射

| 层 | 职责 | 后端模块 |
|---|---|---|
| L4 意图层 | NL → SQG | `nexus/engine/compiler.py` |
| L3 认知层（核心） | 调度 · 协调 · 生成 | `nexus/engine/{Optimizer,coordinator,generator}.py` |
| L2 语义层 | 本体 + 能力清单 | `nexus/core/*` · `nexus/ontology/*` · `nexus/registry.py` |
| L1 接入层 | 数据 / Agent / 动作 | `nexus/resolvers/*` |
| 竖切面 | 权限 / 血缘 / 成本 | `policy` / `provenance` / 运行审计表 |

### 18.2 内核 vs 宿主包结构

```
backend/app/
├─ main.py bootstrap.py config*.json config.py   ← FastAPI 宿主 + 配置
├─ api/v1/                                         ← HTTP 适配层（薄）
├─ core/services.py                                ← IoC 容器
├─ models/                                         ← API 请求/响应模型
├─ utils/                                          ← logger / json
└─ nexus/            ★ 引擎 SDK（框架无关，可独立发包）
   ├─ client.py      NexusClient 门面
   ├─ core/          领域模型（见第 3/5/6 节）
   ├─ resolvers/     Resolver 接口 + 五类实现（见第 5 节）
   ├─ engine/        Compiler / Optimizer / Coordinator / Generator（见第 7 节）
   ├─ ontology/      本体存储
   └─ registry.py    Resolver 注册表 + 选源竞标
```

## 19. 本体存储实现（Azure SQL）

`OntologyStore` 抽象类两套实现：`AzureSqlOntologyStore`（生产，pyodbc）/ `SqliteOntologyStore`（本地）。切换由 `config.nexus.ontology.backend` 决定，引擎无感。

**Concept↔Binding 关联（定论）**：一对多。**外键 `Binding.concept_id` 为唯一真相**；`Concept.bindings`（前向列表）作为便捷/派生视图（读时由 `concept_id` 反查组装），避免两处存储漂移。

**DDL 草案**（复合字段以 JSON 存于 `NVARCHAR(MAX)`，读时反序列化为 pydantic）：

```sql
-- 概念（5 种 kind 同表；kind 专属字段存 attrs JSON）
CREATE TABLE nexus_concepts (
    id NVARCHAR(200) PRIMARY KEY, kind NVARCHAR(32) NOT NULL, name NVARCHAR(200) NOT NULL,
    semantics NVARCHAR(MAX), synonyms NVARCHAR(MAX),                       -- JSON
    attrs NVARCHAR(MAX),   -- JSON：kind 专属：attribute.{entity,type}；metric.{expr}；
                           --   relation.{left,right,cardinality,direction,join_type}；derivation.{target,sources,transform}
    policy NVARCHAR(MAX), provenance NVARCHAR(MAX),                        -- JSON
    updated_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);  -- 不存 bindings 列，由 nexus_bindings.concept_id 反查

-- 绑定（只挂 entity→表 / attribute→列；无 joins，join 归 relation）
CREATE TABLE nexus_bindings (
    id NVARCHAR(200) PRIMARY KEY, concept_id NVARCHAR(200) NOT NULL,
    resolver NVARCHAR(100) NOT NULL, kind NVARCHAR(32) NOT NULL,   -- table|column|prompt|file|endpoint
    expr NVARCHAR(MAX),                                            -- 表名/列名/表达式/模板/路径/端点
    confidence FLOAT NOT NULL DEFAULT 1.0,
    CONSTRAINT FK_binding_concept FOREIGN KEY (concept_id) REFERENCES nexus_concepts(id)
);
CREATE INDEX IX_bindings_concept ON nexus_bindings(concept_id);

CREATE TABLE nexus_runs (
    run_id NVARCHAR(64) PRIMARY KEY, as_user NVARCHAR(200), question NVARCHAR(MAX) NOT NULL,
    sqg NVARCHAR(MAX), plan NVARCHAR(MAX), result NVARCHAR(MAX), verdict NVARCHAR(MAX),  -- JSON
    status NVARCHAR(32) NOT NULL, cost_ms INT, created_at DATETIME2 NOT NULL DEFAULT SYSUTCDATETIME()
);

CREATE TABLE nexus_run_steps (
    id BIGINT IDENTITY PRIMARY KEY, run_id NVARCHAR(64) NOT NULL, node_id NVARCHAR(64) NOT NULL,
    resolver NVARCHAR(100), call NVARCHAR(MAX), output NVARCHAR(MAX), trust FLOAT, verdict NVARCHAR(MAX),
    started_at DATETIME2, ended_at DATETIME2,
    CONSTRAINT FK_step_run FOREIGN KEY (run_id) REFERENCES nexus_runs(run_id)
);
```

## 20. API 设计

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/ask` | 一句话提问 → 答案+血缘（同步） |
| POST | `/api/v1/ask/stream` | 同上，SSE 流式 |
| GET/POST | `/api/v1/concepts` | 概念读写 |
| GET/POST | `/api/v1/bindings` | 绑定读写 |
| GET | `/api/v1/resolvers` | 列出 Resolver 能力清单 |
| GET | `/api/v1/runs/{run_id}` | 查某次运行的血缘 |

约定：请求/响应模型在 `models/api.py`，与领域模型解耦；统一响应 `{ state, message, data }`；流式走 `text/event-stream`；鉴权用 MSAL/JWT，`as_user` 从 token 解析（不信任前端传入）；错误码 501（未实现）/422（校验）/401（鉴权）/502（源错误，附血缘）。

## 21. SDK 设计

`NexusClient`（`nexus/client.py`）装配本体存储 + 注册表 + 四段引擎，唯一入口：

```python
from nexus import NexusClient
from nexus.resolvers import SqlResolver
nexus = NexusClient(config)                       # config: {ontology, llm}
nexus.register_resolver(SqlResolver("dwh.sql", {...}))
answer = await nexus.ask("华东上季度毛利为什么下滑？", as_user="zhangsan@beone")
```

API 层与 SDK 复用同一个 `NexusClient`（由 IoC 容器单例托管）；`ask` / `ask_stream` 两个入口。

## 22. 配置与服务容器

- **config**（`config.py`）：分层加载 `文件 → 环境变量`，单例；`config.{APP_ENVIRONMENT}.json` 切环境；密钥用 `APP_PREFIX` 前缀环境变量覆盖，脱敏后才记日志。
- **services**（`core/services.py`）：IoC 容器，`services[NexusClient]` 懒加载单例。
- **bootstrap**：`register_services()` 注册类型；`register_resolvers()` 装配各源 Resolver。

## 23. LLM 集成

Provider 抽象（`nexus/llm/`）封装 Azure OpenAI / OpenAI，统一 `complete(messages, schema)` 结构化输出；编译器用「JSON schema 约束 + 校验重试」保证产出合法 SQG；生成器用 Jinja2 模板产出答案；token 计量写入运行记录。

## 24. 可观测性与血缘

日志（`utils/logger.py`）结构化 + `trace_id`；每次运行落 `nexus_runs` + 每节点落 `nexus_run_steps`；`/runs/{id}` 回看「答案里每个数字的来源与裁决」；按 run/resolver 累计耗时、token。

## 25. 错误处理与取消

`ExecContext.cancellation_token` 贯穿执行，协调器每波检查取消；单节点失败隔离（记入血缘并在裁决/生成时降级说明）；ACT 类动作带 `idempotency_key` 防重复。

## 26. 测试策略

| 层级 | 对象 | 手段 |
|---|---|---|
| 单元 | 模型校验、拓扑分波、回填、裁决、竞标打分 | pytest，纯函数 |
| 契约 | Resolver 接口一致性 | 抽象测试套件，各实现复用 |
| 集成 | 本体存储（SQLite 内存库）、SqlResolver 取数 | pytest + 临时库 |
| 端到端 | 示例问题「华东毛利下滑」走完四段 | stub LLM + 内存 SQL 源，断言答案结构与血缘 |

贯穿用例固定为第 15 节附录的三段 JSON，作为回归基线。

## 27. 后端目录结构

```
backend/app/
├─ main.py bootstrap.py config.py config.json config.development.json
├─ api/v1/  router.py  endpoints/(ask concepts bindings resolvers runs)
├─ core/    services.py deps.py
├─ models/  base.py api.py
├─ utils/   logger.py json_utils.py
└─ nexus/
   ├─ client.py registry.py
   ├─ core/     models.py capabilities.py sqg.py context.py
   ├─ resolvers/ base.py sql.py vector.py agent.py rest.py action.py
   ├─ engine/    compiler.py Optimizer.py coordinator.py generator.py
   ├─ ontology/  store.py azure_sql.py sqlite.py
   └─ llm/       base.py azure_openai.py
```

## 28. 后端开发阶段 P0–P4

原则：每阶段一个可演示闭环 + 验证一个核心假设；P0 就把三大接口（Concept/Resolver/SQG）定死，之后只加实现、不改范式。

| 阶段 | 目标 | 范围 | 验收 |
|---|---|---|---|
| **P0** ★ | 一个 SQL 源能问答 | 领域模型 + `SqliteOntologyStore` + `SqlResolver`（真实取数）+ 四段引擎最小实现 + `NexusClient.ask` + `/ask\|concepts\|bindings\|resolvers` + 运行记录落库；编译器可先规则/模板兜底 | 对一张 `fact_sales` 问「华东上季度毛利」返回数值+血缘；`/ask` 不再 501 |
| **P1** | 跨源融合 | `VectorResolver`（RAG）+ 合并/裁决完善 + LLM 编译器上线 + Azure SQL 本体存储 | 命中「数仓数值 + 知识库佐证」合并成一份，冲突按信任分裁决 |
| **P2** | 智能体源 | `AgentResolver` + `ASK` 闭环 + 接一个真实 Data Agent | 归因由 Agent 回答并返回结构化证据 |
| **P3** | 分析即行动 | `ActionResolver` + `ACT` + 幂等 + `RestResolver` | 问答后自动建复盘工单并回执，血缘可查 |
| **P4** | 自动建本体 | `describe/sample` + LLM 推断候选 + 人工确认台 | 对接新库半自动生成可用本体 |

## 29. 里程碑与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| NL→SQG 准确率 | 编译错→答非所问 | schema 约束 + 校验重试 + P0 规则兜底 |
| 跨源主键对齐 | 合并错 | 以 Concept id 为主键，Binding 显式声明 grain |
| Agent 返回非结构化 | 无法裁决/血缘 | 约定 Agent 返回「答案+证据」结构，缺失降级 |
| Azure SQL 连接/驱动 | 部署失败 | 三层 Docker 预装 msodbcsql18；连接串走环境变量 |
| 本体自动生成质量 | 人工成本高 | 高置信自动收、低置信标红人工确认 |

---
---

# 第三部分 · 前端设计

> 前端是 .NET 解决方案（`frontend/DataNexus`：`datanexus.client` Vue 前端 + `DataNexus.Server` + `DataNexus.Library`）。本部分待补。

## 30. 前端设计（待补）

规划要点（占位，后续展开）：
- **技术栈**：Vue 3 + Vite + TypeScript + Element Plus；通用基础设施 `src/common`（`API.ts`/`APIService.ts`/`AppConfig.ts`/`MSAL.ts`）。
- **鉴权**：MSAL（`@azure/msal-browser`），token 传后端由其解析 `as_user`。
- **核心界面**：对话提问框 → 流式答案（SSE）→ 血缘/来源展开 → 动作回执卡片。
- **本体管理台**：Concept / Binding 的浏览与人工确认（对接 P4 自动建本体）。
- 详细设计待与后端 API（第 20 节）联调时补齐。
