# Data Nexus 前端设计（UI Design）

> 核心架构、typed SQG、PEP、跨源优化和 relation schema 以 [data_nexus_design.md](data_nexus_design.md) 为准。本文件定义这些能力如何在 UI 中被创建、理解、执行和审计。

> **实现状态（2026-07-22）**：graph-v3 关系编辑器、强类型指标构建器、typed SQG 节点详情、Fragment PEP DAG、`realizes` 融合展示、Optimizer 四类 artifact 浏览和五阶段运行视图已落地；BFF 复用现有 `run_stage.logs`，未修改数据库表结构。

旧本体转换位置：**本体管理 → 打开旧本体 → 黄色转换提示 →「转换为 graph v3」**。转换仅生成前端草稿；确认关系、修正指标并点击保存后才写回原 graph JSON。

## 0. UI 核心原则

1. **SQG 面向业务用户**：默认只展示“解决问题要做哪些步骤”，不展示 Scan、Filter、JOIN、Sort 等关系代数细节。
2. **PEP 面向开发和运维用户**：展示执行位置、Fragment、Exchange、融合、下推和 logical output bindings。
3. **同一运行提供 SQG/PEP 双视图**，用户可以看“怎么想”和“怎么执行”，但两张图不能混在一起。
4. **关系建模必须显式**：用户设置实体关联时必须选择方向性基数和可选性；无法确认时主动选择“未知”，不能由系统静默假设。
5. **结构与状态分离**：SQG/PEP JSON 决定图结构，运行记录只覆盖状态、耗时、结果和错误。
6. **确定性数据直接展示**：表格、数值和排名不交给 LLM 改写；ASK 的 Markdown 必须经过 sanitizer。
7. **复杂能力渐进披露**：图上保持简洁，typed spec、内部 operator tree、SQL 和优化证明放在节点详情。

---

## 1. 技术架构与通信

### 1.1 项目结构

| 项目 | 技术 | 职责 |
|---|---|---|
| `datanexus.client` | Vue 3 + TypeScript + Element Plus + VueFlow + Vite | 页面、图、表单、Markdown、安全交互 |
| `DataNexus.Server` | ASP.NET Core BFF | 托管 SPA、JWT、配置下发、直接读取运行/本体元数据 |
| `DataNexus.Library` | .NET 类库 | `SqlService`、`HttpClientService`、鉴权和共享配置 |
| Python Backend | FastAPI + Nexus Engine | Initializer、Compiler、Optimizer、Coordinator、Generator、凭据和 Resolver |

### 1.2 两条通信通道

```text
Vue
  ├→ BFF 相对路径 api/*
  │    ├→ 配置
  │    ├→ 本体/Resolver/LLM 非密元数据
  │    └→ run/run_stage/run_node 轮询
  │
  └→ Python Backend 完整 URL + Bearer
       ├→ ask / compile
       ├→ credential / Key Vault
       ├→ Resolver 测试与 reload
       └→ 本体导入探测
```

- 前端从 BFF 获取 Python Backend BaseUrl。
- 密钥不经过 BFF 数据库存储；敏感字段直接交给 Python Backend 写 Key Vault。
- 运行进度通过 BFF 轮询数据库，不要求 SSE。
- `as_user` 从 Bearer token 获取，不允许前端任意传入。

---

## 2. 信息架构

主导航：

1. **提问台**：提问、答案、出处、运行过程；
2. **运行历史**：搜索和回放每次 run；
3. **本体管理**：实体、属性、指标、关系、动作、挂载能力；
4. **源管理**：SQL、CSV、Web IQ、Agent、Action 等 Resolver；
5. **凭据管理**：动态 schema 表单和 Key Vault；
6. **LLM 管理**：规划模型；
7. **系统诊断**：连接、缓存、能力和版本。

角色视图：

- 业务用户：答案、SQG、出处；
- 数据建模人员：本体画布、relation、metric；
- 开发/运维：PEP、Fragment、SQL、Exchange、性能和错误。

---

## 3. 提问台

### 3.1 输入区

- 问题输入框；
- 可选本体；不选时由 Initializer 路由；
- 规划 LLM 下拉；
- 运行按钮、取消按钮；
- 最近问题快捷入口。

