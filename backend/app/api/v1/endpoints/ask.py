"""/api/v1/ask —— 自然语言提问入口。"""
from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_nexus
from models.api import AskRequest, AskResponse
from nexus.client import NexusClient

router = APIRouter()


@router.post("", response_model=AskResponse)
async def ask(req: AskRequest, nexus: NexusClient = Depends(get_nexus)):
    """一句话提问 → 编译 → 调度 → 协调 → 生成 → 答案 + 血缘。"""
    try:
        answer = await nexus.ask(req.q, as_user=req.as_user)
    except NotImplementedError as e:
        # P0 骨架：引擎各段尚未实现
        raise HTTPException(status_code=501, detail=str(e))
    return AskResponse(answer=answer.text, lineage=answer.lineage)
