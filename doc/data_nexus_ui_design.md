# Data Nexus 前端设计（UI Design）

> 配套文档：`data_nexus_design.md`（后端/引擎设计）。本文件只讲**前端如何呈现整个系统**，以及前端与 BFF、后端的通信方式。
> register：本文档随实现更新，保持与代码一致。

---

## 1. 目标：把「打通语义与数据」变成看得见的操作

系统的核心体验是**一句话提问 → 跨源取数 → 答案 + 出处**。前端要让这件事直观、可信、可管理：

- **敢问**：一个干净的提问台，像聊天一样问业务问题。
- **敢信**：每个数字都能点开看「来自哪个库 / 哪张表 / 什么口径」（出处）。
- **可管**：本体（业务名词）、数据源、LLM 都能在界面上注册、查看、维护。
- **可查**：每一次提问都留痕，能回看当时的问题、查询计划、结果与出处。

---

## 2. 技术架构：Vue 客户端 + .NET BFF + 共享库

沿用 AIBI 前端的成熟结构（`frontend/DataNexus/`）：

| 项目 | 技术 | 职责 |
|---|---|---|
| `datanexus.client` | Vue 3 + TS + Element Plus + Vite | 界面与交互；MSAL 登录；调用 `api/*` |
| `DataNexus.Server` | ASP.NET Core（BFF） | 托管 SPA；校验 JWT；**直连 DB** 做元数据/历史读写；**代理**到 Python 后端 |
| `DataNexus.Library` | .NET 类库 | 共享服务：`HttpClientService`（调后端）、`SqlService`（连库）、鉴权、配置 |

### 2.1 两条通信通道（关键设计）

> **前端有自己的 .NET BFF。和数据库的操作直接在 BFF 执行；要和真正的后端（Python 引擎）沟通，则通过 API。**

```mermaid
flowchart LR
    subgraph Client[datanexus.client · Vue]
      UI[页面/组件]
      BFFCALL["src/bff/*  →  api/*"]
      BECALL["src/backend/*  →  api/backend/*"]
    end
    subgraph Client[datanexus.client · Vue]
      UI[页面/组件]
      BFFCALL["src/bff/*  →  api/*（相对路径）"]
      BECALL["src/backend/*  →  完整后端 URL"]
    end
    subgraph Server[DataNexus.Server · BFF]
      CTRL[Controllers：配置端点 + 走 DB 的功能]
      SQL[SqlService 直连 DB]
    end
    PY[Python 引擎 API<br/>/api/v1/*]
    DB[(Azure SQL · nexus schema)]
    KV[(Key Vault)]

    UI --> BFFCALL --> CTRL --> SQL --> DB
    UI -- "直连：完整 URL + Bearer" --> BECALL --> PY
    PY --> DB
    PY --> KV
    CTRL -. 提供 config/BackendAPI（后端地址）.-> BECALL
```

- **Vue → BFF**（`src/bff/*`，相对 `api/<path>`）：配置端点（`config/BackendAPI`、`config/MSAL`）+ BFF 原生、走 DB 的功能。dev 用 vite 代理 `^/api`→BFF，生产同源。
- **Vue → Python 后端（直连）**（`src/backend/*`）：先从 BFF 拿到后端 BaseUrl（`config/BackendAPI`），再用**完整 URL** 直接打后端 `/api/v1/*`，请求带 MSAL `Authorization: Bearer`。后端用 `require_auth` 验 JWT，并对 SPA 源开 CORS。用于跑引擎（`/ask`）、编译、凭据等。
- **BFF → DB（直连）**：`SqlService` 读写 `nexus` schema 的元数据（concepts / bindings / resolvers / llms）与运行历史（runs / run_steps）。

### 2.2 前端目录约定（镜像 AIBI）

- `src/backend/*.ts` —— **直连 Python 后端**：`backendUrl(path)`（在 `bff/Config.ts`）用 `config/BackendAPI` 的 BaseUrl 拼成完整 URL，`service` 带 Bearer 直接请求。例：`Ask.ts`、`Credential.ts`。
- `src/bff/*.ts` —— 调 BFF（相对 `api/*`）：`Config.ts`（含 `backendUrl` 助手 + 取后端地址）、`Runs.ts`、`Ontology.ts`。
- `src/common/*` —— 已就位：`API.ts`（HTTP 客户端；遇完整 `http(s)://` URL 则直打，否则加 `api/` 前缀）、`APIService.ts`、`MSAL.ts`、`AppConfig.ts`。

---

## 3. 谁走哪条通道（职责划分）

