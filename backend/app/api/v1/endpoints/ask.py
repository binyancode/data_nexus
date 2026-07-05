"""/api/v1/ask —— 自然语言提问入口（用 api_handler 装饰器：auth + log + inject）。"""
import asyncio

from fastapi import APIRouter, Request

from core.api_handler import api_handler
from nexus.client import NexusClient

router = APIRouter()


@router.post("")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def ask(request: Request, nexus: NexusClient = None):
    """一句话提问 → 编译 → 优化 → 协调 → 生成 → 答案 + 出处。

    as_user 优先取自认证身份（request.state.identity），否则回退请求体。
    """
    body = await request.json()
    identity = getattr(request.state, "identity", None)
    as_user = (identity.user if identity else None) or body.get("as_user")

    answer = await asyncio.to_thread(nexus.ask, body.get("q"), as_user)
    return {
        "answer": answer.text,
        "lineage": [li.model_dump() for li in answer.lineage],
    }
