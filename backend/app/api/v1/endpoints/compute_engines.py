"""计算引擎目录与管理员配置 API。"""

from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from core.api_handler import api_handler
from nexus.client import NexusClient
from services.sql_db import sql_db

router = APIRouter()


def _error(message: str, status_code: int = 400) -> JSONResponse:
    return JSONResponse({"state": "error", "message": message}, status_code=status_code)


def _require_admin(request: Request, db: sql_db) -> JSONResponse | None:
    identity = getattr(request.state, "identity", None)
    user = identity.user if identity else None
    if not user:
        return _error("需要管理员身份", 403)
    rows = db.execute_query(
        "SELECT is_admin FROM nexus.app_user WHERE user_name = ?", (user,)
    )
    if not rows or not bool(rows[0].get("is_admin")):
        return _error("仅管理员可管理计算引擎", 403)
    return None


def _is_admin(request: Request, db: sql_db) -> bool:
    identity = getattr(request.state, "identity", None)
    user = identity.user if identity else None
    if not user:
        return False
    rows = db.execute_query(
        "SELECT is_admin FROM nexus.app_user WHERE user_name = ?", (user,)
    )
    return bool(rows and rows[0].get("is_admin"))


@router.get("")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def list_compute_engines(request: Request, nexus: NexusClient = None,
                               db: sql_db = None):
    """直接按数据库当前状态列出计算引擎；供查询下拉和管理页使用。"""
    items = nexus.compute_registry.list()
    if not _is_admin(request, db):
        items = [item for item in items if item.get("provision_state") == "ready"]
        for item in items:
            item.pop("provision_error", None)
    return JSONResponse(
        {"items": items},
        headers={"Cache-Control": "no-store"},
    )


@router.post("")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def create_compute_engine(request: Request, nexus: NexusClient = None,
                                db: sql_db = None):
    """创建配置；SQL Server 会先创建并验证固定 WITHOUT LOGIN 运行用户。"""
    denied = _require_admin(request, db)
    if denied:
        return denied
    body = await request.json()
    try:
        definition = nexus.compute_registry.create_definition(
            engine_name=body.get("engine_name"),
            engine_type=body.get("engine_type"),
            credential_name=body.get("credential_name"),
            runtime_user=body.get("runtime_user"),
            config=body.get("config") or {},
            is_default=bool(body.get("is_default")),
        )
        return definition.public()
    except ValueError as exc:
        return _error(str(exc))


@router.put("/{name}")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def update_compute_engine(request: Request, name: str = None,
                                nexus: NexusClient = None, db: sql_db = None):
    """更新运行参数或默认状态；类型、凭据和运行用户不可原地变更。"""
    denied = _require_admin(request, db)
    if denied:
        return denied
    body = await request.json()
    try:
        definition = nexus.compute_registry.update_definition(
            name or request.path_params.get("name"),
            config=body.get("config") or {},
            is_default=bool(body.get("is_default")),
        )
        return definition.public()
    except ValueError as exc:
        return _error(str(exc))


@router.post("/{name}/default")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def set_default_compute_engine(request: Request, name: str = None,
                                     nexus: NexusClient = None, db: sql_db = None):
    denied = _require_admin(request, db)
    if denied:
        return denied
    try:
        definition = nexus.compute_registry.set_default(name or request.path_params.get("name"))
        return definition.public()
    except ValueError as exc:
        return _error(str(exc))


@router.post("/{name}/test")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def test_compute_engine(request: Request, name: str = None,
                              nexus: NexusClient = None, db: sql_db = None):
    denied = _require_admin(request, db)
    if denied:
        return denied
    try:
        selected = name or request.path_params.get("name")
        nexus.compute_registry.test_definition(selected)
        return {"engine_name": selected, "tested": True}
    except ValueError as exc:
        return _error(str(exc))


@router.delete("/{name}")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def delete_compute_engine(request: Request, name: str = None,
                                nexus: NexusClient = None, db: sql_db = None):
    """停用配置，删除其固定 SQL Server 用户，然后删除元数据。"""
    denied = _require_admin(request, db)
    if denied:
        return denied
    selected = name or request.path_params.get("name")
    try:
        nexus.compute_registry.delete_definition(selected)
        return {"engine_name": selected, "deleted": True}
    except ValueError as exc:
        return _error(str(exc))
