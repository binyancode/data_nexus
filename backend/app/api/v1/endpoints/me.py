"""/api/v1/me —— 返回当前 access token 识别出的身份（用于验证后端对令牌的识别）。"""

from fastapi import APIRouter, Request

from core.api_handler import api_handler

router = APIRouter()


@router.get("")
@api_handler.log()
@api_handler.auth()
async def me(request: Request):
    """校验 Bearer Token（验签 + issuer/audience/scope），返回识别出的用户与关键声明。"""
    identity = getattr(request.state, "identity", None)
    claims = identity.identity if identity else {}
    return {
        "user": identity.user if identity else None,
        "preferred_username": claims.get("preferred_username"),
        "aud": claims.get("aud"),
        "scp": claims.get("scp"),
        "tid": claims.get("tid"),
        "ver": claims.get("ver"),
    }
