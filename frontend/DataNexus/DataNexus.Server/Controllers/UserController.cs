using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class UserController : ControllerBase
    {
        private readonly SqlService _sql;

        public UserController(SqlService sql)
        {
            _sql = sql;
        }

        // 当前登录用户（前端 authState 据此判断 is_admin / 显示名）。
        [HttpGet("me")]
        public async Task<APIResponseModel> GetMe()
        {
            var userName = User.Identity?.Name;
            if (string.IsNullOrEmpty(userName))
                return new APIResponseModel { State = "error", Message = "Not authenticated" };

            var table = await _sql.QueryAsync(
                "SELECT user_name, display_name, is_admin FROM nexus.app_user WHERE user_name = @userName",
                new[] { new SqlParameter("@userName", userName) });

            var row = table.AsEnumerable().FirstOrDefault();
            return new APIResponseModel
            {
                Data = new
                {
                    user_name = userName,
                    display_name = row?.Field<string?>("display_name"),
                    is_admin = row != null && !row.IsNull("is_admin") && row.Field<bool>("is_admin"),
                },
            };
        }
    }
}
