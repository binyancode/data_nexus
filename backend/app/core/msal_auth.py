"""MSAL / Azure AD JWT 认证（从 AIBI 移植并裁剪）。

校验请求携带的 OAuth2 Bearer Token（无论来自 BFF 代理、前端直连还是其它调用方）：
验签（JWKS）+ 校验 issuer/audience/scope，返回 `jwt_identity`（`.user` = preferred_username 或 app 的 appid）。

依赖：PyJWT + cryptography（已随 azure-identity 安装）。
配置：`config.msal` = { tenant_id, authority, client_id, audience, scopes: [...] }。
"""

from __future__ import annotations

import base64
import json

import jwt
from jwt import PyJWKClient
from fastapi import Request


class jwt_error(Exception):
    """JWT 认证异常。"""
    pass


class jwt_identity:
    """认证身份封装，统一取用户标识。"""

    def __init__(self, identity: dict):
        self.identity = identity

    @property
    def user(self) -> str:
        if self.identity.get("idtyp") == "app":
            return self.identity.get("appid", "unknown_app")
        return self.identity.get("preferred_username", "unknown_user")


class msal_auth:
    """Azure AD 认证服务：验证 Bearer Token，返回 jwt_identity。"""

    def __init__(self, msal_config: dict):
        self.msal_config = msal_config or {}

    def auth(self, req: Request) -> jwt_identity:
        auth_header = req.headers.get("Authorization", "")
        if not (auth_header and auth_header.lower().startswith("bearer ")):
            raise jwt_error("Missing OAuth2 Bearer token")
        try:
            claims = self._token_is_valid(self.msal_config, auth_header[7:])
        except jwt_error:
            raise
        except Exception as ex:
            raise jwt_error("Invalid token: " + str(ex))

        scopes = set(self.msal_config.get("scopes", []))
        if scopes and "scp" in claims and not (set(claims["scp"].split()) & scopes):
            raise jwt_error("Invalid scope")
        return jwt_identity(claims)

    def _token_is_valid(self, msal_config: dict, token: str) -> dict:
        tenant_id = msal_config["tenant_id"]
        authority = msal_config["authority"]
        audience = msal_config["audience"]

        _, payload = self._decode_without_verification(token)
        issuer_url = payload["iss"]
        valid_hosts = [
            "https://login.microsoftonline.com",
            "https://sts.windows.net",
            "https://login.partner.microsoftonline.cn",
            "https://sts.chinacloudapi.cn",
        ]
        if not any(issuer_url.lower().startswith(f"{host}/{tenant_id}".lower()) for host in valid_hosts):
            raise jwt_error(f"Invalid issuer: {issuer_url}")

        jwks_url = f"{authority}/{tenant_id}/discovery/v2.0/keys"
        signing_key = PyJWKClient(jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer_url,
        )

    @staticmethod
    def _decode_without_verification(token: str):
        try:
            header, payload, _ = token.split(".")
            decoded_header = json.loads(base64.urlsafe_b64decode(header + "==").decode("utf-8"))
            decoded_payload = json.loads(base64.urlsafe_b64decode(payload + "==").decode("utf-8"))
            return decoded_header, decoded_payload
        except Exception as e:
            raise jwt_error(f"Failed to decode jwt: {e}")