提交后立即显示 run id 和五阶段时间线。

### 3.2 答案区

按结果类型呈现：

| 结果 | UI |
|---|---|
| Scalar | 指标卡：名称、值、单位、口径 |
| Table/Ranking | 确定性 Markdown/原生表格，支持复制和下载 |
| Document/Search | 标题、URL、摘要、可展开全文 |
| ASK | sanitized Markdown |
| ACT | 动作回执卡：对象、状态、幂等键、时间 |

数据类结果不通过 LLM 二次改写。ASK 生成的 Markdown 使用 `marked` 解析并经 DOMPurify 清洗。

### 3.3 出处卡片

每个业务结果显示：

- SQG 节点名称；
- 来源 Source Instance 和对象；
- metric/statistic/grain/scope 摘要；
- 是否跨源；
- 是否 exact/approximate；
- 由哪些 PEP Fragment 实现；
- 优化说明，如“4 个指标合并为 1 次扫描”。

卡片默认固定高度，点击整行展开完整 SQL、关系路径、URL/文档内容和参数摘要。

---

## 4. 五阶段运行面板

### 4.1 时间线

```text
Initializer → Compiler → Optimizer → Coordinator → Generator
```

状态颜色：

- 灰：pending；
- 蓝：running；
- 绿：done；
- 红：failed；
- 黄：skipped/cancelled。

每一阶段可展开：

| 阶段 | 展示内容 |
|---|---|
| Initializer | 候选本体、最终选择、路由缓存命中、可用能力摘要 |
| Compiler | 原问题、typed SQG、校验结果、编译缓存命中 |
| Optimizer | Semantic Binding、Bound Logical Plan（IR）、PEP、候选成本和 optimization trace |
| Coordinator | Fragment 状态、行数、耗时、重试、逻辑结果注册表 |
| Generator | 最终 Markdown/表格、lineage、动作回执 |

默认不显示完整 LLM prompt；具有诊断权限的用户可在日志标签查看脱敏内容。

### 4.2 轮询

- `run.state=running` 时约每 0.5 秒读取一次；
- 浏览器后台时降低频率；
- `done/failed/cancelled` 停止；
- 历史回放只读取一次；
- 轮询失败指数退避，不改变 run 状态。

---

## 5. SQG 视图：用户友好的解题 DAG

### 5.1 展示原则

SQG 图只显示高层业务任务：

```text
华东2024年销售额 ─┐
华东2024年毛利   ─┤
华南2024年销售额 ─┼→ 生成销售报告结论 → 发送报告邮件给颜斌
华南2024年毛利   ─┤
2024年销量前三产品 ┘
```

禁止在 SQG 默认图中出现：

- SCAN/FETCH；
- FILTER；
- JOIN；
- ALIGN；
- SORT/LIMIT；
- PROJECT；
- 临时表和 SQL 子查询。

### 5.2 节点样式

| Operator | 主色 | 节点摘要 |
|---|---|---|
| SELECT | 蓝绿 | 业务对象、字段、范围 |
| AGGREGATE | 青 | 指标/统计、范围、grain、TopN |
| CALCULATE | 紫 | 输入、公式/比较、选择规则 |
| SEARCH | 蓝 | 搜索词、数量 |
| BROWSE | 蓝 | URL/文档 |
| ASK | 橙 | 生成目的、输入节点 |
| ACT | 红 | 动作、目标对象 |

节点主体只显示：

- 业务名称；
- Operator 标签；
- 状态和关键值；
- 错误/缓存/近似计算角标。

### 5.3 节点详情抽屉

详情分四个标签：

1. **业务语义**：名称、scope 的自然语言、metric/statistic、dimension、ranking；
2. **Typed JSON**：只读高亮 `spec`；
3. **结果契约**：schema、grain、domain、ordering、unit；
4. **执行映射**：哪些 PEP Fragment 通过 `realizes` 实现该结果。

Predicate AST 默认转成自然语言，例如：

```text
订单日期：2024-01-01（含）至 2025-01-01（不含）
区域：等于“华东”
```

### 5.4 CALCULATE 展示

CALCULATE 在图上仍是一个业务步骤，例如：

```text
各月中位数 ─┐
             ├→ 找出中位数/平均值比最低月份
各月平均值 ─┘
```

