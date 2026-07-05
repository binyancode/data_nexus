"""FastAPI 依赖注入辅助。

约定：通过 services[Type] 从全局 IoC 容器取服务实例；
此模块提供把这些实例暴露成 FastAPI Depends 的薄封装。
"""
from typing import Optional

from fastapi import Request, HTTPException

from config import config as _config
from core.services import services
from core.msal_auth import msal_auth, jwt_error, jwt_identity
from nexus.client import NexusClient


def get_config():
    """返回全局配置单例。"""
    return _config()


def get_nexus() -> NexusClient:
    """返回 Nexus 引擎门面（单例）。"""
    return services[NexusClient]


def require_auth(request: Request) -> Optional[jwt_identity]:
    """校验请求携带的 Bearer Token，返回身份（`.user` = as_user）。

    不关心调用方是谁——BFF 代理、前端直连、curl、其它服务都可以，
    只要带的是配置 audience 的有效 Azure AD token。

    - 已配置 `config.msal`（tenant_id 等）→ 强校验，失败 401。
    - 未配置 msal → 开发模式放行：如带 `X-As-User` 头则用它，否则返回 None。
    """
    cfg = _config()
    msal_conf = cfg.get("msal") or {}
    if not msal_conf.get("tenant_id"):
        dev_user = request.headers.get("X-As-User")
        return jwt_identity({"preferred_username": dev_user}) if dev_user else None
    try:
        return msal_auth(msal_conf).auth(request)
    except jwt_error as ex:
        raise HTTPException(status_code=401, detail=str(ex))