| 操作 | 通道 | 说明 |
|---|---|---|
| 提问（跑四段引擎） | **前端直连后端** `/api/v1/ask` | 带 Bearer；后端 `require_auth` 验 JWT + CORS |
| 编译预览（看 NL→SQG） | **前端直连后端** | 让用户看「问题被翻成什么查询」 |
| 保存/更新数据源密文（连接串、Key） | **前端直连后端**（credential→KV） | 密文只由后端写 Key Vault |
| 浏览/编辑 概念·绑定（本体） | **BFF 直连 DB** | 读写 `nexus.concepts / bindings` |
| 浏览/新增/停用 Resolver、LLM 注册行 | **BFF 直连 DB** | 读写 `nexus.resolvers / llms`（非密字段） |
| 运行历史列表 + 回看出处 | **BFF 直连 DB** | 读 `nexus.runs / run_steps` |
| 测试新数据源能否连通 | **前端直连后端** | 由后端用凭据实际连一次 |

> 后端地址（BaseUrl）由 BFF 的 `config/BackendAPI` 端点下发，前端 `backendUrl()` 拼完整 URL 后直接请求后端（带 Bearer）。BFF **不代理**这些后端调用。

> **注册新数据源的编排（两步）**：① 用户填连接（含密码）→ 前端直连**后端 API** 将密文存入 KV，拿回 `credential_name`；② 前端再让 **BFF 直连 DB** 写一行 `nexus.resolvers`（只存非密配置 + `credential_name`）。密文全程不落 BFF/前端存储。

---

## 4. 页面规划（怎么呈现这个系统）

### 4.1 提问台（Ask Console）— 主场景 ★
- 顶部一个大输入框：像聊天一样输入业务问题。
- 回答区：先出**答案文本**，下面一排**出处卡片**（每个数字一张：业务名 = 值 · 来源库/表 · 口径 SQL）。
- 出处卡片可点开 → 抽屉展示完整口径、信任分、若多源则各来源对照。
- **执行过程面板**（提问后实时展开，见 §4.7）：四段引擎的输入/输出逐段亮起；协调器阶段用 **VueFlow** 画出 SQG，实时显示每个节点执行到哪一步。
- 通道：直连后端；同步用 `POST {BaseUrl}/v1/ask`，需要看进度用流式 `POST {BaseUrl}/v1/ask/stream`（SSE）。

### 4.2 追溯抽屉（Lineage）
- 从提问台或历史进入：把一次回答的**每个数字**摊开——来源、口径、执行耗时、（多源时）合并裁决说明。
- 通道：随 `/ask` 返回；历史场景走 BFF 读 `run_steps`。

### 4.3 运行历史（Runs）
- 列表：时间、问题、状态、耗时。点开 → 该次的问题 → SQG → 计划 → 结果 → 出处（回放）。
- 通道：**BFF 直连 DB**（`nexus.runs / run_steps`）。

### 4.4 本体管理（Ontology）
- 概念（Concept）列表 + 编辑：id / kind / 名称 / 同义词 / 语义 / 属性。
- 绑定（Binding）：概念 → 物理落点（表/列/表达式）。
- （进阶）把本体渲染成一张**语义图**（实体是节点、属性挂节点、关系是边、指标是聚合）。
- 通道：**BFF 直连 DB**（`nexus.concepts / bindings`）。

### 4.5 源管理（Resolvers 注册表）
- 列表：名称 / 类型（sql/vector/agent/action）/ 状态 / 绑定的凭据名。
- 新增向导：选类型 → 填连接（密文交后端存 KV）→ 测试连通 → 保存注册行。
- 通道：列表/停用 = **BFF 直连 DB**；密文与测试 = **后端 API**。

### 4.6 LLM 管理
- 注册多个 LLM（provider / 部署名 / 默认项）；Key 走 KV。
- 通道：注册行 = **BFF 直连 DB**（`nexus.llms`）；Key = **后端 API**。

### 4.7 执行过程可视化（VueFlow）★
提问后实时展示后端「四段引擎」的执行进度与每段输入/输出，让用户看到「问题是怎么一步步算出来的」。

**阶段时间线（顶部）**：编译器 → 优化器 → 协调器 → 生成器，四段依次点亮（灰=待执行、蓝=进行中、绿=完成、红=出错）。每段可点开看输入/输出：
- 编译器：输入 = 自然语言问题；输出 = SQG（语义查询图 JSON）。
- 优化器：输出 = 物理执行计划（每节点选中的源 + 拼好的 SQL）。
- 协调器：见下方 DAG。
- 生成器：输出 = 答案 + 出处。