详情中再展开：对齐键、公式、除零策略和 MIN_BY，不在图上拆成 ALIGN/DIVIDE/SORT/LIMIT。

---

## 6. PEP 视图：物理 Fragment DAG

### 6.1 Optimizer 三步产物浏览

Optimizer 阶段展开后固定提供四个标签，前三个对应三步结果，第四个解释决策过程：

| 标签 | 默认视图 | 用于排查 |
|---|---|---|
| **语义绑定** | Concept/Binding 表 + relation path 图 | 概念绑错实体/属性、选错源、关系路径错误 |
| **逻辑计划（IR）** | Bound Logical Plan operator tree | filter/grain/domain/cardinality 推导错误、逻辑改写错误 |
| **物理计划（PEP）** | Fragment DAG | 融合、下推、跨源切分、Exchange 或执行位置错误 |
| **优化过程** | 规则/候选/成本时间线 | 为什么应用或拒绝某条规则、为什么选择当前 PEP |

IR 在界面上的全称首次显示为：

```text
Bound Logical Plan
中间表示（Intermediate Representation, IR）
```

帮助文案：

```text
IR 是 SQG 与可执行 PEP 之间的强类型逻辑计划：它已经解析业务概念和关系，
但还没有决定在哪个数据源执行、是否广播、如何 Exchange 或生成哪种 SQL。
```

#### 语义绑定视图

表格列：

- SQG node / spec path；
- concept id、kind、类型；
- metric expression；
- entity/attribute；
- 候选及选中的 Binding/Source Instance；
- relation path；
- confidence、警告和错误。

点击一条绑定，高亮 SQG 中的引用位置、逻辑计划中的对应 Scan/Relate，以及本体画布 relation。

#### Bound Logical Plan 视图

- 树形视图和原始 JSON 双模式；
- 节点显示 `SCAN/FILTER/RELATE/DERIVE/AGGREGATE/WINDOW/TOP_N`；
- 展示 schema、grain、domain、cardinality、type、source candidates；
- 点击逻辑算子可反向高亮来源 SQG 节点，并正向高亮实现它的 PEP Fragment；
- 默认折叠 typed expression，按需展开。

#### Optimization Trace 视图

按时间/阶段列出：

- applied rule；
- rejected rule + 原因；
- candidate PEP；
- estimated rows/bytes/cost；
- 最终选择原因。

支持筛选规则名、逻辑节点、Fragment 和 warning/error。

#### 失败和缓存

- Optimizer 中途失败时，已保存的 artifact 仍然可浏览；`partial/failed` 使用黄/红状态；
- diagnostics 自动定位到对应 JSON path/operator；
- 缓存命中显示“来自缓存”，并可跳转原 artifact，但当前 run 仍保留自己的 artifact 引用/快照；
- 三步产物均支持复制 JSON 和下载，遵守权限与脱敏策略。

### 6.2 默认 Fragment 图

PEP 默认按执行单元显示：

```text
CSV Source Fragment ─ Exchange ─┐
                                ├→ DuckDB Compute Fragment → ASK → ACT
SQL Source Fragment ─ Exchange ─┘
```

节点类型：

- Source Fragment；
- Exchange；
- Compute Fragment；
- ASK；
- ACT。

Fragment 内的 Scan/Filter/JOIN/Aggregate/TopN 只在展开模式展示。

### 6.3 融合可视化

一个 PEP Fragment 实现多个 SQG 任务时：

- 节点显示“⚡融合 4 个逻辑结果”；
- 展开 `realizes` 映射；
- 可点击某一逻辑结果，高亮对应 physical field；
- SQG 图相应节点保持独立，不出现 PROJECT 拆分节点。

示例：

```text
p_region_metrics
  ⚡ 一次扫描
  realizes:
    华东2024年销售额 → east_sales
    华东2024年毛利   → east_profit
    华南2024年销售额 → south_sales
    华南2024年毛利   → south_profit
```

### 6.4 下推和分支展示

节点角标：

- `FILTER PUSHED`；
- `JOIN PUSHED`；
- `PRE-AGG`；
- `CONDITIONAL AGG`；
- `GLOBAL TOP N`；
- `COMPUTE FALLBACK`；
- `EXACT` / `APPROX`。

