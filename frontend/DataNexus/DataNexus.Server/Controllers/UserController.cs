using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using Microsoft.Extensions.Caching.Memory;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class UserController : AdminControllerBase
    {
        private readonly IMemoryCache _cache;

        public UserController(SqlService sql, IMemoryCache cache) : base(sql)
        {
            _cache = cache;
        }

        // 当前登录用户（前端 authState 据此判断 is_admin / 显示名）。
        [HttpGet("me")]
        public async Task<APIResponseModel> GetMe()
        {
            var userName = User.Identity?.Name;
            if (string.IsNullOrEmpty(userName))
                return new APIResponseModel { State = "error", Message = "Not authenticated" };

            var table = await Sql.QueryAsync(
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

        [HttpGet]
        public async Task<IActionResult> GetUsers(CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            var table = await Sql.QueryAsync(
                @"SELECT id, user_name, display_name, is_admin, created_at
                    FROM nexus.app_user
                   ORDER BY is_admin DESC, user_name",
                ct: ct);
            var users = table.AsEnumerable().Select(row => new
            {
                id = row.Field<long>("id"),
                user_name = row.Field<string>("user_name"),
                display_name = row.Field<string?>("display_name"),
                is_admin = !row.IsNull("is_admin") && row.Field<bool>("is_admin"),
                created_at = row.Field<DateTime?>("created_at"),
            }).ToList();
            return Ok(new APIResponseModel { Data = users });
        }

        public sealed class UserDto
        {
            public string? user_name { get; set; }
            public string? display_name { get; set; }
            public bool is_admin { get; set; }
        }

        [HttpPost]
        public async Task<IActionResult> CreateUser(
            [FromBody] UserDto dto,
            CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            var validation = Validate(dto);
            if (validation != null) return BadRequest(validation);
            var userName = dto.user_name!.Trim();
            var displayName = NormalizeDisplayName(dto.display_name);

            var table = await Sql.QueryAsync(
                @"SET NOCOUNT ON;
                  SET XACT_ABORT ON;
                  BEGIN TRANSACTION;
                  IF EXISTS (
                      SELECT 1 FROM nexus.app_user WITH (UPDLOCK, HOLDLOCK)
                       WHERE user_name = @userName
                  )
                  BEGIN
                      COMMIT TRANSACTION;
                      SELECT CAST(0 AS bit) AS created, CAST(NULL AS bigint) AS id;
                      RETURN;
                  END;

                  INSERT INTO nexus.app_user (user_name, display_name, is_admin, created_at)
                  VALUES (@userName, @displayName, @isAdmin, SYSUTCDATETIME());
                  DECLARE @id bigint = SCOPE_IDENTITY();
                  COMMIT TRANSACTION;
                  SELECT CAST(1 AS bit) AS created, @id AS id;",
                UserParameters(userName, displayName, dto.is_admin), ct);
            var row = table.AsEnumerable().First();
            if (!row.Field<bool>("created"))
            {
                return Conflict(new APIResponseModel
                {
                    State = "error",
                    Message = $"用户已存在：{userName}",
                });
            }

            _cache.Remove(AuthCacheKey(userName));
            return Ok(new APIResponseModel
            {
                Data = new { id = row.Field<long>("id"), user_name = userName },
            });
        }

        [HttpPut("{id:long}")]
        public async Task<IActionResult> UpdateUser(
            long id,
            [FromBody] UserDto dto,
            CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            var validation = Validate(dto);
            if (validation != null) return BadRequest(validation);
            var userName = dto.user_name!.Trim();
            var displayName = NormalizeDisplayName(dto.display_name);

            var existing = await Sql.QueryAsync(
                "SELECT user_name FROM nexus.app_user WHERE id = @id",
                new[] { new SqlParameter("@id", id) }, ct);
            var existingRow = existing.AsEnumerable().FirstOrDefault();
            if (existingRow == null)
            {
                return NotFound(new APIResponseModel { State = "error", Message = "用户不存在" });
            }
            var oldUserName = existingRow.Field<string>("user_name")
                ?? throw new InvalidOperationException("app_user.user_name cannot be null");
            if (!string.Equals(oldUserName, userName, StringComparison.OrdinalIgnoreCase))
            {
                return BadRequest(new APIResponseModel
                {
                    State = "error",
                    Message = "Azure AD 登录账号不可修改；请删除后重新新增用户",
                });
            }

            await Sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.app_user
                     SET display_name = @displayName,
                         is_admin = @isAdmin
                   WHERE id = @id",
                new[]
                {
                    new SqlParameter("@displayName", (object?)displayName ?? DBNull.Value),
                    new SqlParameter("@isAdmin", dto.is_admin),
                    new SqlParameter("@id", id),
                }, ct);

            _cache.Remove(AuthCacheKey(oldUserName));
            return Ok(new APIResponseModel { Data = new { id, user_name = oldUserName } });
        }

        [HttpDelete("{id:long}")]
        public async Task<IActionResult> DeleteUser(long id, CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            var table = await Sql.QueryAsync(
                @"DELETE FROM nexus.app_user
                  OUTPUT DELETED.user_name
                   WHERE id = @id",
                new[] { new SqlParameter("@id", id) }, ct);
            var row = table.AsEnumerable().FirstOrDefault();
            if (row == null)
            {
                return NotFound(new APIResponseModel { State = "error", Message = "用户不存在" });
            }
            var userName = row.Field<string>("user_name")
                ?? throw new InvalidOperationException("app_user.user_name cannot be null");
            _cache.Remove(AuthCacheKey(userName));
            return Ok(new APIResponseModel { Data = new { id, user_name = userName } });
        }

        private static APIResponseModel? Validate(UserDto dto)
        {
            var userName = dto.user_name?.Trim();
            if (string.IsNullOrWhiteSpace(userName))
                return new APIResponseModel { State = "error", Message = "user_name 必填" };
            if (userName.Length > 200)
                return new APIResponseModel { State = "error", Message = "user_name 最长 200 个字符" };
            if ((dto.display_name?.Length ?? 0) > 200)
                return new APIResponseModel { State = "error", Message = "display_name 最长 200 个字符" };
            return null;
        }

        private static string? NormalizeDisplayName(string? value)
        {
            var normalized = value?.Trim();
            return string.IsNullOrEmpty(normalized) ? null : normalized;
        }

        private static string AuthCacheKey(string userName)
        {
            return $"AuthUser:{userName.Trim().ToLowerInvariant()}";
        }

        private static SqlParameter[] UserParameters(
            string userName,
            string? displayName,
            bool isAdmin)
        {
            return new[]
            {
                new SqlParameter("@userName", userName),
                new SqlParameter("@displayName", (object?)displayName ?? DBNull.Value),
                new SqlParameter("@isAdmin", isAdmin),
            };
        }
    }
}
