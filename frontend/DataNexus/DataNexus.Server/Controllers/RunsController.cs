using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    // 运行记录：BFF 直连 DB 读 nexus.run / run_stage / run_node（前端画执行过程 + 历史回放）。
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class RunsController : ControllerBase
    {
        private readonly SqlService _sql;

        public RunsController(SqlService sql)
        {
            _sql = sql;
        }

        // 运行历史列表
        [HttpGet]
        public async Task<APIResponseModel> GetRuns([FromQuery] int take = 50)
        {
            var t = await _sql.QueryAsync(
                @"SELECT TOP (@take) run_id, question, as_user, context, [state], cost_ms, created_at
                  FROM nexus.run ORDER BY created_at DESC",
                new[] { new SqlParameter("@take", take) });

            var items = t.AsEnumerable().Select(r => new
            {
                run_id = r.Field<string>("run_id"),
                question = r.Field<string?>("question"),
                as_user = r.Field<string?>("as_user"),
                context = r.Field<string?>("context"),
                state = r.Field<string?>("state"),
                cost_ms = r.IsNull("cost_ms") ? 0 : r.Field<int>("cost_ms"),
                created_at = r.Field<DateTime?>("created_at"),
            }).ToList();

            return new APIResponseModel { Data = items };
        }

        // 单次运行详情：run + 四段 stage + 各 node（前端轮询此接口刷新执行进度）
        [HttpGet("{runId}")]
        public async Task<APIResponseModel> GetRun(string runId)
        {
            var p = new[] { new SqlParameter("@id", runId) };

            var runT = await _sql.QueryAsync(
                @"SELECT run_id, question, as_user, context, [state], answer, cost_ms, created_at, updated_at
                  FROM nexus.run WHERE run_id = @id", p);
            var rr = runT.AsEnumerable().FirstOrDefault();
            if (rr == null)
                return new APIResponseModel { State = "error", Message = "Run not found" };

            var run = new
            {
                run_id = rr.Field<string>("run_id"),
                question = rr.Field<string?>("question"),
                as_user = rr.Field<string?>("as_user"),
                context = rr.Field<string?>("context"),
                state = rr.Field<string?>("state"),
                answer = rr.Field<string?>("answer"),
                cost_ms = rr.IsNull("cost_ms") ? 0 : rr.Field<int>("cost_ms"),
                created_at = rr.Field<DateTime?>("created_at"),
                updated_at = rr.Field<DateTime?>("updated_at"),
            };

            var stageT = await _sql.QueryAsync(
                @"SELECT stage, seq, [state], [input], [output], error, cost_ms, started_at, ended_at
                  FROM nexus.run_stage WHERE run_id = @id ORDER BY seq",
                new[] { new SqlParameter("@id", runId) });
            var stages = stageT.AsEnumerable().Select(r => new
            {
                stage = r.Field<string?>("stage"),
                seq = r.IsNull("seq") ? 0 : Convert.ToInt32(r["seq"]),
                state = r.Field<string?>("state"),
                input = r.Field<string?>("input"),
                output = r.Field<string?>("output"),
                error = r.Field<string?>("error"),
                cost_ms = r.IsNull("cost_ms") ? (int?)null : r.Field<int>("cost_ms"),
                started_at = r.Field<DateTime?>("started_at"),
                ended_at = r.Field<DateTime?>("ended_at"),
            }).ToList();

            var nodeT = await _sql.QueryAsync(
                @"SELECT node_id, [state], resolver, [call], [output], [value], [source], trust, error, cost_ms, started_at, ended_at
                  FROM nexus.run_node WHERE run_id = @id",
                new[] { new SqlParameter("@id", runId) });
            var nodes = nodeT.AsEnumerable().Select(r => new
            {
                node_id = r.Field<string?>("node_id"),
                state = r.Field<string?>("state"),
                resolver = r.Field<string?>("resolver"),
                call = r.Field<string?>("call"),
                output = r.Field<string?>("output"),
                value = r.Field<string?>("value"),
                source = r.Field<string?>("source"),
                trust = r.IsNull("trust") ? (double?)null : r.Field<double>("trust"),
                error = r.Field<string?>("error"),
                cost_ms = r.IsNull("cost_ms") ? (int?)null : r.Field<int>("cost_ms"),
                started_at = r.Field<DateTime?>("started_at"),
                ended_at = r.Field<DateTime?>("ended_at"),
            }).ToList();

            return new APIResponseModel { Data = new { run, stages, nodes } };
        }
    }
}