如果两个逻辑任务共享前置聚合后分支，PEP 显示共享 Fragment 和两条后处理边，而不是复制整个链。

### 6.5 Exchange 展示

Exchange 边/节点显示：

- 模式：materialize、broadcast、semi-join keys、stream；
- 估算/实际 rows 和 bytes；
- 来源和目标执行位置；
- 批次、参数数量或临时表；
- 是否发生磁盘溢写。

超过阈值时黄/红警告，提示“跨源明细搬运量较大”。

### 6.6 Fragment 详情

标签：

1. **Operator Tree**：内部关系算子树；
2. **Compiled Call**：SQL、参数、URL 或请求体，敏感值脱敏；
3. **Optimization**：候选策略、成本、选择理由、放弃理由；
4. **Lineage**：Source Instance、对象、关系路径、logical outputs；
5. **Runtime**：状态、耗时、行数、重试和错误。

### 6.7 双视图联动

- SQG 节点 → 高亮 `realizes` 它的 PEP Fragment；
- PEP Fragment → 高亮被实现的所有 SQG 节点；
- 选择 relation path → 跳转本体画布并高亮相关 relation；
- URL 查询参数和凭据不进入地址栏。

---

## 7. 本体管理

### 7.1 画布

- entity 为卡片；attribute 列在卡片内；
- fact/dimension 仅作为视觉提示，不是 Optimizer 证明依据；
- relation 为有方向语义的边；
- edge label 显示键、基数和可选性；
- 支持自动布局、缩放、搜索、关系路径高亮；
- 停用属性不参与 Compiler catalog。

建议 relation edge label：

```text
customer_id = customer_id · N:1 · 订单必选 / 客户可选
```

### 7.2 新建/编辑关系对话框

关系对话框不是只选两个键，必须包含以下区域。

#### A. 端点

- From entity；
- From attribute；
- To entity；
- To attribute；
- 属性类型、PK/UNIQUE/NULL 只读提示；
- 复合键以多选并保持顺序，不允许拆成多个独立 relation。

#### B. 关系类型（必选）

单选/卡片：

- N:1 多对一；
- 1:N 一对多；
- 1:1 一对一；
- N:M 多对多；
- 未知/不保证。

选择后填写两个方向的 `max`。N:M 显示警告并建议建立桥 entity。

#### C. 可选性（两个问题均必答）

使用业务句式，不直接让用户理解抽象的 min：

1. “每条 **From** 记录是否必须匹配至少一条 **To** 记录？”
2. “每条 **To** 记录是否必须被至少一条 **From** 记录匹配？”

选项：

- 必须：`min=1`；
- 可以没有：`min=0`；
- 未知：`min=unknown`，优化器按保守策略。

#### D. 完整性来源

- 数据库约束（导入后只读显示约束名）；
- 业务声明；
- 系统推断；
- 未知。

显示 confidence 和来源。手工关系默认 `DECLARED`，不能伪装成 `ENFORCED`。

#### E. 时态关系（高级）

可选：事实时间、有效开始、有效结束；用于历史组织/区域归属。

#### F. 双向自然语言预览

保存前实时展示：

```text
每张订单必须且只能属于一个客户。
一个客户可以没有订单，也可以拥有多张订单。
关系来自数据库外键 FK_order_customer，可信度 100%。
```

用户确认这段话后保存。

### 7.3 Relation 表单校验

禁止保存：

- 端点或属性缺失；
- 两端属性 dtype 明显不兼容；
- 基数/可选性未选择；
- `ENFORCED` 没有约束来源；
- 复合 FK 只选择部分列；
- 时态关系缺少时间字段；
- 自环但没有明确语义。

允许保存“未知”，但必须显示黄色风险标记，并说明：

```text
此关系可用于保守 JOIN，但会禁用依赖基数的预聚合和 JOIN 重排。
```

### 7.4 导入关系确认

SQL/CSV 导入向导增加“关系确认”步骤：

| 字段 | 自动推断来源 |
|---|---|
| 端点 | FK 或列匹配候选 |
| 基数 | PK/UNIQUE/FK |
| From 可选性 | FK 列 NULL/NOT NULL |
| To 可选性 | 通常无法由 FK 单独证明，默认待确认 |
| Integrity | 真实 FK、业务声明或推断 |

