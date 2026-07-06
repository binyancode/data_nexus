"""/api/v1/credentials —— 凭据密文相关操作（详情/新建/更新/删除）。

边界：凭据「基础列表」由 BFF 直接读 DB（nexus.app_credential，非敏感元数据）；
只有涉及密文的操作（查看详情需回填非敏感值 / 新建 / 更新 / 删除）才走这里，
因为这些要访问 Key Vault，只有 Python 端持有 KV 访问能力。

安全：详情接口只回**非敏感**字段的值，敏感字段（sensitive=True）一律不返回。
更新不做合并——前端必须重新填写敏感字段（如密码），整份覆盖写回。
"""

from fastapi import APIRouter, Request

from core.api_handler import api_handler
from services.credential import credential, azure_keyvault_credential_provider

router = APIRouter()


def _sensitive_keys(credential_type: str) -> set[str]:
    """某凭据类型里 sensitive=True 的字段名集合。"""
    meta = credential.get_types().get(credential_type) or {}
    return {f["name"] for f in meta.get("schema", []) if f.get("sensitive")}


def _strip_sensitive(credential_type: str, data: dict) -> dict:
    """去掉敏感字段的值（前端展示时敏感字段留空/占位）。"""
    sk = _sensitive_keys(credential_type)
    return {k: v for k, v in (data or {}).items() if k not in sk}


@router.get("/types")
@api_handler.log()
@api_handler.auth()
async def credential_types(request: Request):
    """凭据类型 + 字段 schema（供前端动态渲染表单，含 required/sensitive）。"""
    return {"types": credential.get_types()}


@router.get("/{name}")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def credential_detail(request: Request, name: str = None,
                            cred: azure_keyvault_credential_provider = None):
    """凭据详情：回填**非敏感**字段值 + 类型 + 描述；敏感字段一律不返回。"""
    name = name or request.path_params.get("name")
    c = cred.load(name)
    if c is None:
        return {"state": "error", "message": f"credential '{name}' 不存在"}
    return {
        "credential_name": c.name,
        "credential_type": c.credential_type,
        "data": _strip_sensitive(c.credential_type, c.data),
    }


@router.post("")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def credential_create(request: Request, cred: azure_keyvault_credential_provider = None):
    """新建凭据。body: {credential_name, credential_type, data, description?}"""
    body = await request.json()
    name = (body.get("credential_name") or "").strip()
    ctype = body.get("credential_type") or ""
    data = body.get("data") or {}
    description = body.get("description") or ""
    if not name or not ctype:
        return {"state": "error", "message": "credential_name / credential_type 必填"}
    cred.save(name, ctype, data, description)   # credential 子类构造时会校验必填字段
    return {"credential_name": name}


@router.put("/{name}")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def credential_update(request: Request, name: str = None,
                            cred: azure_keyvault_credential_provider = None):
    """更新凭据（整份覆盖，不做合并——前端必须重填敏感字段）。

    body: {credential_type, data, description?}
    """
    name = name or request.path_params.get("name")
    body = await request.json()
    ctype = body.get("credential_type") or ""
    data = body.get("data") or {}
    description = body.get("description") or ""
    if not ctype:
        return {"state": "error", "message": "credential_type 必填"}
    cred.save(name, ctype, data, description)   # 子类构造校验：敏感字段缺失会报错
    return {"credential_name": name}


@router.delete("/{name}")
@api_handler.log()
@api_handler.auth()
@api_handler.service()
async def credential_delete(request: Request, name: str = None,
                            cred: azure_keyvault_credential_provider = None):
    """删除凭据（软删 DB 映射 + 删 KV 密文）。"""
    name = name or request.path_params.get("name")
    ok = cred.delete(name)
    return {"deleted": bool(ok), "credential_name": name}
