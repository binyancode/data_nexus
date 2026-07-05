"""api_handler —— 端点装饰器（auth / log / inject），Nexus 轻量版。

三个可叠加的装饰器（顺序无关）：
  - @api_handler.auth()            校验 Bearer Token，identity 存 request.state.identity
  - @api_handler.log()             记录请求/响应/耗时，异常兜底 500
  - @api_handler.service(T,"name") 注入 services[T]；无参 @api_handler.service() 按端点参数注解自动注入已注册服务

约定：被装饰的端点签名为 async def f(request: Request, **kwargs)，
自行从 request 解析 body（await request.json()）。装饰器对 FastAPI 只暴露
`(request: Request)`，运行时再把 identity/service 塞进 kwargs。

依赖：core/msal_auth（鉴权）、core/services（IoC）、utils/logger（日志）。
"""

from __future__ import annotations

import asyncio
import functools
import inspect
import json
import time
import traceback
from datetime import datetime, timezone
from typing import Optional, Type, get_type_hints

from fastapi import Request
from fastapi.responses import JSONResponse

from config import config as _config
from core.services import services
from core.msal_auth import msal_auth, jwt_error, jwt_identity
from core.api_log import ApiLogRecord, ApiLogSink
from utils.logger import get_logger

_logger = get_logger("api")

# 让 FastAPI 只看到 (request: Request)，忽略内层真实的 **kwargs
_REQUEST_SIGNATURE = inspect.Signature(
    [inspect.Parameter("request", inspect.Parameter.POSITIONAL_OR_KEYWORD, annotation=Request)]
)


def _expose(wrapper, func):
    wrapper.__name__ = getattr(func, "__name__", "endpoint")
    wrapper.__doc__ = getattr(func, "__doc__", None)
    wrapper.__signature__ = _REQUEST_SIGNATURE
    return wrapper


def _mask(text: Optional[str], keys: Optional[list[str]]) -> Optional[str]:
    if not text or not keys:
        return text
    try:
        obj = json.loads(text)
    except Exception:
        return text
    for k in keys:
        if k in obj:
            obj[k] = "***"
    return json.dumps(obj, ensure_ascii=False)


def _serialize_response(resp) -> Optional[str]:
    try:
        if isinstance(resp, (dict, list)):
            return json.dumps(resp, ensure_ascii=False, default=str)
        body = getattr(resp, "body", None)  # JSONResponse
        if body is not None:
            return body.decode("utf-8", "ignore")
        return None if resp is None else str(resp)
    except Exception:
        return None


def _derive_state(resp, error: Optional[str]) -> str:
    """根据异常/响应状态码区分日志状态。"""
    if error:
        return "failed"
    code = getattr(resp, "status_code", 200)
    if code == 401:
        return "unauthorized"
    if code == 403:
        return "denied"
    if code >= 500:
        return "failed"
    if code >= 400:
        return "error"
    return "success"