流程：

1. 展示候选 relation；
2. 高置信字段预选，推断依据可展开；
3. 用户逐条或批量确认；
4. 未确认关系不进入 Published 本体；
5. 用户可显式改为“未知”后发布。

CSV/跨源候选不得显示成绿色“已确认”。

### 7.5 关系详情和优化影响

点击关系边展示：

- 双向 multiplicity；
- optionality；
- integrity 来源；
- relation 端点和物理绑定；
- 使用该关系的 metric/SQG/运行；
- Optimizer 可用规则：预聚合、JOIN reorder、semi-join；
- 数据质量统计：未匹配率、重复 key 率、最后验证时间。

---

## 8. Metric 与属性编辑

### 8.1 Attribute

字段：名称、id、column、role、dtype、additivity、描述、同义词、enabled。

源约束 PK/UNIQUE/NULL 单独只读展示；用户可以声明业务覆盖，但必须保留 provenance。

### 8.2 Metric

Metric 编辑器使用结构化表达式构建器：

- 属性选择；
- 算术；
- aggregate function；
- null policy；
- unit/result type；
- exact/approximate；
- 实时类型检查和关系路径预览。

高级用户可以查看 typed JSON，但不直接输入 SQL-like 字符串。

---

## 9. 源、凭据与能力管理

### 9.1 Resolver

列表显示：名称、类型、Source Instance、状态、凭据、operators、用户权限、典型延迟。

详情增加 relational capabilities：

- 支持的 filter/join/aggregate/time grain；
- conditional aggregate、window、TopN；
- temp table；
- 参数和并发限制；
- 成本与 egress 信息。

### 9.2 凭据

- 字段由后端 credential schema 动态渲染；
- sensitive 字段不可回显；
- SQL、local file、Azure Blob、Web IQ 等按兼容矩阵选择；
- 保存后执行连接测试；
- 错误仅显示脱敏摘要。

### 9.3 能力刷新

Resolver 或凭据修改后：

1. reload registry；
2. 刷新 capabilities；
3. 标记受影响 Compiler/PEP 缓存失效；
4. 在 UI 显示版本和刷新时间。

---

## 10. 前端数据契约

### 10.1 SQG

```ts
type SQGNode = {
  id: string
  operator: 'SELECT' | 'AGGREGATE' | 'CALCULATE' | 'SEARCH' | 'BROWSE' | 'ASK' | 'ACT'
  name: string
  spec: Record<string, unknown>
  depends_on: string[]
  inputs: Record<string, { node: string; output?: string; row?: number }>
}
```

`depends_on` 展示控制依赖，`inputs` 展示数据输入，两者不可混为一谈。input node 必须属于 `depends_on`，但控制依赖可以不传输出。前端不自行解释所有 AST 细节；使用 operator-specific formatter 将 typed spec 转成摘要，原始 JSON 永远可查看。

### 10.2 PEP

```ts
type PEPNode = {
  id: string
  kind: 'SOURCE_FRAGMENT' | 'EXCHANGE' | 'COMPUTE_FRAGMENT' | 'ASK' | 'ACT'
  source_instance?: string
  depends_on: string[]
  wave: number
  realizes: LogicalOutputBinding[]
  estimates?: { rows?: number; bytes?: number; cost?: number }
  operator_tree?: unknown
}
```

### 10.3 运行记录

```ts
type RunStage = {
  stage: 'initializer' | 'compiler' | 'optimizer' | 'coordinator' | 'generator'
  state: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  input?: unknown
  output?: unknown
  logs?: unknown
  error?: string
  cost_ms?: number
}

type RunNode = {
  node_id: string
  state: 'pending' | 'running' | 'done' | 'failed' | 'skipped'
  resolver?: string
  call?: unknown
  output?: unknown
  value?: string
  source?: string
  error?: string
  cost_ms?: number
  logs?: unknown
}

type OptimizerArtifactType =
  | 'semantic_binding'
  | 'bound_logical_plan'
  | 'physical_execution_plan'
  | 'optimization_trace'

type OptimizerArtifactSummary = {
  artifact_id: string
  run_id: string
  artifact_type: OptimizerArtifactType
  sequence: number
  state: 'complete' | 'partial' | 'failed'
  schema_version: number
  producer_version: string
  input_artifact_id?: string
  input_hash: string
  cache_hit?: boolean
  summary?: Record<string, unknown>
  diagnostics?: Array<Record<string, unknown>>
  created_at: string
}

type OptimizerArtifactDetail = OptimizerArtifactSummary & {
  content: Record<string, unknown>
}
```

