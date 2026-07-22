"""/api/v1/ask —— 自然语言提问入口（异步：先建 run 返回 run_id，后台线程执行；前端轮询 run 状态）。"""
from fastapi import APIRouter, Request

from core.api_handler import api_handler
from nexus.client import NexusClient

router = APIRouter()


@router.post("")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def ask(request: Request, nexus: NexusClient = None):
    """一句话提问 → 立即返回 run_id，后台执行五段引擎；前端据 run_id 轮询 nexus.run/run_stage/run_node 看进度。

    as_user 优先取自认证身份（request.state.identity），否则回退请求体。
    """
    body = await request.json()
    identity = getattr(request.state, "identity", None)
    as_user = (identity.user if identity else None) or body.get("as_user")

    question = body.get("q")
    if not isinstance(question, str) or not question.strip():
        return {"state": "error", "message": "问题不能为空"}
    ontology_id = body.get("ontology_id")   # 显式指定；缺省则由 LLM 自动路由
    llm_name = body.get("llm_name")         # 本次运行选中的规划 LLM；缺省用默认
    compute_engine_name = body.get("compute_engine_name")  # 缺省由计算引擎注册表选默认

    # start_ask 同步建 run 后返回 run_id；本体选择/校验在后台的「初始化器」段完成（选不到→失败段，前端轮询可见）
    try:
        run_id = nexus.start_ask(question=question, as_user=as_user,
                                 ontology_id=ontology_id, llm_name=llm_name,
                                 compute_engine_name=compute_engine_name)
    except ValueError as ex:
        return {"state": "error", "message": str(ex)}

    return {"run_id": run_id}
