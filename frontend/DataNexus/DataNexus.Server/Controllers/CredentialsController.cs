using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    // 凭据「基础列表」：BFF 直连 DB 读 nexus.app_credential 的非敏感元数据。
    // 注意：任何密文相关操作（详情回填/新建/更新/删除）都不在此处，走 Python /api/v1/credentials（持有 Key Vault 访问）。
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class CredentialsController : ControllerBase
    {
        private readonly SqlService _sql;

        public CredentialsController(SqlService sql)
        {
            _sql = sql;
        }

        // 凭据列表（仅非敏感元数据；绝不含 secret_name / 密文）
        [HttpGet]
        public async Task<APIResponseModel> GetCredentials()
        {
            var t = await _sql.QueryAsync(
                @"SELECT credential_name, credential_type, description, is_active, creation_time, update_time
                  FROM nexus.app_credential
                  WHERE is_active = 1
                  ORDER BY credential_name");

            var items = t.AsEnumerable().Select(r => new
            {
                credential_name = r.Field<string?>("credential_name"),
                credential_type = r.Field<string?>("credential_type"),
                description = r.Field<string?>("description"),
                is_active = !r.IsNull("is_active") && r.Field<bool>("is_active"),
                creation_time = r.Field<DateTime?>("creation_time"),
                update_time = r.Field<DateTime?>("update_time"),
            }).ToList();

            return new APIResponseModel { Data = items };
        }
    }
}
