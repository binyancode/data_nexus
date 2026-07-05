# Data Nexus — Backend (FastAPI)

联邦语义中台后端。分两种使用方式：**① REST API**（本服务）与 **② SDK**（`app/nexus` 包，可被其他程序直接 import）。

## 层级结构

```
backend/
├─ requirements.txt
├─ .env.example
└─ app/
   ├─ main.py              # FastAPI 入口：CORS + 配置驱动的动态路由
   ├─ bootstrap.py         # 服务与 Resolver 注册
   ├─ config.py            # 分层配置（文件 → 环境变量），单例
   ├─ config.json          # 配置（无密钥；密钥走环境变量/KeyVault）
   ├─ config.development.json
   ├─ api/v1/
   │  ├─ router.py         # 配置驱动加载 endpoints
   │  └─ endpoints/        # ask · concepts · resolvers
   ├─ core/
   │  ├─ services.py       # IoC 服务容器（services[Type]）
   │  └─ deps.py           # FastAPI 依赖
   ├─ models/              # API 请求/响应模型
   ├─ utils/               # logger · json_utils
   └─ nexus/               # ★ 引擎 SDK（框架无关）
      ├─ client.py         # NexusClient 门面（SDK 入口）
      ├─ core/             # Concept · Binding · Capabilities · SQG · ExecContext
      ├─ resolvers/        # Resolver 接口 + SqlResolver
      ├─ engine/           # Compiler · Optimizer · Coordinator · Generator
      ├─ ontology/         # 本体存储（SQLite 起步）
      └─ registry.py       # Resolver 注册表 + 选源竞标候选
```

## 运行

依赖以 `app/` 为导入根（扁平 import），请在 `app/` 目录内启动：

```powershell
cd backend
python -m pip install -r requirements.txt
cd app
uvicorn main:app --reload --port 8000
```

- 健康检查：`GET http://localhost:8000/health`
- 接口文档：`http://localhost:8000/docs`
- 已注册源：`GET /api/v1/resolvers`

> P0 阶段：引擎四段（Compiler/Optimizer/Coordinator/Generator）为骨架，`/api/v1/ask` 会返回 501，待逐段实现。
