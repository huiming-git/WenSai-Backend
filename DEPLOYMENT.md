# WenSai Backend 部署文档

Backend 是业务控制服务和实时事件中心，负责公开 API、JWT 鉴权、任务状态、审批、文件、事件持久化和 WebSocket 推送。Backend 不直接启动 Hermes，也不直接执行 Agent。

## 依赖服务

- PostgreSQL：保存用户、任务、事件、审批、文件记录。
- Redis：用于 `task:{task_id}:events` Pub/Sub 和 Celery broker。
- AgentSDK：Backend 通过 internal API 派发任务。
- Nginx/Ingress：对外暴露 HTTPS、API、WebSocket。

## 环境变量

复制并修改：

```bash
cp .env.example .env
```

生产必须修改：

```ini
SECRET_KEY=用 openssl rand -hex 32 生成
POSTGRES_USER=wensai
POSTGRES_PASSWORD=强密码
POSTGRES_DB=wensai
DATABASE_URL=postgresql+psycopg2://wensai:强密码@postgres:5432/wensai
REDIS_URL=redis://redis:6379/0
AGENTSDK_BASE_URL=http://agentsdk:8010
INTERNAL_API_TOKEN=强随机服务间 token
CORS_ORIGINS=https://你的前端域名
UPLOAD_DIR=/app/uploads
STORAGE_BACKEND=local
```

`INTERNAL_API_TOKEN` 必须和 AgentSDK 配置一致。

## Docker Compose

当前仓库内 `docker-compose.yml` 覆盖：

- `db`
- `redis`
- `api`
- `worker`

启动：

```bash
docker compose up --build -d
docker compose exec api alembic upgrade head
```

健康检查：

```bash
curl http://127.0.0.1:8000/api/health
docker compose exec redis redis-cli ping
docker compose exec db pg_isready -U wensai
```

完整系统部署推荐使用仓库根目录的 `docker-compose.prod.yml`，它会统一编排 `db / redis / api / worker / agentsdk`。生产版官方 CubeSandbox 不在 Compose 内运行，应按官方文档安装在宿主机 / 裸机层，然后让 AgentSDK 通过 E2B 兼容 API 访问。

如果继续使用当前目录内的 Backend-only `docker-compose.yml`，需要在上层编排里额外加入 `agentsdk` 服务，并设置：

```ini
AGENTSDK_BASE_URL=http://agentsdk:8010
```

## 当前生产沙盒策略

当前生产机使用本地沙盒方案：

```ini
SANDBOX_BACKEND=local
LOCAL_SANDBOX_DIRNAME=local-sandbox
LOCAL_SANDBOX_ENFORCE_PROCESS=false
```

原因是当前宿主机资源不足以部署官方 CubeSandbox：安装器要求至少 8GB 内存，且 `/data/cubelet` 需要位于 XFS 文件系统；当前机器约 4GB 内存，根文件系统为 ext4。同时 80/443 已由 1Panel OpenResty 占用，CubeProxy 需要另行规划端口或反向代理。

在扩容并准备 XFS 数据目录前，不要把生产环境切换到 `SANDBOX_BACKEND=cube`。本地沙盒可以跑通 Hermes ACP 链路，但隔离级别不是 CubeSandbox MicroVM。

## 公开 API

Frontend 只访问 Backend：

- `POST /api/tasks`
- `GET /api/tasks/{task_id}`
- `GET /api/tasks/{task_id}/events`
- `WS /ws/tasks/{task_id}/events?token=<jwt>`
- `GET /api/tasks/{task_id}/approvals`
- `POST /api/tasks/{task_id}/approvals/{approval_id}/approve`
- `POST /api/tasks/{task_id}/approvals/{approval_id}/reject`
- `POST /api/tasks/{task_id}/cancel`
- `GET /api/tasks/{task_id}/files`

WebSocket 只做 Backend -> Frontend 推送，审批和取消仍走 HTTP。

## Internal API

AgentSDK 调用 Backend internal API 必须带：

```http
X-Internal-Token: <INTERNAL_API_TOKEN>
```

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

所有事件必须经过 `EventService`，先写 PostgreSQL，再 publish 到 Redis。

## Nginx

```nginx
location /api/ {
    proxy_pass http://127.0.0.1:8000/api/;
    proxy_set_header Host $host;
    proxy_set_header X-Real-IP $remote_addr;
    proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
}

location /ws/ {
    proxy_pass http://127.0.0.1:8000/ws/;
    proxy_http_version 1.1;
    proxy_set_header Upgrade $http_upgrade;
    proxy_set_header Connection "upgrade";
    proxy_set_header Host $host;
    proxy_read_timeout 3600s;
}
```

生产日志不要记录完整 WebSocket URL query token。

## 实时链路验证

1. 启动 PostgreSQL、Redis、Backend、AgentSDK。
2. 前端创建 Hermes ACP 任务。
3. `GET /api/tasks/{task_id}/events` 应看到：

```text
task_created
task_queued
task_started
agent_runtime_started
agent_thinking
tool_call_started
tool_call_finished
file_created
agent_message
agent_runtime_stopped
file_saved
task_completed
```

## 运维命令

```bash
docker compose logs -f api
docker compose restart api
docker compose exec api alembic upgrade head
docker compose exec db pg_dump -U wensai wensai > backup.sql
cat backup.sql | docker compose exec -T db psql -U wensai wensai
```

## 安全要求

- PostgreSQL、Redis 不暴露公网。
- AgentSDK 不暴露公网。
- `INTERNAL_API_TOKEN` 使用强随机值。
- Frontend 不直接连接 AgentSDK。
- Backend 不处理 Hermes 原始事件，只保存统一 `task_events`。
- 高风险操作必须通过 approval。
