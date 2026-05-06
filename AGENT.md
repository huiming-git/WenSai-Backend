# WenSai Backend Agent Guide

本文面向维护 Backend 的代码 Agent。Backend 是问赛的数据、权限和事件控制面，改动时优先保证一致性和安全边界。

## 职责边界

Backend 负责：

- 认证、用户、积分、工作区。
- 论文、评审和 AI review。
- Agent task 状态机、事件、审批和文件记录。
- WebSocket 事件推送。
- 文件存储、下载、预览和真实删除。
- 调用 AgentSDK internal API。

Backend 不负责：

- 运行 Hermes。
- 消费 Hermes ACP 原始事件。
- 直接操作官方 CubeSandbox。
- 向 Frontend 暴露 AgentSDK 地址或 internal token。

## 不变量

- Frontend 只能访问 Backend public API。
- Backend 调 AgentSDK 时只通过 internal API，并携带 `X-Internal-Token`。
- AgentSDK 通过 `/api/internal/*` 回写状态、事件、结果、错误、审批和文件。
- 所有 task events 必须先写 PostgreSQL，再 publish Redis。
- 文件删除必须同时处理 Backend storage/DB 和 AgentSDK sandbox 文件。
- 工作区权限必须通过 owner 或 `WorkspaceMember` 校验。
- `INTERNAL_API_TOKEN` 只能存在服务端配置中，不能进入前端响应。

## 关键文件

| 路径 | 说明 |
| --- | --- |
| `app/main.py` | FastAPI 初始化、CORS、路由注册、启动重派发 queued tasks |
| `app/config.py` | 环境变量 |
| `app/database.py` | DB engine/session |
| `app/storage.py` | local/S3 存储抽象 |
| `app/tasks/router.py` | task public API |
| `app/tasks/service.py` | task 状态变更和 response |
| `app/tasks/dispatcher.py` | 调 AgentSDK、转发/删除沙盒文件 |
| `app/internal_api/router.py` | AgentSDK 回写接口 |
| `app/events/service.py` | 事件写库和 Redis publish |
| `app/realtime/router.py` | WebSocket |
| `app/files/router.py` | 文件上传、新建、预览、下载、删除 |
| `app/workspaces/service.py` | 工作区创建、active workspace、root path |
| `alembic/versions/` | DB migrations |
| `tests/` | pytest |

## Agent 任务状态

常见状态：

```text
pending -> queued -> running -> waiting_approval -> running -> completed
                                  |                 -> failed
                                  -> cancelled
```

注意：

- `POST /api/tasks` 创建任务并派发。
- `POST /api/tasks/{task_id}/start` 用于 pending upload 流程。
- Backend 启动时 `redispatch_queued_tasks` 会重派发未 started 的 queued tasks。
- `cancel` 当前只更新 Backend 状态并调用 AgentSDK cancel endpoint；具体 runtime 取消能力在 AgentSDK。

## 文件规则

上传/新建：

```text
Frontend -> Backend storage + TaskFile DB -> AgentSDK /sandbox/files
```

删除：

```text
Frontend -> Backend /api/files/{id}
  -> AgentSDK DELETE /sandbox/files
  -> Backend storage delete
  -> Backend DB delete
```

删除任务：

```text
Backend delete Task
  -> AgentSDK DELETE /sandbox
  -> storage / DB cleanup
```

不要只删前端、只删 DB，或只删 storage。

## Internal API

所有 `/api/internal/*` 必须依赖 `require_internal_token`。

主要接口：

- `GET /api/internal/tasks/{task_id}`
- `POST /api/internal/tasks/{task_id}/status`
- `POST /api/internal/tasks/{task_id}/events`
- `POST /api/internal/tasks/{task_id}/result`
- `POST /api/internal/tasks/{task_id}/error`
- `POST /api/internal/tasks/{task_id}/approvals`
- `GET /api/internal/approvals/{approval_id}`
- `GET /api/internal/approvals/{approval_id}/wait`
- `POST /api/internal/tasks/{task_id}/files`

新增 internal endpoint 时必须：

- 使用 internal token。
- 避免返回用户 JWT、internal token、LLM key。
- 写测试覆盖未授权访问。

## 事件规则

事件来源统一进入 `EventService`。不要让 router 直接绕过事件服务写 Redis。

事件应包含：

- `task_id`
- `type`
- `content`
- `metadata`
- `created_at`

WebSocket 只推送 Backend 已落库事件。Frontend 会按 `event.id` 去重。

## 预览规则

`app/files/router.py` 负责：

- 文本/图片直接预览。
- PDF 预览。
- Office 通过 LibreOffice 转 PDF/图片。
- OpenXML 文本提取。
- 页图缓存到 `PREVIEW_CACHE_DIR`。

涉及预览时注意：

- 不要信任用户文件名，所有路径必须 safe normalize。
- 生成文件放入临时目录或 preview cache。
- 大文件和长文本要截断显示。
- 修改 preview 输出 schema 时同步前端 `FilePreview` 类型。

## 数据库和迁移

改 SQLModel model 后通常需要 Alembic migration：

```bash
alembic revision --autogenerate -m "describe change"
alembic upgrade head
```

迁移要检查：

- 外键名是否稳定。
- nullable/default 是否兼容已有数据。
- 删除字段是否需要数据迁移。

## 本地运行

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
alembic upgrade head
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

## 验证

常规：

```bash
pytest
```

按范围：

```bash
pytest tests/test_auth.py
pytest tests/test_tasks_platform.py tests/test_workspaces.py
pytest tests/test_papers.py tests/test_reviews.py
```

涉及迁移时：

```bash
alembic upgrade head
```

涉及生产 compose 时，在有 Docker 的环境执行：

```bash
docker compose --env-file ../.env.production -f ../docker-compose.prod.yml config
```

## 安全要求

- 不要把 `SECRET_KEY`、`INTERNAL_API_TOKEN`、`LLM_API_KEY` 写入日志或响应。
- PostgreSQL、Redis、AgentSDK 不对公网开放。
- 生产 CORS 必须是精确域名。
- WebSocket URL 带 JWT，生产访问日志不要记录完整 query token。
- 文件路径必须防止 `..`、绝对路径和反斜杠绕过。
- 审批是高风险操作的边界，不能默认 allow。

## 禁止事项

- 不要在 Backend 中引入 Hermes ACP client。
- 不要让 Backend 直接调用官方 CubeSandbox。
- 不要让 Frontend 看到 AgentSDK base URL。
- 不要用 mock/fake runtime 伪造任务成功。
- 不要把文件删除改成只删 UI 或只删数据库。
