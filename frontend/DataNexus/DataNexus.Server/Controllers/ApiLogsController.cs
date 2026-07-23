using DataNexus.Server.Models;
using DataNexus.Server.Services;
using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using System.Text.Json;
using System.Text.Json.Nodes;

namespace DataNexus.Server.Controllers
{
    [Authorize]
    [ApiController]
    [Route("api/api-logs")]
    public class ApiLogsController : AdminControllerBase
    {
        public ApiLogsController(SqlService sql) : base(sql) { }

        [HttpGet]
        public async Task<IActionResult> GetLogs(
            [FromQuery] int page = 1,
            [FromQuery] int pageSize = 50,
            [FromQuery] string? state = null,
            [FromQuery] string? source = null,
            [FromQuery] string? user = null,
            [FromQuery] string? function = null,
            [FromQuery] string? keyword = null,
            [FromQuery] DateTime? from = null,
            [FromQuery] DateTime? to = null,
            CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            page = Math.Max(1, page);
            pageSize = Math.Clamp(pageSize, 10, 100);
            var conditions = new List<string> { "1 = 1" };
            var parameters = new List<SqlParameter>();

            AddExactFilter(conditions, parameters, "[state]", "@state", state);
            AddExactFilter(conditions, parameters, "[source]", "@source", source);
            AddLikeFilter(conditions, parameters, "user_name", "@user", user);
            AddLikeFilter(conditions, parameters, "function_name", "@function", function);
            if (!string.IsNullOrWhiteSpace(keyword))
            {
                conditions.Add(@"(function_name LIKE @keyword OR [path] LIKE @keyword
                                 OR user_name LIKE @keyword OR [message] LIKE @keyword)");
                parameters.Add(new SqlParameter("@keyword", $"%{keyword.Trim()}%"));
            }
            if (from.HasValue)
            {
                conditions.Add("request_time >= @from");
                parameters.Add(new SqlParameter("@from", from.Value));
            }
            if (to.HasValue)
            {
                conditions.Add("request_time < @to");
                parameters.Add(new SqlParameter("@to", to.Value));
            }

            var where = string.Join(" AND ", conditions);
            var totalObj = await Sql.ExecuteScalarAsync(
                $"SELECT COUNT_BIG(*) FROM nexus.api_log WHERE {where}",
                parameters.ToArray(), ct);
            var total = Convert.ToInt64(totalObj ?? 0);

            var listParameters = parameters.Select(CloneParameter).ToList();
            listParameters.Add(new SqlParameter("@skip", (page - 1) * pageSize));
            listParameters.Add(new SqlParameter("@take", pageSize));
            var table = await Sql.QueryAsync(
                $@"SELECT id, function_name, [method], [path], user_name, [state], cost_ms,
                           request_time, response_time, [source],
                           CASE WHEN [message] IS NULL OR [message] = '' THEN CAST(0 AS bit)
                                ELSE CAST(1 AS bit) END AS has_message
                      FROM nexus.api_log
                     WHERE {where}
                     ORDER BY id DESC
                    OFFSET @skip ROWS FETCH NEXT @take ROWS ONLY",
                listParameters.ToArray(), ct);

            var items = table.AsEnumerable().Select(row => new
            {
                id = row.Field<long>("id"),
                function_name = row.Field<string?>("function_name"),
                method = row.Field<string?>("method"),
                path = row.Field<string?>("path"),
                user_name = row.Field<string?>("user_name"),
                state = row.Field<string?>("state"),
                cost_ms = row.IsNull("cost_ms") ? (int?)null : row.Field<int>("cost_ms"),
                request_time = row.Field<DateTime?>("request_time"),
                response_time = row.Field<DateTime?>("response_time"),
                source = row.Field<string?>("source"),
                has_message = !row.IsNull("has_message") && row.Field<bool>("has_message"),
            }).ToList();

            return Ok(new APIResponseModel
            {
                Data = new { items, total, page, page_size = pageSize },
            });
        }

        [HttpGet("{id:long}")]
        public async Task<IActionResult> GetLog(long id, CancellationToken ct = default)
        {
            var denied = await RequireAdminAsync(ct);
            if (denied != null) return denied;

            var table = await Sql.QueryAsync(
                @"SELECT id, function_name, [method], [path], user_name, payload, response,
                         [state], cost_ms, [message], request_time, response_time, [source]
                    FROM nexus.api_log WHERE id = @id",
                new[] { new SqlParameter("@id", id) }, ct);
            var row = table.AsEnumerable().FirstOrDefault();
            if (row == null)
            {
                return NotFound(new APIResponseModel
                {
                    State = "error",
                    Message = "日志不存在",
                });
            }

            return Ok(new APIResponseModel
            {
                Data = new
                {
                    id = row.Field<long>("id"),
                    function_name = row.Field<string?>("function_name"),
                    method = row.Field<string?>("method"),
                    path = row.Field<string?>("path"),
                    user_name = row.Field<string?>("user_name"),
                    payload = RedactJson(row.Field<string?>("payload")),
                    response = RedactJson(row.Field<string?>("response")),
                    state = row.Field<string?>("state"),
                    cost_ms = row.IsNull("cost_ms") ? (int?)null : row.Field<int>("cost_ms"),
                    message = row.Field<string?>("message"),
                    request_time = row.Field<DateTime?>("request_time"),
                    response_time = row.Field<DateTime?>("response_time"),
                    source = row.Field<string?>("source"),
                },
            });
        }

        private static void AddExactFilter(
            ICollection<string> conditions,
            ICollection<SqlParameter> parameters,
            string column,
            string parameter,
            string? value)
        {
            if (string.IsNullOrWhiteSpace(value)) return;
            conditions.Add($"{column} = {parameter}");
            parameters.Add(new SqlParameter(parameter, value.Trim()));
        }

        private static void AddLikeFilter(
            ICollection<string> conditions,
            ICollection<SqlParameter> parameters,
            string column,
            string parameter,
            string? value)
        {
            if (string.IsNullOrWhiteSpace(value)) return;
            conditions.Add($"{column} LIKE {parameter}");
            parameters.Add(new SqlParameter(parameter, $"%{value.Trim()}%"));
        }

        private static SqlParameter CloneParameter(SqlParameter source)
        {
            return new SqlParameter(source.ParameterName, source.Value ?? DBNull.Value);
        }

        private static readonly HashSet<string> SensitiveKeys = new(
            new[]
            {
                "password", "pwd", "key", "api_key", "apikey", "client_secret",
                "secret", "token", "access_token", "refresh_token", "authorization",
            },
            StringComparer.OrdinalIgnoreCase);

        private static string? RedactJson(string? value)
        {
            if (string.IsNullOrWhiteSpace(value)) return value;
            try
            {
                var node = JsonNode.Parse(value);
                RedactNode(node);
                return node?.ToJsonString(new JsonSerializerOptions { WriteIndented = true });
            }
            catch (JsonException)
            {
                return value;
            }
        }

        private static void RedactNode(JsonNode? node)
        {
            if (node is JsonObject obj)
            {
                foreach (var key in obj.Select(item => item.Key).ToList())
                {
                    if (SensitiveKeys.Contains(key)) obj[key] = "***";
                    else RedactNode(obj[key]);
                }
            }
            else if (node is JsonArray array)
            {
                foreach (var item in array) RedactNode(item);
            }
        }
    }
}