Optimizer stage 的 `output` 返回最终 PEP；四类 artifact 位于同一 stage 的 `logs.artifacts`。BFF 复用现有运行详情接口返回 `logs`，前端切换标签时解析相应 key。当前不新增数据库表；若未来 artifact 大到需要独立分页，再另行评审。

### 10.4 Relation

```ts
type Relation = {
  id: string
  name: string
  from: { entity: string; attribute: string | string[] }
  to: { entity: string; attribute: string | string[] }
  multiplicity: {
    from_to: { min: 0 | 1 | 'unknown'; max: 1 | 'many' | 'unknown' }
    to_from: { min: 0 | 1 | 'unknown'; max: 1 | 'many' | 'unknown' }
  }
  integrity: {
    mode: 'ENFORCED' | 'DECLARED' | 'INFERRED' | 'UNKNOWN'
    source?: string
    constraint_name?: string
    confidence?: number
  }
  temporal?: {
    fact_time: string
    valid_from: string
    valid_to: string
  } | null
  semantics?: string
}
```

---

## 11. 状态、错误和可访问性

### 11.1 错误呈现

- Compiler 错误指向具体 SQG 节点/字段；
- relation 错误指向具体端点或 multiplicity；
- PEP 错误显示失败 Fragment 和上游影响；
- ACT 错误区分对象未找到、对象不唯一、权限、远端失败；
- 不把堆栈直接暴露给普通用户。

### 11.2 可访问性

- 所有状态不仅靠颜色，还使用图标和文本；
- VueFlow 节点支持键盘选择；
- 表单 label/错误与控件关联；
- 图提供列表模式，保证屏幕阅读器可读；
- SQL/JSON 使用可复制文本，不只显示截图；
- 缩放后节点最小字号可读。

### 11.3 响应式

- 桌面：SQG/PEP 主图 + 右侧详情；
- 小屏：图与详情切换；
- 关系编辑器使用分步表单，避免 460px 对话框塞入全部字段；
- 大表结果虚拟滚动，lineage 延迟加载。

---

## 12. 验收场景

### 12.1 业务问题

输入销售报告问题后：

- SQG 恰好显示五个取数任务、一个 ASK、一个 ACT；
- 不显示 Filter/JOIN/Sort/Limit；
- PEP 能显示四个地区指标被一次 Source Fragment 融合；
- `realizes` 可从 PEP 反向高亮四个 SQG 节点；
- ASK 和 ACT 各只有一个节点。

### 12.2 跨源 Top 3 区域

- SQG 只显示“销售额排名前三的区域”；
- PEP 显示 CSV Source、SQL Source、Exchange、DuckDB Compute；
- SQL Source 内部可展开 customer JOIN region；
- 若安全，CSV 节点显示 PRE-AGG；
- TopN 节点标记 GLOBAL；
- relation path 可跳转本体图。

### 12.3 Relation

新建 `订单 → 客户` 关系时：

- 未选择关系类型不能保存；
- 未回答两个可选性问题不能保存；
- 选择 N:1、订单必选、客户可选后，预览显示“每张订单必须且只能属于一个客户；客户可以没有订单或有多张订单”；
- 保存后 edge 显示 `N:1` 和可选状态；
- 选择 unknown 时允许保存但显示保守优化警告。

### 12.4 历史回放

- 五阶段时间线完整；
- SQG、Semantic Binding、Bound Logical Plan（IR）与 PEP 均可回放；
- Optimizer artifact 三步链路及 optimization trace 可逐层浏览；
- Optimizer 失败时仍能查看失败前保存的 partial artifact 和 diagnostics；
- PEP 节点状态来自 run_node；
- SQL、参数、relation path、优化理由和 lineage 可追溯；
- 敏感字段保持脱敏。
