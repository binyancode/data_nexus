# Data Nexus 平台设计文档

> 一张图 · 一个协议 · 一种查询 —— 联结一切数据、智能体与行动
>
> 本文档是 `doc/design/nexus_platform_ppt.html`（19 页设计稿）的完整实现级说明，可直接据此开发。

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
13. [价值与战略定位](#13-价值与战略定位)
14. [待深挖问题](#14-待深挖问题)
15. [附录：完整 JSON 样例](#15-附录完整-json-样例)

---

## 0. 阅读顺序与核心心智模型

整套系统只有**三大静态构件 + 一条动态流水线**。先记住这张分层：

| 平面 | 构件 | 性质 | 一句话 |
|---|---|---|---|
| 知识层（静态） | **Concept 概念** | 业务名词 | 「销售额、地区、客户」是什么 |
| 知识层（静态） | **Binding 绑定** | 概念→物理映射 | 「销售额」= `SUM(fact_sales.amount)` |
| 能力层（静态） | **Resolver 解析器** | 统一执行接口 | 数据源 / 智能体 / 动作都长成同一个接口 |
| 运行层（动态） | **运行引擎** | 一次提问的流水线 | 提问 → 编译 → 调度 → 协调 → 生成 → 答案 |

动态流水线的中间产物是 **SQG（语义查询图 / 查询指令）**：一张 DAG，节点是算子、边是依赖。

```
用户提问 → 编译器Compiler → SQG(查询指令) → 调度器Dispatcher(选源+编译成调用)
        → 协调器Coordinator(分波并行+回填+合并+裁决) → 生成器Generator(答案+血缘) → 答案
```

- **编译时**：向知识层查 Concept / Binding。
- **执行时**：向能力层调用 Resolver。

> 贯穿全文的示例问题：**「华东上季度毛利为什么下滑，给份说明，并把复盘任务派给区域负责人。」**

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

三层结构，每一层在后文单独展开：

```
┌───────────────────────────────────────────────────────────────┐
│ 知识层 · 本体（静态）                                            │
│   Concept（业务名词）   Binding（概念→物理表映射）               │
└───────────────────────────────────────────────────────────────┘
                    ▲ 编译时查 Concept/Binding
┌───────────────────────────────────────────────────────────────┐
│ 运行引擎（动态）                                                 │
│   提问 → Compiler → SQG → Dispatcher → Coordinator → Generator  │
└───────────────────────────────────────────────────────────────┘
                    ▼ 执行时调用 Resolver
┌───────────────────────────────────────────────────────────────┐
│ 能力层 · Resolver（静态）                                        │
│   数据源 Resolver   Agent Resolver   动作 Resolver               │
└───────────────────────────────────────────────────────────────┘
```

---

## 3. 知识层：本体（Concept + Binding）

### 3.1 Concept（概念）

Concept = 业务名词。只讲「是什么」，不管数据存哪。所有本体元素长成**同一个形状**，靠 `kind` 区分。

**Schema**

```jsonc
{
  "id": "metric.gross_margin",        // 唯一标识
  "kind": "metric",                   // entity|attribute|relation|metric|dimension
  "name": "毛利",                      // 业务显示名
  "semantics": "销售收入 - 销售成本",   // 业务含义（供 LLM 理解 & 消歧）
  "type": "decimal",                  // 数据类型
  "synonyms": ["毛利额", "gross margin"],
  "bindings": ["bind.gross_margin.dwh"], // ★ 指向 Binding，可多个（跨源融合支点）
  "policy": {                          // 权限（治理内生）
    "sensitivity": "internal",
    "row_level": true
  },
  "provenance": {                      // 血缘
    "generated_by": "auto",           // auto|manual
    "confidence": 0.93,
    "source_ref": "dwh.fact_sales",
    "updated_at": "2026-07-04T00:00:00Z"
  }
}
```

**kind 取值**

| kind | 含义 | 示例 |
|---|---|---|
| `entity` | 实体 | 客户、产品 |
| `attribute` | 属性 | 客户名称、产品单价 |
| `relation` | 关系 | 订单→客户 |
| `metric` | 指标（可聚合） | 销售额、毛利 |
| `dimension` | 维度（可切分） | 地区、时间 |

> 实现建议：Concept 存一张表 `nexus_concepts`，字段与 schema 一一对应，`bindings/policy/provenance/synonyms` 用 JSON 列。

### 3.2 Binding（绑定）

Concept 只讲业务、不含物理；Binding 当桥，把概念落到真实物理对象上。对接目标可以是**表、提问模板、文件路径、HTTP 端点**。

**Schema**

```jsonc
{
  "id": "bind.gross_margin.dwh",
  "concept_id": "metric.gross_margin",
  "resolver": "dwh.sql",              // 由哪个 Resolver 执行
  "kind": "sql_expr",                 // sql_expr|column|join|prompt|file|endpoint
  "expr": "SUM(fact_sales.gross_margin)",
  "table": "fact_sales",
  "joins": [                           // 取数需要的 join 路径
    { "left": "fact_sales.region_id", "right": "dim_region.region_id" }
  ],
  "grain": ["dim_region.region_name", "date_trunc('month', order_date)"],
  "confidence": 0.95
}
```

**三条要点**

1. **换库/加源只改 Binding，Concept 不动。**
2. **同一 Concept 可绑多个 Binding = 跨源融合**（例如「毛利」同时绑数仓表和销售 Agent）。
3. **对接目标因 Resolver 而异**：SQL 源绑表达式；Agent 源绑「提问模板」；文件源绑路径；API 源绑端点。

编译示例：用户问「华东上季度毛利」，编译器靠 Binding 拼出：

```sql
SELECT SUM(fact_sales.gross_margin)
FROM fact_sales
JOIN dim_region ON fact_sales.region_id = dim_region.region_id
WHERE dim_region.region_name = '华东'
  AND fact_sales.order_date >= '2024-01-01' AND fact_sales.order_date < '2024-04-01';
```

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

- Concept：`毛利`=指标、`地区`=维度。
- Binding：`毛利`=`SUM(fact_sales.gross_margin)`、`地区`=`dim_region.region_name`；join 自动填好。

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

数据源、AI 智能体、执行动作，三种东西长成**同一个接口**。调度器眼里没有「源」和「Agent」之分，只有一堆**报了能力清单、竞标同一段查询的 Resolver**。

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

### 5.2 五类 Resolver

| # | 源类型 | 性质 | 交互方式 | 说明 |
|---|---|---|---|---|
| 1 | 关系库 SQL / PG | 被动 · 确定 | 查询语言取数 | 结果确定可复算 |
| 2 | 向量库 / 知识库 | 被动 · 近似 | RAG 检索 | topk 召回，近似 |
| 3 | **Fabric Data Agent** ★ | 主动 · 黑盒 | 自然语言 `ask()` | 智能体即源 |
| 4 | REST / SaaS API | 被动 · 外部 | HTTP | 外部系统 |
| 5 | **动作：写回/审批/触发** ★ | 主动 · 有状态 | 副作用调用 | 分析即行动 |

- **被动**：你用查询语言去取数、结果确定。
- **主动**：你把需求交给它、它自己去办（第 3、5 行是差异化）。

### 5.3 能力清单（Capabilities）Schema

```jsonc
{
  "resolver": "dwh.sql",
  "concepts": ["metric.gross_margin", "metric.sales_amount", "dim.region"],
  "operators": ["SELECT", "FILTER", "AGGREGATE", "TRAVERSE"], // 支持的算子
  "cost": 0.2,           // 相对成本 0~1
  "latency_ms": 300,     // 典型时延
  "trust": 0.98,         // 信任分（裁决权重）
  "user_scoped": true,   // ★ 是否支持用户级权限控制（行级安全/数据权限）
  "freshness": "realtime"
}
```

`user_scoped` 是第 8 节权限透传的开关。

### 5.4 竞标 / 路由

同一个 SQG 节点，可能有多个 Resolver 的能力清单覆盖它。调度器按 **信任 / 成本 / 时效** 加权打分，选中一个（或多个做交叉验证）。

```
score(resolver, node) = w_trust * trust
                      - w_cost  * cost
                      - w_lat   * norm(latency)
                      + w_cover * concept_coverage
```

---

## 6. 查询语言：SQG（语义查询图）

SQG = **Semantic Query Graph** = 语义查询图，通俗叫「查询指令」。它是一张 **DAG**：节点是算子、边是依赖。

### 6.1 六个算子

| 算子 | 作用 | 示例 |
|---|---|---|
| `SELECT` | 取属性 / 文档 | 检索佐证文档 |
| `FILTER` | 维度约束 | 只看华东 |
| `AGGREGATE` | 指标计算 | 对毛利求和 |
| `TRAVERSE` | 沿关系跳转（天然跨源 join） | 订单→客户→区域 |
| `ASK` ★ | 把一段交给 Agent 回答 | 归因分析 |
| `ACT` ★ | 执行动作 / 写回 | 建复盘工单 |

**核心结论**：问答（ASK）、跨源 join（TRAVERSE）、写回（ACT）都是**同级算子**，所以「分析」和「行动」用同一套引擎 —— 既能答也能做。

### 6.2 SQGNode Schema

```jsonc
{
  "id": "n3",
  "op": "ASK",                       // SELECT|FILTER|AGGREGATE|TRAVERSE|ASK|ACT
  "concept": "metric.gross_margin",  // 该节点关心的概念（可空，如 ASK/ACT）
  "filter": { "地区": "华东", "期间": "2024Q1" },
  "groupBy": "月",
  "range": "近6月",
  "query": "华东 毛利 下滑",          // SELECT 检索词
  "prompt": "毛利={n1} 趋势={n2}，解释下滑原因", // ASK 的问法，{n} 是占位符
  "action": "create_ticket",         // ACT 的动作
  "deps": ["n1", "n2"]               // 依赖的节点（决定执行波次）
}
```

### 6.3 SQG（整图）Schema

```jsonc
{
  "intent": "explain_and_act",
  "as_user": "zhangsan@beone",       // 当前用户（见第 8 节）
  "nodes": [ /* SQGNode[] */ ]
}
```

> 占位符规则：任何 `deps` 非空的节点，其 `prompt` / `action.desc` 里用 `{nX}` 引用上游结果，**运行时回填**。

---

## 7. 运行引擎

一次提问的完整流水线，四段：

```
提问 → ①Compiler 编译器 → SQG
     → ②Dispatcher 调度器 → 执行计划 plan
     → ③Coordinator 协调器 → 合并结果
     → ④Generator 生成器 → 答案 + 血缘
```

### 7.1 编译器 Compiler

**输入**：用户自然语言 + 历史。**输出**：SQG（DAG）。

职责：
1. 意图识别（`intent`）。
2. 概念消歧：把「毛利」「华东」「上季度」映射到 Concept id。
3. 拆算子建 DAG，标注 `deps`。
4. 注入 `as_user`。

实现建议：LLM 受约束生成（给定 Concept 清单 + 算子 schema，输出 JSON），再做 schema 校验。

### 7.2 调度器 Dispatcher（选源 + 编译成调用 + 权限透传）

对 SQG 每个节点做两件事：

1. **选源竞标**：让能覆盖该节点概念的 Resolver 竞标，按信任/成本/时效选中（见 5.4）。
2. **编译成真实调用**：调 `resolver.plan(node, binding)`，用 Binding 生成 `call`（SQL / 检索 / 自然语言 / HTTP）。依赖别人的节点，`call` 里留 `{nX}` 占位符。
3. **权限透传**：若中标 Resolver 的 `capabilities.user_scoped == true`，给该 plan 项打 `user_scoped: true`；执行时把 `as_user` 传给它（见第 8 节）。

**执行计划 plan Schema**

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

一句话：**调度器 = 选源 + 把每个节点编译成真实调用 + 标注谁需要用户身份。**

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

---

## 8. 权限与治理

### 8.1 用户级权限透传（本平台重点）

有些 Resolver 自己带**用户级权限控制**（行级安全 / 数据权限）。设计原则：**权限在数据源头强制，不在应用层手工拼 where。**

流程：

1. Resolver 在 `capabilities()` 里声明 `user_scoped: true`。
2. 编译器在 SQG 顶部注入 `as_user`（当前登录用户）。
3. 调度器给中标的 user_scoped 节点打 `user_scoped: true`。
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
| L3 | 认知层（核心） | 调度 · 协调 · 生成 | **Dispatcher / Coordinator / Generator** |
| L2 | 语义层 | 本体 + 各源能力清单 | **Concept / Binding / Capabilities** |
| L1 | 接入层 | 数据 / Agent / 动作 | **Resolver** |
| 竖切面 | 治理内生 | 权限 / 血缘 / 成本 | `policy` / `provenance` |

研发重心：**L3 认知层**。

---

## 10. 端到端示例

**问题**：「华东区上季度毛利为什么下滑？给份说明，并把复盘任务派给区域负责人。」

| 阶段 | 产物 |
|---|---|
| ① Compiler | SQG（n1 毛利数值 / n2 趋势 / n4 佐证 / n3 归因ASK / n5 派任务ACT） |
| ② Dispatcher | plan：n1/n2→dwh.sql、n4→kb.vector、n3→agent.sales、n5→ticket.http；标注 user_scoped |
| ③ Coordinator | 3 波并行执行 + 回填 + 合并 + 裁决 |
| ④ Generator | 说明 + 趋势图 + 血缘 + 派任回执 |

四张中标 Resolver（带信任分）：数仓 0.98、Data Agent 0.82、知识库 0.75、动作（回执）。

**重点**：全程没有任何「针对某个源」的特殊分支，全是「算子 + Resolver 竞标 + 合并」。

（三段真实 JSON 见[第 15 节附录](#15-附录完整-json-样例)。）

---

## 11. 落地路径 P0–P4

| 阶段 | 名称 | 目标 | 验证 |
|---|---|---|---|
| **P0** | 骨架 | 本体 + Resolver 接口 + SQG 编译器 | 一个 SQL 源能问答 |
| **P1** | 联邦 | 加向量库 Resolver + 合并/裁决 | 跨源融合 |
| **P2** ★ | 智能体源 | 加 ASK 算子 + 接一个 Fabric Data Agent | 「Agent = 源」 |
| **P3** | 行动 | 加 ACT 算子 + 动作 Resolver | 「分析 → 行动」打通 |
| **P4** | 自演化 | Resolver 探测源自动生成本体 | 半自动建本体 |

原则：

- 每阶段都要有可演示闭环。
- **P0 就把三大接口（Concept / Resolver / SQG）定死**，之后只加实现、不改范式。

风险点：本体自动生成准确率、Agent 返回证据的结构化、跨源主键对齐。

---

## 12. 复用现有代码资产

本平台是当前 PowerBI Copilot 语义引擎的**超集**，大量资产可直接迁移：

| 现有资产（`backend/app/services/semantic_engine/`） | 迁移为 |
|---|---|
| `Orchestrator`（`orchestrator.py`） | **Dispatcher 调度器** 的雏形（状态机 → DAG 调度） |
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
- `Orchestrator.next_action()`（线性状态机） → `Dispatcher` 产出 plan + `Coordinator` 拓扑分波（升级为 DAG）。

---

## 13. 价值与战略定位

### 13.1 五个价值

1. **加源零范式**：接新系统 = 写一个 Resolver，引擎不改。
2. **一种查询**：查数据 / 血缘 / 权限 / 问 Agent 全是同一种查询。
3. **分析即行动**：ASK 与 ACT 同级，洞察到执行同一引擎打通。
4. **治理内生**：权限和血缘随概念一起管，可追溯是默认。
5. **Agent 无缝**：多智能体联邦是 Resolver 竞标机制的自然子集。

判据：加任何新东西，本质只是「本体里加一个 Concept，或加一个 Resolver」，范式不变。

### 13.2 三个战略定位

| 方案 | 定位 | 对标 | 特点 |
|---|---|---|---|
| A | 联邦语义中台 | Palantir、dbt | 跨源统一问答 + 血缘治理；偏重、B 端 |
| B | Agent 编排总控 | MCP 生态 | 编排 Fabric / 专家 Agent；轻、快 |
| **C** ★ | 自助分析 Copilot | 现有 PowerBI Copilot 超集 | 落地最短，复用最多 |

**建议**：C 起步（复用现有资产最多）→ 架构按 A 分层 → 内置 B 的「Agent 即源」做核心差异化。

---

## 14. 待深挖问题

1. **本体存储选型**：属性图 vs RDF vs 关系库模拟；P0 用 SQL 模拟起步。
2. **SQG 算子代数 + 编译器**：把六个算子定义完整，设计 NL→SQG 的受约束生成。
3. **Resolver 竞标 / 路由算法**：「成本-信任-时效」加权模型，冲突裁决细则。
4. **自动建本体准确率**：结构探测 + 抽样 + LLM 推断的候选质量，减少人工确认。

---

## 15. 附录：完整 JSON 样例

以示例问题「华东上季度毛利为什么下滑，给说明并派复盘任务」为例，三段一一对应。

### ① 查询指令 SQG（编译器输出，`{n}` 是占位符）

```json
{
  "intent": "explain_and_act",
  "as_user": "zhangsan@beone",
  "nodes": [
    { "id": "n1", "op": "AGGREGATE",
      "concept": "metric.gross_margin",
      "filter": { "地区": "华东", "期间": "2024Q1" } },
    { "id": "n2", "op": "AGGREGATE",
      "concept": "metric.gross_margin",
      "groupBy": "月", "range": "近6月" },
    { "id": "n4", "op": "SELECT",
      "concept": "doc.evidence",
      "query": "华东 毛利 下滑" },
    { "id": "n3", "op": "ASK", "deps": ["n1", "n2"],
      "prompt": "毛利={n1} 趋势={n2}，解释下滑原因" },
    { "id": "n5", "op": "ACT", "deps": ["n3"],
      "action": "create_ticket", "desc": "{n3}" }
  ]
}
```

### ② 调度器 plan（翻译成 Resolver 调用 + 透传用户）

```json
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
      "call": { "q": "华东 毛利 下滑", "topk": 3 } },
    { "node": "n3", "resolver": "agent.sales",
      "call": { "ask": "毛利={n1} 趋势={n2}，解释下滑原因" },
      "user_scoped": true },
    { "node": "n5", "resolver": "ticket.http",
      "call": { "POST": "/tickets", "body": { "desc": "{n3}" } },
      "user_scoped": true }
  ]
}
```

> `kb.vector` 是公共文档，不带 `user_scoped`；其余 Resolver 声明支持用户级权限，执行时收到 `as_user`。

### ③ 执行结果（协调器回填 + 裁决后）

```json
{
  "n1": { "毛利": 12000000, "环比": -0.15, "source": "数仓", "trust": 0.98 },
  "n2": { "series": [480, 420, 300], "unit": "万" },
  "n4": { "docs": ["价格政策", "涨价通报"] },
  "n3": { "answer": "主因:大客户减采30%+原材料涨价",
          "evidence": ["n4#1"], "trust": 0.82 },
  "n5": { "ticket": "#4521", "status": "created" },
  "verdict": { "毛利": "以 n1 为准(trust 0.98)", "loser": "某源 1180万 → 丢弃数字" }
}
```

**一句话总纲：SQG（问什么）→ plan（谁来答 · 怎么调 · 谁在问）→ result（答什么），三段一一对应。**
