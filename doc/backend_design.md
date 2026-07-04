# Data Nexus — 后端开发设计（Backend Development Design）

> 本文是**后端工程实现的详细设计**，先讲清完整思路，再给出可执行的开发阶段。
> 概念模型（Concept / Binding / Resolver / SQG / 运行引擎）的业务定义见同目录 [`data_nexus_design.md`](./data_nexus_design.md)，本文不重复，只聚焦「后端怎么落地」。
>
> 阅读顺序：第 1–4 章建立整体思路 → 第 5–9 章是核心实现设计 → 第 10–13 章是接口/配置/集成 → 第 14–16 章是质量保障 → 第 17–19 章是目录与开发阶段。

---

## 目录

1. [目标与范围](#1-目标与范围)
2. [设计原则](#2-设计原则)
3. [总体架构](#3-总体架构)
4. [技术选型](#4-技术选型)
5. [领域模型](#5-领域模型)
6. [知识层：本体存储（Azure SQL）](#6-知识层本体存储azure-sql)
7. [能力层：Resolver](#7-能力层resolver)
8. [运行引擎：四段流水线](#8-运行引擎四段流水线)
9. [权限与治理](#9-权限与治理)
10. [API 设计](#10-api-设计)
11. [SDK 设计](#11-sdk-设计)
12. [配置与服务容器](#12-配置与服务容器)
13. [LLM 集成](#13-llm-集成)
14. [可观测性与血缘](#14-可观测性与血缘)
15. [错误处理与取消](#15-错误处理与取消)
16. [测试策略](#16-测试策略)
17. [目录结构](#17-目录结构)
18. [开发阶段 P0–P4](#18-开发阶段-p0p4)
19. [里程碑与风险](#19-里程碑与风险)

---

## 1. 目标与范围

### 1.1 后端要做的事

把用户的一句话（例：**「华东上季度毛利为什么下滑，给份说明，并把复盘任务派给区域负责人」**）变成一条自动流水线：**提问 → 编译 → 调度 → 协调 → 生成 → 答案 + 血缘 + 动作回执**。

### 1.2 两种交付形态（同一内核）

| 形态 | 载体 | 使用者 |
|---|---|---|
| **① REST API** | FastAPI 服务（`backend/app`） | 前端 UI、外部系统 HTTP 调用 |
| **② SDK** | `nexus` 包（框架无关，可 `pip` 安装） | 其他 Python 程序直接 `import` |

**核心约束**：引擎内核（`nexus` 包）**不依赖任何 Web 框架**；API 只是内核之上的一层薄适配。两种形态共用同一个 `NexusClient`，永不分叉。

### 1.3 范围边界

- **在范围内**：本体存储、Resolver 接口与 SQL 实现、运行引擎四段、API/SDK、权限透传、血缘、配置与服务容器。
- **暂不做（后续阶段）**：向量库/Agent/动作 Resolver 的完整实现、自动建本体、前端渲染层、复杂裁决策略学习。

---

## 2. 设计原则

1. **SDK 优先、框架无关**：内核不 import fastapi；可被任何宿主嵌入。
2. **统一接口抹平差异**：数据源 / 智能体 / 动作都实现同一个 `Resolver`，引擎里没有类型分支。
3. **配置驱动**：路由、服务、Resolver 装配都由 `config.json` + 环境变量驱动，改配置不改代码。
4. **治理内生**：权限（`policy`）与血缘（`provenance`）随概念/每次运行一起落库，可追溯是默认能力。
5. **异步并行**：协调器按 DAG 分波，用 `asyncio.gather` 并行执行同波节点。
6. **契约先行**：领域模型用 pydantic 定死 schema，既做校验，又当 LLM 结构化输出的目标类型。
7. **可复算**：每次运行的 SQG / plan / result / verdict 全量落库，支持回放与审计。
8. **换源零范式**：接新系统 = 写一个 Resolver + 若干 Binding，引擎与 API 不动。

---

## 3. 总体架构

### 3.1 分层与模块映射

| 层 | 职责 | 后端模块 |
|---|---|---|
| L5 体验层 | 对话 / 渲染 | 前端（`frontend/`，本文不含） |
| L4 意图层 | NL → 查询指令 | `nexus/engine/compiler.py` |
| L3 认知层（核心） | 调度 · 协调 · 生成 | `nexus/engine/{dispatcher,coordinator,generator}.py` |
| L2 语义层 | 本体 + 能力清单 | `nexus/core/*` · `nexus/ontology/*` · `nexus/registry.py` |
| L1 接入层 | 数据 / Agent / 动作 | `nexus/resolvers/*` |
| 竖切面 | 权限 / 血缘 / 成本 | `policy` / `provenance` / 运行审计表 |

**研发重心 = L3 认知层**。

### 3.2 进程内数据流

```
HTTP/SDK 调用
   │  q, as_user
   ▼
NexusClient.ask()
   │
   ├─(1) Compiler.compile(q)      →  SQG（DAG：节点=算子，边=依赖）
   │        查 L2 本体（Concept/Binding）
   │
   ├─(2) Dispatcher.dispatch(sqg) →  Plan（每节点：选中的 resolver + 具体调用 + user_scoped）
   │        查 L2 能力清单 + 选源竞标
   │
   ├─(3) Coordinator.coordinate(plan, ctx) → merged, verdict
   │        调 L1 Resolver.resolve()；分波并行 + 回填 + 合并 + 裁决
   │
   └─(4) Generator.generate(merged, verdict) → Answer（文本 + 血缘 + 回执）
```

- **编译时**只读知识层（Concept/Binding）。
- **执行时**只调能力层（Resolver）。
- 两者通过 SQG / Plan 解耦。

### 3.3 包结构（内核 vs 宿主）

```
backend/app/
├─ main.py / bootstrap.py / config*.json / config.py   ← FastAPI 宿主 + 配置
├─ api/v1/                                               ← HTTP 适配层（薄）
├─ core/services.py                                      ← IoC 容器
├─ models/                                               ← API 请求/响应模型
├─ utils/                                                ← logger / json
└─ nexus/            ★ 引擎 SDK（框架无关，可独立发包）
   ├─ client.py      NexusClient 门面
   ├─ core/          领域模型（pydantic + dataclass）
   ├─ resolvers/     Resolver 接口 + 五类实现
   ├─ engine/        Compiler / Dispatcher / Coordinator / Generator
   ├─ ontology/      本体存储（Azure SQL / SQLite）
   └─ registry.py    Resolver 注册表 + 选源竞标
```

---

## 4. 技术选型

| 关注点 | 选型 | 理由 |
|---|---|---|
| 语言 | Python 3.11+ | LLM 编排 + 数据连接器生态最成熟 |
| Web 框架 | FastAPI + uvicorn | 异步原生、OpenAPI、SSE 流式 |
| 数据模型 | pydantic v2 | 校验 + LLM 结构化输出目标类型 |
| 并发 | asyncio | 协调器分波并行（`asyncio.gather`） |
| 主数据库 | **Azure SQL Database** | 本体 + 运行审计存储（生产） |
| DB 访问 | SQLAlchemy Core + pyodbc（ODBC Driver 18） | 与 Azure SQL 对接；本地可切 SQLite |
| LLM | openai SDK（Azure OpenAI 兼容） | 编译器结构化生成、生成器答案 |
| 打包 | pyproject（`nexus` 可独立发包） | SDK 形态 |
| 容器 | 三层 Docker（base 含 msodbcsql18） | Azure SQL 需 ODBC 驱动 |

> Azure SQL 连接：`Driver={ODBC Driver 18 for SQL Server};Server=...;Database=...;` + 密码或 Entra ID 认证；密钥走环境变量 / Key Vault，绝不入库、不进日志。

---

## 5. 领域模型

所有模型集中在 `nexus/core/`，用 pydantic（数据）+ dataclass（执行上下文）。字段定义与 [`data_nexus_design.md`](./data_nexus_design.md) 第 3、5、6 节一一对应。

### 5.1 知识层

- **Concept**（`core/models.py`）：`id, kind(entity|attribute|relation|metric|dimension), name, semantics, type, synonyms[], bindings[], policy, provenance`。
- **Binding**（`core/models.py`）：`id, concept_id, resolver, kind(sql_expr|column|join|prompt|file|endpoint), expr, table, joins[], grain[], confidence`。
- **Policy**：`sensitivity, row_level`。**Provenance**：`generated_by, confidence, source_ref, updated_at`。

### 5.2 能力层

- **Capabilities**（`core/capabilities.py`）：`resolver, concepts[], operators[], cost, latency_ms, trust, user_scoped, freshness`。

### 5.3 查询指令

- **Operator** 枚举：`SELECT | FILTER | AGGREGATE | TRAVERSE | ASK | ACT`。
- **SQGNode**：`id, op, concept, filter, groupBy, range, query, prompt, action, deps[]`。
- **SQG**：`intent, as_user, nodes[]`。

### 5.4 执行期

- **PlannedCall**：`node, resolver, call, trust, user_scoped`。**Plan**：`as_user, plan[]`。
- **ResolveResult**：`data, evidence[], trust, meta`（数据 / 答案+证据 / 回执统一形状）。
- **ExecContext**（dataclass）：`user, trace_id, cancellation_token`；`with_user(user)` 派生子上下文。
- **SourceSchema**：`tables{table:columns[]}, foreign_keys[]`（自动建本体用）。

> 设计约束：领域模型只描述数据与不变式，**不含 I/O**；I/O 全在 Resolver / Store / Engine 里。

---

## 6. 知识层：本体存储（Azure SQL）

### 6.1 存储抽象

`nexus/ontology/store.py` 定义 `OntologyStore` 抽象类，两套实现：
- `AzureSqlOntologyStore`（生产，pyodbc）
- `SqliteOntologyStore`（本地开发/测试）

接口对上层只暴露：`list_concepts / get_concept / upsert_concept / get_binding / upsert_binding / find_concepts_by_terms`。切换实现由 `config.nexus.ontology.backend` 决定，引擎无感。

### 6.2 表设计（DDL 草案）

复合字段（synonyms/bindings/policy/provenance/joins/grain）用 `NVARCHAR(MAX)` 存 JSON，读时反序列化为 pydantic。

```sql
-- 概念表
CREATE TABLE nexus_concepts (
    id            NVARCHAR(200) NOT NULL PRIMARY KEY,
    kind          NVARCHAR(32)  NOT NULL,
    name          NVARCHAR(200) NOT NULL,
    semantics     NVARCHAR(MAX) NULL,
    type          NVARCHAR(64)  NULL,
    synonyms      NVARCHAR(MAX) NULL,   -- JSON array
    bindings      NVARCHAR(MAX) NULL,   -- JSON array of binding ids
    policy        NVARCHAR(MAX) NULL,   -- JSON
    provenance    NVARCHAR(MAX) NULL,   -- JSON
    updated_at    DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 绑定表
CREATE TABLE nexus_bindings (
    id            NVARCHAR(200) NOT NULL PRIMARY KEY,
    concept_id    NVARCHAR(200) NOT NULL,
    resolver      NVARCHAR(100) NOT NULL,
    kind          NVARCHAR(32)  NOT NULL,
    expr          NVARCHAR(MAX) NULL,
    [table]       NVARCHAR(200) NULL,
    joins         NVARCHAR(MAX) NULL,   -- JSON
    grain         NVARCHAR(MAX) NULL,   -- JSON
    confidence    FLOAT         NOT NULL DEFAULT 1.0,
    CONSTRAINT FK_binding_concept FOREIGN KEY (concept_id) REFERENCES nexus_concepts(id)
);
CREATE INDEX IX_bindings_concept ON nexus_bindings(concept_id);

-- 运行记录（血缘/审计，见第 14 章）
CREATE TABLE nexus_runs (
    run_id      NVARCHAR(64)  NOT NULL PRIMARY KEY,
    as_user     NVARCHAR(200) NULL,
    question    NVARCHAR(MAX) NOT NULL,
    sqg         NVARCHAR(MAX) NULL,      -- JSON
    plan        NVARCHAR(MAX) NULL,      -- JSON
    result      NVARCHAR(MAX) NULL,      -- JSON
    verdict     NVARCHAR(MAX) NULL,      -- JSON
    status      NVARCHAR(32)  NOT NULL,  -- pending|ok|error
    cost_ms     INT           NULL,
    created_at  DATETIME2     NOT NULL DEFAULT SYSUTCDATETIME()
);

-- 运行步骤（每节点一条，细粒度血缘）
CREATE TABLE nexus_run_steps (
    id          BIGINT IDENTITY PRIMARY KEY,
    run_id      NVARCHAR(64)  NOT NULL,
    node_id     NVARCHAR(64)  NOT NULL,
    resolver    NVARCHAR(100) NULL,
    call        NVARCHAR(MAX) NULL,
    output      NVARCHAR(MAX) NULL,
    trust       FLOAT         NULL,
    verdict     NVARCHAR(MAX) NULL,
    started_at  DATETIME2     NULL,
    ended_at    DATETIME2     NULL,
    CONSTRAINT FK_step_run FOREIGN KEY (run_id) REFERENCES nexus_runs(run_id)
);
```

### 6.3 自动建本体（后续阶段）

流程：`Resolver.describe()` 探测表/字段/外键 → `sample()` 抽样 → LLM 推断候选 Concept/Binding + 置信度 → 高置信自动入库、低置信标人工确认。P4 落地，接口在 P0 预留。

---

## 7. 能力层：Resolver

### 7.1 统一接口

`nexus/resolvers/base.py`：

```python
class Resolver(ABC):
    id: str
    def capabilities(self) -> Capabilities: ...          # 报能力
    def plan(self, node, binding) -> PlannedCall: ...     # 评估 + 编译成调用
    async def resolve(self, call, ctx) -> ResolveResult:  # 干活
    def describe(self) -> SourceSchema: ...               # 自动建本体（可选）
    def sample(self, obj, n=20) -> list[dict]: ...        # 抽样（可选）
```

### 7.2 五类实现（按阶段落地）

| # | 类 | 阶段 | resolve 语义 |
|---|---|---|---|
| 1 | `SqlResolver` | **P0** | 用 Binding 拼 SQL 取数（Azure SQL / PG） |
| 2 | `VectorResolver` | P1 | RAG 检索 topk |
| 3 | `AgentResolver` | P2 | 自然语言 `ask()`，返回答案+证据 |
| 4 | `RestResolver` | P3 | HTTP 调外部 API |
| 5 | `ActionResolver` | P3 | 执行副作用（建工单），返回回执 + 幂等键 |

### 7.3 注册表与选源竞标

`nexus/registry.py`：
- `register / get / all`
- `candidates(node)`：返回能覆盖该节点概念且支持其算子的 Resolver。
- 竞标打分（在 Dispatcher 里）：
  $$\text{score} = w_{trust}\cdot trust - w_{cost}\cdot cost - w_{lat}\cdot \text{norm}(latency) + w_{cover}\cdot coverage$$

---

## 8. 运行引擎：四段流水线

### 8.1 Compiler（编译器）— L4

- **输入**：`q`（自然语言）、`as_user`、`history`。**输出**：`SQG`。
- **步骤**：① 意图识别 → ② 概念消歧（把「毛利/华东/上季度」映射到 Concept id；用 `find_concepts_by_terms` + 语义匹配）→ ③ 拆算子建 DAG、标 `deps` → ④ 注入 `as_user`。
- **实现**：给 LLM 喂「候选 Concept 清单 + 算子 schema」，**受约束生成 JSON**，再用 pydantic 校验成 `SQG`；校验失败重试/降级。
- **可测试性**：LLM 客户端抽象成接口，单测用 stub 返回固定 SQG。

### 8.2 Dispatcher（调度器）— L3

对 SQG 每个节点：
1. `registry.candidates(node)` 取候选 → 按 `score` 选中一个（或多个交叉验证）。
2. 调 `resolver.plan(node, binding)` 生成 `call`；依赖别人的节点，`call` 里留 `{nX}` 占位符。
3. 若中标 Resolver `capabilities.user_scoped == True`，给该 plan 项打 `user_scoped=True`。
4. 组装 `Plan(as_user=sqg.as_user, plan=[...])`。

### 8.3 Coordinator（协调器）— L3（核心）

```python
async def coordinate(plan, ctx):
    results = {}
    for wave in topo_waves(plan):                 # 按 deps 拓扑分波
        calls = [backfill(item, results) for item in wave]   # 回填 {nX}
        wave_results = await asyncio.gather(*[run_call(c, ctx) for c in calls])
        results.update(zip([w.node for w in wave], wave_results))
    merged  = merge_by_concept(results)           # 按概念主键对齐合并
    verdict = arbitrate(merged)                    # 数字冲突按 信任×时效×精度 裁决
    return merged, verdict

async def run_call(item, ctx):
    if item.user_scoped:
        ctx = ctx.with_user(plan.as_user)          # ★ 权限透传
    return await registry.get(item.resolver).resolve(item.call, ctx)
```

- **分波**：`topo_waves` 按 `deps` 做 Kahn 拓扑排序，无依赖的同波。
- **回填**：`backfill` 把上游 `ResolveResult` 填进下游 `call` 的 `{nX}`。
- **裁决**：数字类冲突取加权胜者，败者数字丢弃、文字（解释/证据）保留，裁决过程写血缘。

### 8.4 Generator（生成器）— L3

- **输入**：`merged`、`verdict`。**输出**：`Answer(text, lineage)`，支持 SSE 流式。
- 用合并数据 + 模板（Jinja2）写答案；附血缘（每个数字来自哪个节点/Resolver/信任分/裁决）；附动作回执。

---

## 9. 权限与治理

### 9.1 用户级权限透传链路

```
Resolver.capabilities.user_scoped=true
   → Compiler 注入 SQG.as_user
   → Dispatcher 给该 plan 项打 user_scoped
   → Coordinator 执行时 ctx.with_user(as_user)
   → Resolver.resolve 按用户身份在源头做行级安全过滤
```

原则：**权限在数据源头强制，应用层不手工拼 where**。公共源（如向量库公共文档）不带 `user_scoped`。

### 9.2 治理内生

`policy`（敏感级/行级）随 Concept 落库；每次运行的 `sqg/plan/result/verdict` + 每步 `nexus_run_steps` 落库 = 默认可追溯。

---

## 10. API 设计

### 10.1 路由（配置驱动动态加载）

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/health` | 健康检查 |
| POST | `/api/v1/ask` | 一句话提问 → 答案+血缘（同步） |
| POST | `/api/v1/ask/stream` | 同上，SSE 流式 |
| GET | `/api/v1/concepts` | 列出概念 |
| POST | `/api/v1/concepts` | 新增/更新概念 |
| GET | `/api/v1/bindings` | 列出绑定 |
| POST | `/api/v1/bindings` | 新增/更新绑定 |
| GET | `/api/v1/resolvers` | 列出 Resolver 能力清单 |
| GET | `/api/v1/runs/{run_id}` | 查某次运行的血缘 |

### 10.2 约定

- 请求/响应模型在 `models/api.py`（pydantic），与领域模型解耦。
- 统一响应包裹：`{ state, message, data }`（前端 `API.ts` 已按此约定解包）。
- 流式：`text/event-stream`，Generator 逐块 yield。
- 鉴权：MSAL / JWT Bearer（`as_user` 从 token 解析，不信任前端传入）。
- 错误：领域内 `NotImplementedError`→501；校验失败→422；鉴权失败→401；源错误→502 + 血缘。

---

## 11. SDK 设计

`NexusClient`（`nexus/client.py`）是唯一入口，装配本体存储 + 注册表 + 四段引擎：

```python
from nexus import NexusClient
from nexus.resolvers import SqlResolver

nexus = NexusClient(config)                       # config: {ontology, llm}
nexus.register_resolver(SqlResolver("dwh.sql", {...}))
answer = await nexus.ask("华东上季度毛利为什么下滑？", as_user="zhangsan@beone")
```

- API 层与 SDK 复用同一个 `NexusClient`（由 IoC 容器单例托管）。
- `ask`（返回完整答案）与 `ask_stream`（异步生成器，供 SSE）两个入口。

---

## 12. 配置与服务容器

- **config**（`config.py`）：分层加载 `文件 → 环境变量`，单例；`config.{APP_ENVIRONMENT}.json` 切环境；密钥用 `APP_PREFIX` 前缀的环境变量覆盖，脱敏后才记日志。
- **services**（`core/services.py`）：IoC 容器，`services[NexusClient]` 懒加载单例，自动把 `config["nexus"]` 注入构造函数。
- **bootstrap**：`register_services()` 注册类型；`register_resolvers()` 向 NexusClient 装配各源 Resolver。

---

## 13. LLM 集成

- Provider 抽象：`nexus/llm/`（P1 起），封装 Azure OpenAI / OpenAI，统一 `complete(messages, schema)` 结构化输出接口。
- 编译器用「JSON schema 约束 + 校验重试」保证产出合法 SQG。
- 生成器用 `dbo.prompt_templates` 风格的 Jinja2 模板产出答案。
- 成本/token 计量写入运行记录。

---

## 14. 可观测性与血缘

- **日志**：`utils/logger.py` 结构化输出；关键路径打 `trace_id`。
- **血缘**：每次运行落 `nexus_runs` + 每节点落 `nexus_run_steps`；`/runs/{id}` 可回看「答案里每个数字的来源与裁决」。
- **成本计量**：按 run / resolver 累计耗时、token、调用次数。

---

## 15. 错误处理与取消

- `ExecContext.cancellation_token` 贯穿执行；协调器每波检查取消。
- Resolver 错误隔离：单节点失败不必拖垮整图，记入血缘并在裁决/生成时降级说明。
- 幂等：ACT 类动作带 `idempotency_key`，防重复执行。

---

## 16. 测试策略

| 层级 | 对象 | 手段 |
|---|---|---|
| 单元 | 领域模型校验、拓扑分波、回填、裁决、竞标打分 | pytest，纯函数无 I/O |
| 契约 | Resolver 接口一致性 | 抽象测试套件，各实现复用 |
| 集成 | 本体存储（SQLite 内存库）、SqlResolver 取数 | pytest + 临时库 |
| 端到端 | 示例问题「华东毛利下滑」走完四段 | 用 stub LLM + 内存 SQL 源，断言答案结构与血缘 |

贯穿用例固定为 `data_nexus_design.md` 附录的三段 JSON，作为回归基线。

---

## 17. 目录结构

```
backend/app/
├─ main.py  bootstrap.py  config.py  config.json  config.development.json
├─ api/v1/
│  ├─ router.py
│  └─ endpoints/  ask.py  concepts.py  bindings.py  resolvers.py  runs.py
├─ core/    services.py  deps.py
├─ models/  base.py  api.py
├─ utils/   logger.py  json_utils.py
└─ nexus/
   ├─ client.py   registry.py
   ├─ core/        models.py  capabilities.py  sqg.py  context.py
   ├─ resolvers/   base.py  sql.py  vector.py  agent.py  rest.py  action.py
   ├─ engine/      compiler.py  dispatcher.py  coordinator.py  generator.py
   ├─ ontology/    store.py  azure_sql.py  sqlite.py
   └─ llm/         base.py  azure_openai.py
```

---

## 18. 开发阶段 P0–P4

原则：**每阶段一个可演示闭环 + 验证一个核心假设；P0 就把三大接口（Concept/Resolver/SQG）定死，之后只加实现、不改范式。**

### P0 — 骨架：一个 SQL 源能问答 ★当前起点

- **范围**：领域模型（全部）+ `OntologyStore`（SQLite）+ `SqlResolver`（真实取数）+ 四段引擎最小可用实现 + `NexusClient.ask` + `/api/v1/ask|concepts|bindings|resolvers` + 运行记录落库。
- **编译器 P0 简化**：可先用「规则+模板」把有限句式编成 SQG（不强依赖 LLM），LLM 版留接口。
- **交付物**：能对一张 `fact_sales` 问「华东上季度毛利」，返回数值 + 血缘。
- **验收**：端到端测试通过；`/ask` 不再返回 501。
- **依赖**：Azure SQL / SQLite 可连；示例本体（毛利/地区）入库。

### P1 — 联邦：跨源融合

- **范围**：`VectorResolver`（RAG）+ 合并/裁决完善 + LLM 编译器上线（结构化生成）+ Azure SQL 本体存储。
- **验收**：一次提问命中「数仓数值 + 知识库佐证」，合并成一份答案，数字冲突按信任分裁决。

### P2 — 智能体源

- **范围**：`AgentResolver` + `ASK` 算子闭环 + 接一个真实 Data Agent。
- **验收**：归因类问题由 Agent 回答并返回结构化证据，与数仓数值同图协同。

### P3 — 行动：分析即行动

- **范围**：`ActionResolver` + `ACT` 算子 + 幂等 + `RestResolver`。
- **验收**：问答后自动建复盘工单并回执，全程血缘可查。

### P4 — 自演化：自动建本体

- **范围**：`describe/sample` + LLM 推断候选 Concept/Binding + 人工确认工作台。
- **验收**：对接一个新库，半自动生成可用本体，人工只做确认/改名。

---

## 19. 里程碑与风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| NL→SQG 准确率 | 编译错→答非所问 | schema 约束 + 校验重试 + P0 先规则兜底 |
| 跨源主键对齐 | 合并错 | 以 Concept id 为主键，Binding 显式声明 grain |
| Agent 返回非结构化 | 无法裁决/血缘 | 约定 Agent 返回「答案+证据」结构，缺失降级 |
| Azure SQL 连接/驱动 | 部署失败 | 三层 Docker 预装 msodbcsql18；连接串走环境变量 |
| 本体自动生成质量 | 人工成本高 | 高置信自动收、低置信标红，只交人工确认 |

> 下一步（本设计通过后）：进入 **P0**，先落 `SqlResolver` + 最小编译器，让「一个 SQL 源能问答」端到端跑通。
