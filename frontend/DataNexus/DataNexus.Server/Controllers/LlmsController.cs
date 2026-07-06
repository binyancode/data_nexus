using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    // LLM（规划大脑）管理：BFF 直连 nexus.llms。无密文（密钥在其引用的 credential 里，由 Python 管理）。
    // 保存后需调用 Python /api/v1/resolvers/reload 让内存注册表即时生效。
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class LlmsController : ControllerBase
    {
        private readonly SqlService _sql;

        public LlmsController(SqlService sql)
        {
            _sql = sql;
        }

        // 列表（含提问界面下拉需要的 is_default）
        [HttpGet]
        public async Task<APIResponseModel> GetLlms()
        {
            var t = await _sql.QueryAsync(
                @"SELECT llm_name, provider, config, credential_name, is_default, is_active, update_time
                  FROM nexus.llms
                  WHERE is_active = 1
                  ORDER BY is_default DESC, llm_name");

            var items = t.AsEnumerable().Select(r => new
            {
                llm_name = r.Field<string?>("llm_name"),
                provider = r.Field<string?>("provider"),
                config = r.Field<string?>("config"),
                credential_name = r.Field<string?>("credential_name"),
                is_default = !r.IsNull("is_default") && r.Field<bool>("is_default"),
                is_active = !r.IsNull("is_active") && r.Field<bool>("is_active"),
                update_time = r.Field<DateTime?>("update_time"),
            }).ToList();

            return new APIResponseModel { Data = items };
        }

        public class LlmDto
        {
            public string? llm_name { get; set; }
            public string? provider { get; set; }
            public string? config { get; set; }
            public string? credential_name { get; set; }
            public bool is_default { get; set; }
        }

        [HttpPost]
        public async Task<APIResponseModel> CreateLlm([FromBody] LlmDto dto)
        {
            if (string.IsNullOrWhiteSpace(dto.llm_name) || string.IsNullOrWhiteSpace(dto.provider))
                return new APIResponseModel { State = "error", Message = "llm_name / provider 必填" };

            if (dto.is_default)
                await ClearDefault();

            await _sql.ExecuteNonQueryAsync(
                @"INSERT INTO nexus.llms (llm_name, provider, config, credential_name, is_default, is_active, creation_time)
                  VALUES (@name, @provider, @config, @cred, @def, 1, SYSUTCDATETIME())",
                new[]
                {
                    new SqlParameter("@name", dto.llm_name),
                    new SqlParameter("@provider", dto.provider),
                    new SqlParameter("@config", (object?)(dto.config ?? "{}") ?? DBNull.Value),
                    new SqlParameter("@cred", (object?)dto.credential_name ?? DBNull.Value),
                    new SqlParameter("@def", dto.is_default),
                });

            await EnsureAnyDefault();
            return new APIResponseModel { Data = new { dto.llm_name } };
        }

        [HttpPut("{name}")]
        public async Task<APIResponseModel> UpdateLlm(string name, [FromBody] LlmDto dto)
        {
            if (dto.is_default)
                await ClearDefault();

            await _sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.llms
                  SET provider = @provider, config = @config, credential_name = @cred,
                      is_default = @def, update_time = SYSUTCDATETIME()
                  WHERE llm_name = @name",
                new[]
                {
                    new SqlParameter("@name", name),
                    new SqlParameter("@provider", (object?)dto.provider ?? DBNull.Value),
                    new SqlParameter("@config", (object?)(dto.config ?? "{}") ?? DBNull.Value),
                    new SqlParameter("@cred", (object?)dto.credential_name ?? DBNull.Value),
                    new SqlParameter("@def", dto.is_default),
                });

            await EnsureAnyDefault();
            return new APIResponseModel { Data = new { llm_name = name } };
        }

        [HttpDelete("{name}")]
        public async Task<APIResponseModel> DeleteLlm(string name)
        {
            await _sql.ExecuteNonQueryAsync(
                "UPDATE nexus.llms SET is_active = 0, is_default = 0, update_time = SYSUTCDATETIME() WHERE llm_name = @name",
                new[] { new SqlParameter("@name", name) });

            await EnsureAnyDefault();
            return new APIResponseModel { Data = new { llm_name = name } };
        }

        // 设为默认（其余清零）
        [HttpPut("{name}/default")]
        public async Task<APIResponseModel> SetDefault(string name)
        {
            await ClearDefault();
            await _sql.ExecuteNonQueryAsync(
                "UPDATE nexus.llms SET is_default = 1, update_time = SYSUTCDATETIME() WHERE llm_name = @name AND is_active = 1",
                new[] { new SqlParameter("@name", name) });
            return new APIResponseModel { Data = new { llm_name = name } };
        }

        private Task<int> ClearDefault() =>
            _sql.ExecuteNonQueryAsync("UPDATE nexus.llms SET is_default = 0 WHERE is_default = 1");

        // 若当前没有任何默认，则把最早的一个 active 设为默认，避免"无默认"
        private async Task EnsureAnyDefault()
        {
            var t = await _sql.QueryAsync("SELECT COUNT(*) AS c FROM nexus.llms WHERE is_default = 1 AND is_active = 1");
            var has = t.Rows.Count > 0 && Convert.ToInt32(t.Rows[0]["c"]) > 0;
            if (has) return;
            await _sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.llms SET is_default = 1
                  WHERE llm_name = (SELECT TOP 1 llm_name FROM nexus.llms WHERE is_active = 1 ORDER BY creation_time)");
        }
    }
}
