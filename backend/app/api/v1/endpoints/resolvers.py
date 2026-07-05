"""/api/v1/resolvers —— 列出 Resolver、探测其 schema、导入预览（产出可并入画板的 graph 片段）。"""
from fastapi import APIRouter, Depends, HTTPException, Request

from core.deps import get_nexus
from nexus.client import NexusClient

router = APIRouter()


@router.get("")
async def list_resolvers(nexus: NexusClient = Depends(get_nexus)):
    """已注册的 Resolver（name/type）。"""
    return nexus.list_resolvers()


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
