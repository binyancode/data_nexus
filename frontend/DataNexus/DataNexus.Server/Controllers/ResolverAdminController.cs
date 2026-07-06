using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    // 源（Resolver）管理：BFF 直连 nexus.resolvers。每个源引用一个 credential（sql→sql、agent→azure_openai、action→无）。
    // 无密文（密钥在其引用的 credential 里，由 Python 管理）。保存后需调用 Python /api/v1/resolvers/reload 生效。
    [Authorize]
    [ApiController]
    [Route("api/resolver-admin")]
    public class ResolverAdminController : ControllerBase
    {
        private readonly SqlService _sql;

        public ResolverAdminController(SqlService sql)
        {
            _sql = sql;
        }

        [HttpGet]
        public async Task<APIResponseModel> GetResolvers()
        {
            var t = await _sql.QueryAsync(
                @"SELECT resolver_name, resolver_type, config, credential_name, is_active, update_time
                  FROM nexus.resolvers
                  ORDER BY resolver_name");

            var items = t.AsEnumerable().Select(r => new
            {
                resolver_name = r.Field<string?>("resolver_name"),
                resolver_type = r.Field<string?>("resolver_type"),
                config = r.Field<string?>("config"),
                credential_name = r.Field<string?>("credential_name"),
                is_active = !r.IsNull("is_active") && r.Field<bool>("is_active"),
                update_time = r.Field<DateTime?>("update_time"),
            }).ToList();

            return new APIResponseModel { Data = items };
        }

        public class ResolverDto
        {
            public string? resolver_name { get; set; }
            public string? resolver_type { get; set; }
            public string? config { get; set; }
            public string? credential_name { get; set; }
            public bool is_active { get; set; } = true;
        }

        [HttpPost]
        public async Task<APIResponseModel> CreateResolver([FromBody] ResolverDto dto)
        {
            if (string.IsNullOrWhiteSpace(dto.resolver_name) || string.IsNullOrWhiteSpace(dto.resolver_type))
                return new APIResponseModel { State = "error", Message = "resolver_name / resolver_type 必填" };

            await _sql.ExecuteNonQueryAsync(
                @"INSERT INTO nexus.resolvers (resolver_name, resolver_type, config, credential_name, is_active, creation_time)
                  VALUES (@name, @type, @config, @cred, @active, SYSUTCDATETIME())",
                new[]
                {
                    new SqlParameter("@name", dto.resolver_name),
                    new SqlParameter("@type", dto.resolver_type),
                    new SqlParameter("@config", (object?)(dto.config ?? "{}") ?? DBNull.Value),
                    new SqlParameter("@cred", (object?)dto.credential_name ?? DBNull.Value),
                    new SqlParameter("@active", dto.is_active),
                });

            return new APIResponseModel { Data = new { dto.resolver_name } };
        }

        [HttpPut("{name}")]
        public async Task<APIResponseModel> UpdateResolver(string name, [FromBody] ResolverDto dto)
        {
            await _sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.resolvers
                  SET resolver_type = @type, config = @config, credential_name = @cred,
                      is_active = @active, update_time = SYSUTCDATETIME()
                  WHERE resolver_name = @name",
                new[]
                {
                    new SqlParameter("@name", name),
                    new SqlParameter("@type", (object?)dto.resolver_type ?? DBNull.Value),
                    new SqlParameter("@config", (object?)(dto.config ?? "{}") ?? DBNull.Value),
                    new SqlParameter("@cred", (object?)dto.credential_name ?? DBNull.Value),
                    new SqlParameter("@active", dto.is_active),
                });

            return new APIResponseModel { Data = new { resolver_name = name } };
        }

        [HttpDelete("{name}")]
        public async Task<APIResponseModel> DeleteResolver(string name)
        {
            await _sql.ExecuteNonQueryAsync(
                "DELETE FROM nexus.resolvers WHERE resolver_name = @name",
                new[] { new SqlParameter("@name", name) });

            return new APIResponseModel { Data = new { resolver_name = name } };
        }
    }
}
