from fastapi import APIRouter
from config import config
import importlib

api_router = APIRouter()

# 配置驱动：从 config.route_prefixes[本模块].endpoints 动态加载各 endpoint 路由
config = config()
package_prefix = __name__.rsplit(".", 1)[0]  # "api.v1"
for endpoint, define in config.get("route_prefixes", {}).get(__name__, {}).get("endpoints", {}).items():
    module_name, attr_name = endpoint.rsplit(".", 1)   # "ask.router" -> ("ask", "router")
    module = importlib.import_module(f"{package_prefix}.endpoints.{module_name}")
    api_router.include_router(
        getattr(module, attr_name),
        prefix=define["prefix"],
        tags=define["tags"],
    )
