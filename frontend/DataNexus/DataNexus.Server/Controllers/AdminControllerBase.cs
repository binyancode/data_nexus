using DataNexus.Server.Models;
using DataNexus.Server.Services;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;

namespace DataNexus.Server.Controllers
{
    /// <summary>管理员接口公共基类。每次请求实时查询 app_user，不依赖前端状态或认证白名单缓存。</summary>
    public abstract class AdminControllerBase : ControllerBase
    {
        protected readonly SqlService Sql;

        protected AdminControllerBase(SqlService sql)
        {
            Sql = sql;
        }

        protected async Task<IActionResult?> RequireAdminAsync(CancellationToken ct = default)
        {
            var userName = User.Identity?.Name;
            if (string.IsNullOrWhiteSpace(userName))
            {
                return Unauthorized(new APIResponseModel
                {
                    State = "error",
                    Message = "Not authenticated",
                });
            }

            var value = await Sql.ExecuteScalarAsync(
                "SELECT COUNT(*) FROM nexus.app_user WHERE user_name = @userName AND is_admin = 1",
                new[] { new SqlParameter("@userName", userName) },
                ct);
            if (Convert.ToInt32(value ?? 0) == 0)
            {
                return StatusCode(StatusCodes.Status403Forbidden, new APIResponseModel
                {
                    State = "error",
                    Message = "仅管理员可访问此功能",
                });
            }

            return null;
        }
    }
}
