from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import importlib

from config import config
from bootstrap import register_services, register_resolvers

config = config()

app = FastAPI(
    title=config.get("APP_NAME", "Data Nexus API"),
    description=config.get("APP_DESCRIPTION", ""),
    version=config.get("APP_VERSION", "0.1.0"),
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=config.get("ALLOWED_ORIGINS", []),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 注册服务与 Resolver
register_services()
register_resolvers()

# 配置驱动的动态路由加载
for router, define in config.get("route_prefixes", {}).items():
    module = importlib.import_module(router)
    api_router = getattr(module, define["api_router"])
    app.include_router(api_router, prefix=define["prefix"])


@app.get("/health")
async def health_check():
    return {"status": "ok"}
