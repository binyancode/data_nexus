"""/api/v1/resolvers —— 列出已注册的 Resolver 及其能力清单。"""
from fastapi import APIRouter, Depends

from core.deps import get_nexus
from nexus.client import NexusClient

router = APIRouter()


@router.get("")
async def list_resolvers(nexus: NexusClient = Depends(get_nexus)):
    """返回每个 Resolver 的能力清单（能答哪些概念、成本、时效、信任分、是否 user_scoped）。"""
    return nexus.list_resolvers()
