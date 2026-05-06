# WenSai Backend

WenSai Backend 是问赛的业务控制面。它负责认证、工作区、论文评审、Agent 任务状态、事件、审批、文件归档、文件预览和对 AgentSDK 的 internal dispatch。

Backend 不直接运行 Hermes，不直接调用 ACP，不直接运行官方 CubeSandbox。所有 Agent 执行都通过 AgentSDK。

## 技术栈

| 层 | 技术 |
| --- | --- |
| API | FastAPI |
| 数据模型 | SQLModel, SQLAlchemy |
| 数据库 | PostgreSQL |
| 迁移 | Alembic |
| 实时事件 | Redis Pub/Sub, WebSocket |
| 异步任务 | Celery |
| 存储 | Local filesystem 或 S3/MinIO |
| AI Review | OpenAI-compatible API |
| 测试 | pytest |

## 系统位置

```text
Frontend
  -> Backend public API /api
  -> Backend WebSocket /ws

Backend
  -> PostgreSQL
  -> Redis
  -> Storage local/S3
  -> AgentSDK internal API

AgentSDK
  -> local-sandbox fallback
  -> official CubeSandbox API in production target
```

## 核心职责

- 用户认证：注册、登录、JWT、邀请码、积分。
- 工作区：个人空间、团队空间、成员、当前 active workspace。
- 论文评审：论文 CRUD、附件上传、人工评审、AI 评审。
- Agent 任务：创建、启动、取消、删除、状态机。
- 事件系统：写入 PostgreSQL，再发布 Redis，WebSocket 推送到前端。
- 审批：Agent 高风险操作申请、用户批准/拒绝、AgentSDK 等待结果。
- 文件系统：任务文件、工作区文件、预览、下载、真实删除。
- Internal API：AgentSDK 回写状态、事件、结果、错误、审批和文件。

## 本地开发

前置条件：

- Python 3.12
- PostgreSQL
- Redis
- AgentSDK 可选，默认地址 `http://127.0.0.1:8010`

安装：

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

配置 `.env` 后执行迁移：

```bash
alembic upgrade head
```

启动 API：

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
```

API 文档：

```text
http://127.0.0.1:8000/docs
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `SECRET_KEY` | JWT 签名密钥，生产必须强随机 |
| `DATABASE_URL` | PostgreSQL 连接串 |
| `REDIS_URL` | Redis 连接串 |
| `UPLOAD_DIR` | local storage 目录 |
| `MAX_UPLOAD_SIZE_MB` | 上传大小限制 |
| `INVITE_CODE` | 注册邀请码 |
| `LLM_API_KEY` | OpenAI-compatible key |
| `LLM_BASE_URL` | OpenAI-compatible base URL |
| `LLM_MODEL` | AI 评审模型 |
| `STORAGE_BACKEND` | `local` 或 `s3` |
| `S3_*` | S3/MinIO 配置 |
| `CORS_ORIGINS` | 允许的前端域名 |
| `AGENTSDK_BASE_URL` | AgentSDK internal API 地址 |
| `INTERNAL_API_TOKEN` | Backend 与 AgentSDK 共享的服务间 token |
| `DISPATCH_AGENT_TASKS` | 是否派发 Agent 任务 |
| `LOCAL_WORKSPACE_ROOT` | 本地空间 root path fallback |
| `PREVIEW_CACHE_DIR` | PDF/Office 页图缓存目录 |
| `SOFFICE_COMMAND` | LibreOffice 命令 |
| `PDF_PREVIEW_DPI` | PDF/Office 转图 DPI |

生产配置请基于 [.env.example](./.env.example) 创建 `.env`。如果使用三仓库统一编排，建议在服务器上层部署目录维护专用 `.env.production`，不要提交真实密钥。

## 目录结构

```text
app/
  main.py             FastAPI 入口、路由注册、启动重派发
  config.py           环境变量
  database.py         SQLAlchemy engine/session
  storage.py          local/S3 存储抽象
  auth/               注册、登录、JWT、积分
  users/              用户模型和 schema
  workspaces/         工作区、成员、active workspace
  papers/             论文和附件
  reviews/            人工/AI 评审
  tasks/              Agent task public API、dispatcher、状态服务
  events/             任务事件模型和 EventService
  approvals/          用户审批 API
  files/              任务文件、工作区文件、预览和真实删除
  internal_api/       AgentSDK 回写 API
  realtime/           WebSocket 推送
  agent_profiles/     Agent profile API
alembic/              数据库迁移
tests/                pytest 测试
```

## API 分组

| 分组 | 路径 |
| --- | --- |
| Auth | `/api/auth/*` |
| Workspaces | `/api/workspaces/*` |
| Papers | `/api/papers/*` |
| Reviews | `/api/papers/{id}/reviews`, `/api/reviews/*` |
| Tasks | `/api/tasks/*` |
| Approvals | `/api/approvals/*`, `/api/tasks/{id}/approvals/*` |
| Files | `/api/tasks/{id}/files`, `/api/workspaces/{id}/files`, `/api/files/*` |
| Internal | `/api/internal/*` |
| WebSocket | `/ws/tasks/{task_id}/events` |

## Agent 任务链路

1. Frontend 创建任务：`POST /api/tasks`。
2. Backend 创建 `Task`，状态进入 `queued`。
3. Backend 调 AgentSDK：`POST /internal/agent-runs`，只发送 `task_id`。
4. AgentSDK 通过 Backend internal API 读取任务详情。
5. AgentSDK 运行 runtime，向 Backend 回写事件、审批、文件和结果。
6. Backend 写数据库、发布 Redis，WebSocket 推送给 Frontend。

Backend 启动时会重新派发未开始的 queued tasks，避免 AgentSDK 暂时离线造成任务卡住。

## 文件与沙盒链路

- Backend 保存文件记录和 storage object。
- 上传/新建任务文件后，Backend 会把文件转发到 AgentSDK sandbox input。
- 删除文件时，Backend 必须删除 storage 记录和 AgentSDK sandbox 内真实文件。
- 删除任务/沙盒时，Backend 会请求 AgentSDK cleanup 对应 sandbox。
- PDF/Office 预览页图由 Backend 生成并缓存，Frontend 可再同步到 IndexedDB。

## 数据库迁移

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

生产每次发布后都要执行：

```bash
alembic upgrade head
```

## 测试

```bash
pytest
```

建议按改动范围运行：

```bash
pytest tests/test_auth.py
pytest tests/test_tasks_platform.py tests/test_workspaces.py
pytest tests/test_papers.py tests/test_reviews.py
```

## 部署

单 Backend compose 见本目录 [docker-compose.yml](./docker-compose.yml)。

完整生产部署推荐在服务器上层部署目录统一编排 `Backend / AgentSDK / PostgreSQL / Redis`。如果只部署 Backend，可使用本目录 compose：

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

生产版官方 CubeSandbox 应安装在宿主机 / 裸机层，AgentSDK 通过 API 调用。不要把 CubeSandbox 宿主机组件放进 Backend 或 AgentSDK 容器。

## 维护注意

- Backend 是权限和数据一致性的最终裁决点。
- Internal API 必须校验 `X-Internal-Token`。
- 事件必须先落 PostgreSQL，再 publish Redis。
- 文件删除必须是真删除，不能只删除数据库记录。
- Frontend 不应知道 AgentSDK 或 CubeSandbox 地址。