**协调器 DAG（VueFlow）★**：把 SQG 画成有向图（节点 = SQG 节点，边 = 依赖 `depends_on`），随执行**实时更新每个节点状态**（待执行 / 进行中 / 完成 / 失败）；完成的节点上显示其值与来源，多波并行时能看到「哪些在跑、哪些已回填」。点节点弹出该节点的调用详情（SQL / 证据）。

**技术**：`@vue-flow/core`（+ `background` / `controls` / `minimap`）。节点按依赖分层布局（dagre 或按波次排列）；状态用颜色 + 角标。

**数据来源**：走流式 `POST {BaseUrl}/v1/ask/stream`（SSE），前端按事件逐步更新时间线与 DAG（见 §5）。历史回放则从 `nexus.runs`（SQG/plan）+ `run_steps`（各节点结果）静态重建同一张图。

> **后端配合（P1+）**：四段引擎在关键节点发出进度事件（编译完成 / 计划完成 / 某节点开始·完成 / 生成完成），由 `/ask/stream` 以 SSE 推给前端。P0 的同步 `/ask` 不带进度；此视图依赖后端上线流式进度。

---

## 5. 关键数据契约（前端视角）

- 提问：**直连后端** `POST {BaseUrl}/v1/ask` → `{ answer: string, lineage: LineageItem[] }`
  - `LineageItem = { node_id, label, value, resolver, source, detail }`
- 流式提问（带进度）：**直连后端** `POST {BaseUrl}/v1/ask/stream`（SSE, `text/event-stream`）。事件：
  - `stage` `{ stage: "compiler|optimizer|coordinator|generator", state: "running|done|error", input?, output? }`
  - `node`  `{ node_id, name, state: "pending|running|done|error", value?, source?, detail? }`（协调器逐节点）
  - `answer` `<最终 Answer>`；`error` `{ message }`
- 本体：`GET api/ontology/concepts`、`POST api/ontology/concepts`（BFF）
- 源：`GET api/resolvers`、`POST api/resolvers`（BFF，非密）；存密文 **直连后端** `POST {BaseUrl}/v1/credentials`（存 KV）
- 历史：`GET api/runs?take=50`、`GET api/runs/{run_id}`（BFF）
- 后端地址：`GET api/config/BackendAPI`（BFF 下发 BaseUrl/Version），前端 `backendUrl()` 拼完整 URL。
- 统一响应信封：`{ state, message, data }`（`API.ts` 自动解包 + 全局提示）。

---

## 6. 分阶段（对齐后端 P0/P1）

| 阶段 | 前端范围 | 依赖后端 |
|---|---|---|
| **U0**（配 P0） | 提问台 + 出处 + 运行历史 | `/ask` 已就绪；BFF 接 `nexus.runs` |
| **U1**（配 P1） | 本体管理 + 源/LLM 注册 + 编译预览 | 后端 credential/compile API |
| **U1.5** | 执行过程可视化（VueFlow DAG + 阶段 I/O，实时进度） | 后端 `/ask/stream` 流式进度 |
| **U2** | 语义图可视化、多源融合裁决展示 | 融合/多节点场景 |

---

## 7. 现状与下一步

- 已就位：`datanexus.client`（Vue 骨架 + `common/`：API/MSAL/APIService/AppConfig）；`DataNexus.Server`（默认模板）；`DataNexus.Library`（待补 `SqlService`）。
- 下一步（U0）：
  1. BFF 补 `SqlService`（连 nexus 库）+ `Sql`/`BackendAPI`/`MSAL` 配置段（appsettings）。
  2. BFF 加 `ConfigController`（下发 `config/BackendAPI`、`config/MSAL` 给前端）+ `RunsController`（直连 `nexus.runs/run_steps`）。**不需要**后端代理控制器——前端直连后端。
  3. 后端加 CORS 允许 SPA 源（`ALLOWED_ORIGINS` 已有），并按需启用 `require_auth`。
  4. 客户端 `src/bff/Config.ts`（`backendUrl` 助手）+ `src/backend/Ask.ts`（直连后端 `/ask`）+ `src/bff/Runs.ts`；做提问台页面 + 出处卡片 + 历史列表。
- 执行过程可视化（U1.5）：
  5. 后端：四段引擎加**进度事件**机制（编译/优化完成、协调器每节点开始·完成、生成完成），新增 `POST /api/v1/ask/stream`（SSE）把事件推给前端。
  6. 前端：`datanexus.client` 加依赖 `@vue-flow/core`（+ background/controls/minimap）；`src/backend/AskStream.ts` 消费 SSE；提问台加「执行过程面板」= 阶段时间线 + 协调器 VueFlow DAG（实时节点状态）。
