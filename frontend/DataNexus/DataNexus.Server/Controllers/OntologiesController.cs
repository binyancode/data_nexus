using Microsoft.AspNetCore.Authorization;
using Microsoft.AspNetCore.Mvc;
using Microsoft.Data.SqlClient;
using System.Data;
using System.Text.Json;
using DataNexus.Server.Models;
using DataNexus.Server.Services;

namespace DataNexus.Server.Controllers
{
    // 本体管理：BFF 直连 DB 读写 nexus.ontology（整块 graph JSON）+ nexus.ontology_grant。
    // 可见性：private（仅 owner）| shared（owner + 授权名单）| public（所有人）。写操作仅 owner。
    [Authorize]
    [ApiController]
    [Route("api/[controller]")]
    public class OntologiesController : ControllerBase
    {
        private readonly SqlService _sql;

        public OntologiesController(SqlService sql)
        {
            _sql = sql;
        }

        private string Me => User.Identity?.Name ?? "";

        // ── 列表（对我可见；不含 graph）──
        [HttpGet]
        public async Task<APIResponseModel> List()
        {
            var t = await _sql.QueryAsync(
                @"SELECT o.ontology_id, o.name, o.description, o.owner, o.visibility, o.state, o.updated_at
                    FROM nexus.ontology o
                   WHERE o.owner = @me
                      OR o.visibility = 'public'
                      OR (o.visibility = 'shared' AND EXISTS (
                            SELECT 1 FROM nexus.ontology_grant g
                             WHERE g.ontology_id = o.ontology_id AND g.user_name = @me))
                   ORDER BY o.updated_at DESC",
                new[] { new SqlParameter("@me", Me) });

            var items = t.AsEnumerable().Select(r => new
            {
                ontologyId = r.Field<string?>("ontology_id"),
                name = r.Field<string?>("name"),
                description = r.Field<string?>("description"),
                owner = r.Field<string?>("owner"),
                visibility = r.Field<string?>("visibility"),
                state = r.Field<string?>("state"),
                updatedAt = r.Field<DateTime?>("updated_at"),
                canEdit = r.Field<string?>("owner") == Me,
            }).ToList();
            return new APIResponseModel { Data = items };
        }

        // ── 取一份（含 graph；校验读权限）──
        [HttpGet("{id}")]
        public async Task<APIResponseModel> Get(string id)
        {
            var row = await FetchAsync(id);
            if (row == null) return new APIResponseModel { State = "error", Message = "本体不存在" };

            var owner = row.Field<string?>("owner");
            var visibility = row.Field<string?>("visibility");
            var grants = await GrantsAsync(id);
            var canRead = visibility == "public" || owner == Me || (visibility == "shared" && grants.Contains(Me));
            if (!canRead) return new APIResponseModel { State = "error", Message = "无权访问" };

            var graphStr = row.Field<string?>("graph") ?? "{}";
            using var doc = JsonDocument.Parse(graphStr);
            var graph = doc.RootElement.Clone();

            return new APIResponseModel
            {
                Data = new
                {
                    ontologyId = id,
                    name = row.Field<string?>("name"),
                    description = row.Field<string?>("description"),
                    owner,
                    visibility,
                    state = row.Field<string?>("state"),
                    grants,
                    graph,
                    canEdit = owner == Me,
                },
            };
        }

        public class CreateDto { public string? Name { get; set; } public string? Description { get; set; } }

        // ── 新建空白本体 ──
        [HttpPost]
        public async Task<APIResponseModel> Create([FromBody] CreateDto dto)
        {
            if (string.IsNullOrWhiteSpace(dto.Name))
                return new APIResponseModel { State = "error", Message = "名称不能为空" };

            var id = "onto_" + Guid.NewGuid().ToString("N").Substring(0, 12);
            var emptyGraph = "{\"version\":3,\"entities\":[],\"relations\":[],\"metrics\":[],\"derivations\":[],\"actions\":[],\"resolvers\":[]}";
            await _sql.ExecuteNonQueryAsync(
                @"INSERT INTO nexus.ontology (ontology_id, name, description, owner, visibility, state, graph)
                  VALUES (@id, @name, @desc, @me, 'private', 'draft', @graph);",
                new[]
                {
                    new SqlParameter("@id", id),
                    new SqlParameter("@name", dto.Name),
                    new SqlParameter("@desc", (object?)dto.Description ?? DBNull.Value),
                    new SqlParameter("@me", Me),
                    new SqlParameter("@graph", emptyGraph),
                });
            return new APIResponseModel { Data = new { ontologyId = id } };
        }

        public class SaveDto
        {
            public string? Name { get; set; }
            public string? Description { get; set; }
            public JsonElement Graph { get; set; }
        }

