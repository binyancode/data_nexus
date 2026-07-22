/* Data Nexus compute engine registry — idempotent migration.
   Apply to the Data Nexus metadata database, not to a business/compute database. */

IF NOT EXISTS (
    SELECT 1
      FROM sys.tables t
      JOIN sys.schemas s ON s.schema_id = t.schema_id
     WHERE s.name = N'nexus' AND t.name = N'compute_engines'
)
BEGIN
    CREATE TABLE [nexus].[compute_engines] (
        [engine_name] nvarchar(100) NOT NULL,
        [engine_type] nvarchar(50) NOT NULL,
        [config] nvarchar(MAX) NULL,
        [credential_name] nvarchar(200) NULL,
        [runtime_user] nvarchar(128) NULL,
        [is_default] bit NOT NULL CONSTRAINT [DF_compute_engines_default] DEFAULT ((0)),
        [is_active] bit NOT NULL CONSTRAINT [DF_compute_engines_active] DEFAULT ((1)),
        [provision_state] nvarchar(32) NOT NULL CONSTRAINT [DF_compute_engines_state] DEFAULT ('ready'),
        [provision_error] nvarchar(MAX) NULL,
        [creation_time] datetime2(7) NOT NULL CONSTRAINT [DF_compute_engines_created] DEFAULT (sysutcdatetime()),
        [update_time] datetime2(7) NULL,
        CONSTRAINT [PK_compute_engines] PRIMARY KEY ([engine_name]),
        CONSTRAINT [CK_compute_engines_type] CHECK ([engine_type] IN ('duckdb', 'sql_server')),
        CONSTRAINT [CK_compute_engines_state] CHECK ([provision_state] IN (
            'provisioning', 'ready', 'provision_failed', 'deleting', 'delete_failed'
        )),
        CONSTRAINT [CK_compute_engines_default_ready] CHECK (
            [is_default] = 0 OR ([is_active] = 1 AND [provision_state] = 'ready')
        ),
        CONSTRAINT [CK_compute_engines_config_json] CHECK ([config] IS NULL OR ISJSON([config]) = 1),
        CONSTRAINT [CK_compute_engines_fields] CHECK (
            ([engine_type] = 'duckdb' AND [credential_name] IS NULL AND [runtime_user] IS NULL)
            OR
            ([engine_type] = 'sql_server' AND [credential_name] IS NOT NULL AND [runtime_user] IS NOT NULL)
        )
    );
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
     WHERE parent_object_id = OBJECT_ID(N'[nexus].[compute_engines]')
       AND name = N'CK_compute_engines_state'
)
BEGIN
    ALTER TABLE [nexus].[compute_engines] WITH CHECK
        ADD CONSTRAINT [CK_compute_engines_state]
        CHECK ([provision_state] IN (
            'provisioning', 'ready', 'provision_failed', 'deleting', 'delete_failed'
        ));
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.check_constraints
     WHERE parent_object_id = OBJECT_ID(N'[nexus].[compute_engines]')
       AND name = N'CK_compute_engines_default_ready'
)
BEGIN
    ALTER TABLE [nexus].[compute_engines] WITH CHECK
        ADD CONSTRAINT [CK_compute_engines_default_ready]
        CHECK ([is_default] = 0 OR ([is_active] = 1 AND [provision_state] = 'ready'));
END;
GO

IF COL_LENGTH(N'nexus.compute_engines', N'provision_error') IS NULL
BEGIN
    ALTER TABLE [nexus].[compute_engines]
        ADD [provision_error] nvarchar(MAX) NULL;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
     WHERE object_id = OBJECT_ID(N'[nexus].[compute_engines]')
       AND name = N'UX_compute_engines_default'
)
BEGIN
    CREATE UNIQUE INDEX [UX_compute_engines_default]
        ON [nexus].[compute_engines] ([is_default])
        WHERE [is_default] = 1 AND [is_active] = 1;
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM sys.indexes
     WHERE object_id = OBJECT_ID(N'[nexus].[compute_engines]')
       AND name = N'UX_compute_engines_runtime_user'
)
BEGIN
    CREATE UNIQUE INDEX [UX_compute_engines_runtime_user]
        ON [nexus].[compute_engines] ([credential_name], [runtime_user])
        WHERE [runtime_user] IS NOT NULL;
END;
GO

IF NOT EXISTS (SELECT 1 FROM [nexus].[compute_engines] WHERE [engine_name] = N'duckdb')
BEGIN
    INSERT INTO [nexus].[compute_engines]
        ([engine_name], [engine_type], [config], [credential_name], [runtime_user],
         [is_default], [is_active], [provision_state], [creation_time])
    VALUES
        (N'duckdb', N'duckdb', N'{}', NULL, NULL,
         CASE WHEN EXISTS (
             SELECT 1 FROM [nexus].[compute_engines]
              WHERE [is_default] = 1 AND [is_active] = 1 AND [provision_state] = N'ready'
         ) THEN 0 ELSE 1 END,
         1, N'ready', SYSUTCDATETIME());
END;
GO

IF NOT EXISTS (
    SELECT 1 FROM [nexus].[compute_engines]
        WHERE [is_default] = 1 AND [is_active] = 1 AND [provision_state] = N'ready'
)
BEGIN
    UPDATE [nexus].[compute_engines]
       SET [is_default] = 1,
           [update_time] = SYSUTCDATETIME()
     WHERE [engine_name] = (
         SELECT TOP (1) [engine_name]
           FROM [nexus].[compute_engines]
          WHERE [is_active] = 1 AND [provision_state] = N'ready'
          ORDER BY CASE WHEN [engine_name] = N'duckdb' THEN 0 ELSE 1 END,
                   [creation_time]
     );
END;
GO