class api_handler:
    """端点装饰器工厂。"""

    # 外部注册（依赖倒置：core 不直接引用 services 层，由外部把实现注册进来）
    _registry: dict = {}
    _log_sinks: list = []

    @classmethod
    def register(cls, key: str, value) -> None:
        """注册一个外部对象供装饰器使用（如某个 helper）。"""
        cls._registry[key] = value

    @classmethod
    def get(cls, key: str, default=None):
        return cls._registry.get(key, default)

    @classmethod
    def register_log_sink(cls, sink: ApiLogSink) -> None:
        """注册一个实现了 ApiLogSink 接口的日志汇（如写 DB）。可注册多个。"""
        if not isinstance(sink, ApiLogSink):
            raise TypeError(f"log sink must implement ApiLogSink, got {type(sink).__name__}")
        cls._log_sinks.append(sink)

    @classmethod
    async def _emit(cls, record: ApiLogRecord) -> None:
        if not cls._log_sinks:
            return

        def _run():
            for sink in cls._log_sinks:
                try:
                    sink.emit(record)
                except Exception as ex:
                    _logger.warning(f"log sink failed: {ex}")

        await asyncio.to_thread(_run)


    # ── 鉴权 ──
    @classmethod
    def auth(cls, required: bool = True):
        def decorator(func):
            async def wrapper(request: Request, **kwargs):
                identity = cls._authenticate(request)
                if identity is None and required and cls._auth_enabled():
                    return JSONResponse({"state": "error", "message": "Unauthorized"}, status_code=401)
                request.state.identity = identity
                return await func(request, **kwargs)
            return _expose(wrapper, func)
        return decorator

    # ── 日志 ──
    @classmethod
    def log(cls, sanitize: Optional[list[str]] = None):
        def decorator(func):
            name = getattr(func, "__name__", "endpoint")

            async def wrapper(request: Request, **kwargs):
                start = time.time()
                request_time = datetime.now(timezone.utc)
                try:
                    body = (await request.body()).decode("utf-8", "ignore")
                except Exception:
                    body = ""
                payload = _mask(body, sanitize)

                error, tb, resp = None, None, None
                try:
                    resp = await func(request, **kwargs)
                    return resp
                except Exception as ex:
                    error = str(ex)
                    tb = traceback.format_exc()  # 完整堆栈，用于定位报错行
                    resp = JSONResponse({"state": "failed", "message": error}, status_code=500)
                    return resp
                finally:
                    cost = int((time.time() - start) * 1000)
                    user = getattr(getattr(request.state, "identity", None), "user", None)
                    state = _derive_state(resp, error)
                    await cls._emit(ApiLogRecord(
                        function=name,
                        method=request.method,
                        path=request.url.path,
                        state=state,
                        user=user,
                        payload=payload,
                        response=_serialize_response(resp),
                        message=tb,
                        cost_ms=cost,
                        source="backend",
                        request_time=request_time,
                        response_time=datetime.now(timezone.utc),
                    ))
            return _expose(wrapper, func)
        return decorator

    # ── 服务注入 ──
    @classmethod
    def service(cls, service_type: Optional[Type] = None, name: Optional[str] = None):
        """注入服务实例为端点关键字参数。

        - service(T, "name")：显式注入 services[T] 为 kwargs["name"]。
        - service()：自动扫描端点参数，凡注解为「已注册服务类型」的按参数名注入。
          （自动模式需把 service() 作为最内层装饰器，才能读到端点真实签名；
           注入目标延迟到首次调用时解析，不受注册顺序影响。）
        """
        def decorator(func):
            explicit = None if service_type is None else [(name or service_type.__name__, service_type)]
            cache = {"targets": explicit}

            async def wrapper(request: Request, **kwargs):
                targets = cache["targets"]
                if targets is None:
                    targets = cls._scan_service_params(func)
                    cache["targets"] = targets
                for pname, ptype in targets:
                    if pname not in kwargs:  # 已显式传入的不覆盖
                        kwargs[pname] = services[ptype]
                return await func(request, **kwargs)
            return _expose(wrapper, func)
        return decorator

    @staticmethod
    def _scan_service_params(func) -> list:
        """扫描 func 参数，返回 [(参数名, 类型)]；类型须已注册到 services。"""
        result = []
        try:
            sig = inspect.signature(func)
            hints = get_type_hints(func)
        except Exception:
            return result
        for pname, param in sig.parameters.items():
            if pname == "request" or param.kind in (param.VAR_KEYWORD, param.VAR_POSITIONAL):
                continue
            ann = hints.get(pname)
            if isinstance(ann, type) and services.is_registered(ann):
                result.append((pname, ann))
        return result

    # ── 内部 ──
    @classmethod
    def _msal_conf(cls) -> dict:
        return _config().get("msal") or {}

    @classmethod
    def _auth_enabled(cls) -> bool:
        return bool(cls._msal_conf().get("tenant_id"))

    @classmethod
    def _authenticate(cls, request: Request) -> Optional[jwt_identity]:
        conf = cls._msal_conf()
        if not conf.get("tenant_id"):
            dev_user = request.headers.get("X-As-User")
            return jwt_identity({"preferred_username": dev_user}) if dev_user else None
        try:
            return msal_auth(conf).auth(request)
        except jwt_error:
            return None