        // ── 保存（owner-only；整块 graph）──
        [HttpPut("{id}")]
        public async Task<APIResponseModel> Save(string id, [FromBody] SaveDto dto)
        {
            if (!await IsOwnerAsync(id)) return new APIResponseModel { State = "error", Message = "只有创建者可编辑" };
            if (dto.Graph.ValueKind != JsonValueKind.Object
                || !dto.Graph.TryGetProperty("version", out var version)
                || version.GetInt32() != 3)
                return new APIResponseModel { State = "error", Message = "本体 graph.version 必须为 3" };
            if (dto.Graph.TryGetProperty("relations", out var relations) && relations.ValueKind == JsonValueKind.Array)
            {
                foreach (var relation in relations.EnumerateArray())
                {
                    if (!relation.TryGetProperty("from", out _)
                        || !relation.TryGetProperty("to", out _)
                        || !relation.TryGetProperty("multiplicity", out _)
                        || !relation.TryGetProperty("integrity", out _))
                        return new APIResponseModel { State = "error", Message = "关系必须设置端点、双向基数、可选性和完整性来源" };
                    if (relation.TryGetProperty("confirmation", out var confirmation)
                        && confirmation.TryGetProperty("required", out var required)
                        && required.GetBoolean()
                        && (!confirmation.TryGetProperty("confirmed", out var confirmed) || !confirmed.GetBoolean()))
                        return new APIResponseModel { State = "error", Message = "存在尚未确认语义的导入关系" };
                }
            }
            var graphStr = dto.Graph.ValueKind == JsonValueKind.Undefined ? "{}" : dto.Graph.GetRawText();
            await _sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.ontology
                     SET name=@name, description=@desc, graph=@graph, updated_at=SYSUTCDATETIME()
                   WHERE ontology_id=@id;",
                new[]
                {
                    new SqlParameter("@id", id),
                    new SqlParameter("@name", (object?)dto.Name ?? ""),
                    new SqlParameter("@desc", (object?)dto.Description ?? DBNull.Value),
                    new SqlParameter("@graph", graphStr),
                });
            return new APIResponseModel { Message = "已保存" };
        }

        public class PublishDto { public string? Visibility { get; set; } public List<string>? Grants { get; set; } }

        // ── 发布（owner-only；设可见性 + 授权名单）──
        [HttpPost("{id}/publish")]
        public async Task<APIResponseModel> Publish(string id, [FromBody] PublishDto dto)
        {
            if (!await IsOwnerAsync(id)) return new APIResponseModel { State = "error", Message = "只有创建者可发布" };
            var current = await FetchAsync(id);
            if (current == null) return new APIResponseModel { State = "error", Message = "本体不存在" };
            using (var graphDoc = JsonDocument.Parse(current.Field<string?>("graph") ?? "{}"))
            {
                var graph = graphDoc.RootElement;
                if (!graph.TryGetProperty("version", out var version) || version.GetInt32() != 3)
                    return new APIResponseModel { State = "error", Message = "只能发布 graph v3 本体" };
                if (graph.TryGetProperty("relations", out var relations) && relations.ValueKind == JsonValueKind.Array)
                    foreach (var relation in relations.EnumerateArray())
                        if (relation.TryGetProperty("confirmation", out var confirmation)
                            && confirmation.TryGetProperty("required", out var required) && required.GetBoolean()
                            && (!confirmation.TryGetProperty("confirmed", out var confirmed) || !confirmed.GetBoolean()))
                            return new APIResponseModel { State = "error", Message = "存在尚未确认语义的导入关系" };
            }
            var vis = dto.Visibility is "public" or "shared" or "private" ? dto.Visibility : "private";

            await _sql.ExecuteNonQueryAsync(
                @"UPDATE nexus.ontology SET visibility=@vis, state='published', updated_at=SYSUTCDATETIME() WHERE ontology_id=@id;
                  DELETE FROM nexus.ontology_grant WHERE ontology_id=@id;",
                new[] { new SqlParameter("@id", id), new SqlParameter("@vis", vis!) });

            if (vis == "shared" && dto.Grants != null)
            {
                foreach (var u in dto.Grants.Where(u => !string.IsNullOrWhiteSpace(u)).Distinct())
                {
                    await _sql.ExecuteNonQueryAsync(
                        "INSERT INTO nexus.ontology_grant (ontology_id, user_name) VALUES (@id, @u);",
                        new[] { new SqlParameter("@id", id), new SqlParameter("@u", u) });
                }
            }
            return new APIResponseModel { Message = "已发布" };
        }

        // ── 删除（owner-only）──
        [HttpDelete("{id}")]
        public async Task<APIResponseModel> Delete(string id)
        {
            if (!await IsOwnerAsync(id)) return new APIResponseModel { State = "error", Message = "只有创建者可删除" };
            await _sql.ExecuteNonQueryAsync(
                @"DELETE FROM nexus.ontology_grant WHERE ontology_id=@id;
                  DELETE FROM nexus.ontology WHERE ontology_id=@id;",
                new[] { new SqlParameter("@id", id) });
            return new APIResponseModel { Message = "已删除" };
        }

        // ── helpers ──
        private async Task<DataRow?> FetchAsync(string id)
        {
            var t = await _sql.QueryAsync(
                "SELECT ontology_id, name, description, owner, visibility, state, graph FROM nexus.ontology WHERE ontology_id=@id",
                new[] { new SqlParameter("@id", id) });
            return t.AsEnumerable().FirstOrDefault();
        }

        private async Task<List<string>> GrantsAsync(string id)
        {
            var t = await _sql.QueryAsync(
                "SELECT user_name FROM nexus.ontology_grant WHERE ontology_id=@id",
                new[] { new SqlParameter("@id", id) });
            return t.AsEnumerable().Select(r => r.Field<string>("user_name")!).ToList();
        }

        private async Task<bool> IsOwnerAsync(string id)
        {
            var row = await FetchAsync(id);
            return row != null && row.Field<string?>("owner") == Me;
        }
    }
}
