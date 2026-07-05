using System.Data;
using Microsoft.Data.SqlClient;

namespace DataNexus.Server.Services
{
    // 精简 SQL 访问：连接串取自配置 "Sql:ConnectionString"（连系统库 binyandb-data-nexus）。
    public class SqlService
    {
        private readonly string _connectionString;
        private readonly int _commandTimeout;

        public SqlService(IConfiguration config)
        {
            _connectionString = config["Sql:ConnectionString"]
                ?? throw new InvalidOperationException("Sql:ConnectionString 未配置");
            _commandTimeout = config.GetValue<int?>("Sql:CommandTimeout") ?? 30;
        }

        public async Task<DataTable> QueryAsync(string sql, SqlParameter[]? parameters = null, CancellationToken ct = default)
        {
            using var conn = new SqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            using var cmd = new SqlCommand(sql, conn) { CommandTimeout = _commandTimeout };
            if (parameters != null) cmd.Parameters.AddRange(parameters);
            using var reader = await cmd.ExecuteReaderAsync(ct);
            var table = new DataTable();
            table.Load(reader);
            return table;
        }

        public async Task<object?> ExecuteScalarAsync(string sql, SqlParameter[]? parameters = null, CancellationToken ct = default)
        {
            using var conn = new SqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            using var cmd = new SqlCommand(sql, conn) { CommandTimeout = _commandTimeout };
            if (parameters != null) cmd.Parameters.AddRange(parameters);
            return await cmd.ExecuteScalarAsync(ct);
        }

        public async Task<int> ExecuteNonQueryAsync(string sql, SqlParameter[]? parameters = null, CancellationToken ct = default)
        {
            using var conn = new SqlConnection(_connectionString);
            await conn.OpenAsync(ct);
            using var cmd = new SqlCommand(sql, conn) { CommandTimeout = _commandTimeout };
            if (parameters != null) cmd.Parameters.AddRange(parameters);
            return await cmd.ExecuteNonQueryAsync(ct);
        }
    }
}
