"""/api/v1/ask —— 自然语言提问入口。"""
from fastapi import APIRouter, Depends, HTTPException

from core.deps import get_nexus
from models.api import AskRequest, AskResponse
from nexus.client import NexusClient

router = APIRouter()


@router.post("", response_model=AskResponse)
def ask(req: AskRequest, nexus: NexusClient = Depends(get_nexus)):
    """一句话提问 → 编译 → 优化 → 协调 → 生成 → 答案 + 出处。"""
    answer = nexus.ask(req.q, as_user=req.as_user)
    return AskResponse(answer=answer.text, lineage=answer.lineage)
