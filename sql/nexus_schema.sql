/* =============================================================================
 * Data Nexus — 数据库结构导出（schema: nexus）
 * Source : binyansql-ea-01.database.windows.net / binyandb-data-nexus (Azure SQL)
 * Scope  : nexus 架构下全部表（列 / 类型 / 可空 / 默认值 / 主键）
 * Notes  : 无二级索引、无外键（表间关系由应用层维护，不落 DB FK）。
 *          主键名为 SQL Server 自动生成的系统名，忠实导出。
 * ========================================================================== */

IF NOT EXISTS (SELECT 1 FROM sys.schemas WHERE name = N'nexus')
    EXEC('CREATE SCHEMA [nexus]');
GO

-- ── API 调用日志 ──────────────────────────────────────────────────────────
CREATE TABLE [nexus].[api_log] (
    [id] bigint IDENTITY(1,1) NOT NULL,
    [function_name] nvarchar(200) NULL,
    [method] nvarchar(16) NULL,
    [path] nvarchar(400) NULL,
    [user_name] nvarchar(200) NULL,
    [payload] nvarchar(MAX) NULL,
    [response] nvarchar(MAX) NULL,
    [state] nvarchar(32) NULL,
    [cost_ms] int NULL,
    [message] nvarchar(MAX) NULL,
    [request_time] datetime2(7) NULL,
    [response_time] datetime2(7) NULL,
    [source] nvarchar(50) NULL,
    CONSTRAINT [PK__api_log__3213E83F087B9AC5] PRIMARY KEY ([id])
);
GO

-- ── 应用凭据（密文名指向 Key Vault）───────────────────────────────────────
CREATE TABLE [nexus].[app_credential] (
    [credential_name] nvarchar(200) NOT NULL,
    [credential_type] nvarchar(64) NOT NULL,
    [secret_name] nvarchar(200) NOT NULL,
    [description] nvarchar(500) NULL,
    [is_active] bit NOT NULL DEFAULT ((1)),
    [creation_time] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [update_time] datetime2(7) NULL,
    CONSTRAINT [PK__app_cred__AE195F60FB92212D] PRIMARY KEY ([credential_name])
);
GO

-- ── 应用用户 ──────────────────────────────────────────────────────────────
CREATE TABLE [nexus].[app_user] (
    [id] bigint IDENTITY(1,1) NOT NULL,
    [user_name] nvarchar(200) NOT NULL,
    [display_name] nvarchar(200) NULL,
    [is_admin] bit NOT NULL DEFAULT ((0)),
    [created_at] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    CONSTRAINT [PK__app_user__3213E83F47ECBFCA] PRIMARY KEY ([id])
);
GO

-- ── 规划用 LLM 注册表 ─────────────────────────────────────────────────────
CREATE TABLE [nexus].[llms] (
    [llm_name] nvarchar(100) NOT NULL,
    [provider] nvarchar(50) NOT NULL,
    [config] nvarchar(MAX) NULL,
    [credential_name] nvarchar(200) NULL,
    [is_default] bit NOT NULL DEFAULT ((0)),
    [is_active] bit NOT NULL DEFAULT ((1)),
    [creation_time] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [update_time] datetime2(7) NULL,
    CONSTRAINT [PK__llms__0EB9B5C11A93C518] PRIMARY KEY ([llm_name])
);
GO

-- ── 本体（一行一份，graph 为整块 JSON）────────────────────────────────────
CREATE TABLE [nexus].[ontology] (
    [ontology_id] nvarchar(64) NOT NULL,
    [name] nvarchar(200) NOT NULL,
    [description] nvarchar(MAX) NULL,
    [owner] nvarchar(200) NOT NULL,
    [visibility] nvarchar(16) NOT NULL DEFAULT ('private'),
    [state] nvarchar(16) NOT NULL DEFAULT ('draft'),
    [graph] nvarchar(MAX) NOT NULL,
    [created_at] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [updated_at] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    CONSTRAINT [PK__ontology__115D49A15BE620FB] PRIMARY KEY ([ontology_id])
);
GO

-- ── 本体共享授权（shared 时的可见用户）───────────────────────────────────
CREATE TABLE [nexus].[ontology_grant] (
    [ontology_id] nvarchar(64) NOT NULL,
    [user_name] nvarchar(200) NOT NULL,
    CONSTRAINT [PK_onto_grant] PRIMARY KEY ([ontology_id], [user_name])
);
GO

-- ── Resolver 注册表（数据源 / 智能体 / 动作）──────────────────────────────
CREATE TABLE [nexus].[resolvers] (
    [resolver_name] nvarchar(100) NOT NULL,
    [resolver_type] nvarchar(50) NOT NULL,
    [config] nvarchar(MAX) NULL,
    [credential_name] nvarchar(200) NULL,
    [is_active] bit NOT NULL DEFAULT ((1)),
    [creation_time] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [update_time] datetime2(7) NULL,
    CONSTRAINT [PK__resolver__A31C66D4B92E7B2E] PRIMARY KEY ([resolver_name])
);
GO

-- ── 一次运行（提问 → 答案）────────────────────────────────────────────────
CREATE TABLE [nexus].[run] (
    [run_id] nvarchar(64) NOT NULL,
    [question] nvarchar(MAX) NULL,
    [as_user] nvarchar(200) NULL,
    [state] nvarchar(16) NOT NULL DEFAULT ('running'),
    [answer] nvarchar(MAX) NULL,
    [cost_ms] int NOT NULL DEFAULT ((0)),
    [created_at] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [updated_at] datetime2(7) NOT NULL DEFAULT (sysutcdatetime()),
    [context] nvarchar(MAX) NULL,
    CONSTRAINT [PK__run__7D3D901BA8B65B76] PRIMARY KEY ([run_id])
);
GO

-- ── 运行内的物理执行节点（协调器逐节点落盘）──────────────────────────────
CREATE TABLE [nexus].[run_node] (
    [id] bigint IDENTITY(1,1) NOT NULL,
    [run_id] nvarchar(64) NOT NULL,
    [node_id] nvarchar(64) NOT NULL,
    [state] nvarchar(16) NOT NULL DEFAULT ('pending'),
    [resolver] nvarchar(100) NULL,
    [call] nvarchar(MAX) NULL,
    [output] nvarchar(MAX) NULL,
    [value] nvarchar(200) NULL,
    [source] nvarchar(200) NULL,
    [trust] float NULL,
    [error] nvarchar(MAX) NULL,
    [started_at] datetime2(7) NULL,
    [ended_at] datetime2(7) NULL,
    [cost_ms] int NULL,
    [logs] nvarchar(MAX) NULL,
    CONSTRAINT [PK__run_node__3213E83F8EB63A87] PRIMARY KEY ([id])
);
GO

-- ── 运行的五段引擎阶段（初始化器/编译器/优化器/协调器/生成器）─────────────
CREATE TABLE [nexus].[run_stage] (
    [id] bigint IDENTITY(1,1) NOT NULL,
    [run_id] nvarchar(64) NOT NULL,
    [stage] nvarchar(20) NOT NULL,
    [seq] tinyint NOT NULL,
    [state] nvarchar(16) NOT NULL DEFAULT ('pending'),
    [input] nvarchar(MAX) NULL,
    [output] nvarchar(MAX) NULL,
    [error] nvarchar(MAX) NULL,
    [started_at] datetime2(7) NULL,
    [ended_at] datetime2(7) NULL,
    [cost_ms] int NULL,
    [logs] nvarchar(MAX) NULL,
    CONSTRAINT [PK__run_stag__3213E83F361CA02C] PRIMARY KEY ([id])
);
GO
