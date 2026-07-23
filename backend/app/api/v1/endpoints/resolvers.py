"""/api/v1/resolvers —— 列出 Resolver、探测其 schema、导入预览（产出可并入画板的 graph 片段）。"""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse

from core.api_handler import api_handler
from core.deps import get_nexus
from nexus.client import NexusClient

router = APIRouter()


@router.get("")
async def list_resolvers(nexus: NexusClient = Depends(get_nexus)):
    """已注册的 Resolver（name/type）。"""
    return nexus.list_resolvers()


@router.post("/reload")
async def reload_registry(nexus: NexusClient = Depends(get_nexus)):
    """从 DB 重新装配 resolver / llm（源/凭据/LLM 管理保存后调用，免重启即时生效）。"""
    return nexus.reload_registry()


@router.get("/{name}/schema")
async def resolver_schema(name: str, nexus: NexusClient = Depends(get_nexus)):
    """探测某个 sql resolver 的表与列：{tables: {schema.table: [{column,type}]}}。"""
    schema = nexus.resolver_schema(name)
    if schema is None:
        raise HTTPException(status_code=404, detail=f"resolver '{name}' 不可探测")
    return schema


@router.post("/{name}/import-preview")
async def import_preview(name: str, request: Request, nexus: NexusClient = Depends(get_nexus)):
    """选定表 → 产出 graph 片段（entities/relations）。body: {tables:[...]}"""
    body = await request.json()
    tables = body.get("tables") or []
    frag = nexus.import_preview(name, tables)
    if frag is None:
        raise HTTPException(status_code=404, detail=f"resolver '{name}' 不可探测")
    return frag


@router.post("/{name}/sample")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def resolver_sample(request: Request, name: str = None, nexus: NexusClient = None):
    """读取实体物理对象的样例行。body: {target, limit?}；最多 100 行。"""
    name = name or request.path_params.get("name")
    body = await request.json()
    target = str(body.get("target") or "").strip()
    if not target:
        return JSONResponse({"state": "error", "message": "target 必填"}, status_code=400)
    try:
        limit = int(body.get("limit", 20))
    except (TypeError, ValueError):
        return JSONResponse({"state": "error", "message": "limit 必须是整数"}, status_code=400)
    if not 1 <= limit <= 100:
        return JSONResponse({"state": "error", "message": "limit 必须在 1-100 之间"}, status_code=400)
    result = nexus.resolver_sample(name, target, limit)
    if result is None:
        return JSONResponse(
            {"state": "error", "message": f"resolver '{name}' 不支持样例数据"},
            status_code=404,
        )
    return result
