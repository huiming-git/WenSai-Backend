# 部署指引（AGENT.md）

面向运维 / 部署执行者的操作手册。覆盖 Docker、Docker Compose、裸机（systemd + Nginx）三种方式。默认部署目标为 Linux 服务器。

## 0. 部署前检查清单

- [ ] Python 3.12 可用（裸机方式）或已安装 Docker 24+
- [ ] 已准备生产 `SECRET_KEY`（建议 `openssl rand -hex 32`）
- [ ] 已准备 LLM API Key（若启用 AI 评审）
- [ ] 数据库：生产推荐 PostgreSQL 14+
- [ ] 反向代理：Nginx / Caddy，已配置 HTTPS（Let's Encrypt）
- [ ] 已开放 80 / 443 端口；应用监听端口（8000）仅对本机/内网可达
- [ ] 备份策略：数据库 + `uploads/` 目录（或 S3）

## 1. 环境变量

生产环境变量写入 `.env`（同目录）或通过容器编排注入。关键项：

| 变量 | 说明 | 生产建议 |
| --- | --- | --- |
| `SECRET_KEY` | JWT 签名密钥 | **必填**，强随机 32+ 字节 |
| `DATABASE_URL` | 数据库连接串 | `postgresql+psycopg2://user:pwd@host:5432/wensai` |
| `UPLOAD_DIR` | 本地上传目录 | `/var/lib/wensai/uploads`（本地存储时） |
| `INVITE_CODE` | 注册邀请码 | 自定义 |
| `LLM_API_KEY` | OpenAI 兼容 Key | 保密 |
| `LLM_BASE_URL` | LLM 端点 | 默认 `https://api.openai.com/v1` |
| `LLM_MODEL` | 模型 | 如 `gpt-4o` |
| `STORAGE_BACKEND` | `local` / `s3` | 多实例部署必须用 `s3` |
| `S3_BUCKET` / `S3_ENDPOINT_URL` / `S3_ACCESS_KEY` / `S3_SECRET_KEY` / `S3_REGION` | S3 配置 | MinIO 需设 `S3_ENDPOINT_URL` |
| `CORS_ORIGINS` | 前端域名，逗号分隔 | 精确到线上域名 |

注意：`SECRET_KEY` 为默认值时启动会打印警告，务必更换。

## 2. Docker 部署

### 2.1 构建镜像

```bash
docker build -t wensai-backend:latest .
```

### 2.2 单容器 + SQLite（仅用于演示 / 小规模）

```bash
docker run -d \
  --name wensai-backend \
  --restart unless-stopped \
  -p 127.0.0.1:8000:8000 \
  --env-file .env \
  -v /var/lib/wensai/uploads:/app/uploads \
  -v /var/lib/wensai/db:/app/db \
  -e DATABASE_URL=sqlite:////app/db/wensai.db \
  wensai-backend:latest
```

首次启动后进入容器执行迁移：

```bash
docker exec -it wensai-backend alembic upgrade head
```

### 2.3 Docker Compose + PostgreSQL（推荐）

在项目根目录新建 `docker-compose.yml`：

```yaml
services:
  db:
    image: postgres:16-alpine
    restart: unless-stopped
    environment:
      POSTGRES_USER: wensai
      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD}
      POSTGRES_DB: wensai
    volumes:
      - db_data:/var/lib/postgresql/data
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U wensai"]
      interval: 5s
      retries: 10

  api:
    build: .
    restart: unless-stopped
    env_file: .env
    environment:
      DATABASE_URL: postgresql+psycopg2://wensai:${POSTGRES_PASSWORD}@db:5432/wensai
    depends_on:
      db:
        condition: service_healthy
    ports:
      - "127.0.0.1:8000:8000"
    volumes:
      - uploads:/app/uploads

volumes:
  db_data:
  uploads:
```

启动：

```bash
docker compose up -d --build
docker compose exec api alembic upgrade head
```

升级：

```bash
git pull
docker compose build api
docker compose up -d api
docker compose exec api alembic upgrade head
```

## 3. 裸机部署（systemd + Gunicorn + Nginx）

### 3.1 安装

```bash
sudo useradd -r -m -d /var/lib/wensai -s /usr/sbin/nologin wensai
sudo mkdir -p /opt/wensai && sudo chown wensai:wensai /opt/wensai
sudo -u wensai git clone -b release https://github.com/huiming-git/WenSai-Backend.git /opt/wensai/app
cd /opt/wensai/app
sudo -u wensai python3.12 -m venv venv
sudo -u wensai ./venv/bin/pip install -r requirements.txt gunicorn
sudo -u wensai cp /path/to/prod.env .env
sudo -u wensai ./venv/bin/alembic upgrade head
```

### 3.2 systemd 服务

`/etc/systemd/system/wensai.service`：

```ini
[Unit]
Description=WenSai Backend
After=network.target postgresql.service

[Service]
Type=simple
User=wensai
Group=wensai
WorkingDirectory=/opt/wensai/app
EnvironmentFile=/opt/wensai/app/.env
ExecStart=/opt/wensai/app/venv/bin/gunicorn app.main:app \
  -w 4 -k uvicorn.workers.UvicornWorker \
  -b 127.0.0.1:8000 \
  --access-logfile - --error-logfile -
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

启用：

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now wensai
sudo systemctl status wensai
```

### 3.3 Nginx 反向代理

`/etc/nginx/sites-available/wensai`：

```nginx
server {
  listen 80;
  server_name api.example.com;
  return 301 https://$host$request_uri;
}

server {
  listen 443 ssl http2;
  server_name api.example.com;

  ssl_certificate     /etc/letsencrypt/live/api.example.com/fullchain.pem;
  ssl_certificate_key /etc/letsencrypt/live/api.example.com/privkey.pem;

  client_max_body_size 50m;

  location / {
    proxy_pass         http://127.0.0.1:8000;
    proxy_http_version 1.1;
    proxy_set_header   Host              $host;
    proxy_set_header   X-Real-IP         $remote_addr;
    proxy_set_header   X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header   X-Forwarded-Proto $scheme;
    proxy_read_timeout 120s;
  }
}
```

启用并申请证书：

```bash
sudo ln -s /etc/nginx/sites-available/wensai /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
sudo certbot --nginx -d api.example.com
```

## 4. 数据库迁移

首次部署或版本更新后：

```bash
# Docker Compose
docker compose exec api alembic upgrade head

# 裸机
sudo -u wensai /opt/wensai/app/venv/bin/alembic upgrade head
```

回滚一个版本：

```bash
alembic downgrade -1
```

## 5. 备份

### 数据库（PostgreSQL）

```bash
pg_dump -U wensai -Fc wensai > /backup/wensai-$(date +%F).dump
```

建议通过 cron 每日执行并异地同步。

### 上传文件

- 本地存储：对 `uploads/` 使用 `rsync` / `restic` 异地备份
- S3：启用桶的版本控制与跨区域复制

## 6. 监控 / 日志

- 健康检查：`GET /api/health`，返回 `{"status":"ok"}`；接入 Uptime 监控
- 应用日志：应用输出 stdout/stderr，Docker 由编排收集；裸机通过 `journalctl -u wensai -f`
- 限流：注册 5/min，登录 10/min，AI 评审 5/min（见 `app/routers/*.py`）

## 7. 升级流程

```bash
# 1. 备份数据库与 uploads
# 2. 拉取最新 release 分支
git -C /opt/wensai/app fetch origin
git -C /opt/wensai/app checkout release
git -C /opt/wensai/app pull
# 3. 更新依赖（若 requirements.txt 变化）
sudo -u wensai /opt/wensai/app/venv/bin/pip install -r /opt/wensai/app/requirements.txt
# 4. 应用迁移
sudo -u wensai /opt/wensai/app/venv/bin/alembic upgrade head
# 5. 重启
sudo systemctl restart wensai
# 6. 验证 /api/health
curl -fsS http://127.0.0.1:8000/api/health
```

Docker Compose 版本：

```bash
git pull
docker compose build api
docker compose up -d api
docker compose exec api alembic upgrade head
```

## 8. 安全建议

- 关闭 Swagger / ReDoc 面向公网（如需要，前置鉴权或仅内网开放）
- `SECRET_KEY`、LLM Key、数据库密码不得入库
- 定期轮换 JWT `SECRET_KEY`（会使所有历史 token 失效）
- 数据库账号使用最小权限
- Nginx 开启 HTTPS、HSTS；限制 `client_max_body_size` 与单 IP 连接数
- 文件上传后端已校验大小与类型，但仍建议在代理层再加一道限流

## 9. 故障排查

| 现象 | 排查 |
| --- | --- |
| 启动日志警告 `SECRET_KEY is using the default value` | 未设置生产 `SECRET_KEY` |
| 上传文件 413 | 调大 Nginx `client_max_body_size` |
| AI 评审报错 401 / 429 | 检查 `LLM_API_KEY`、配额、`LLM_BASE_URL` |
| CORS 拒绝 | 将前端域名加入 `CORS_ORIGINS` |
| 多实例下附件丢失 | 切换至 `STORAGE_BACKEND=s3` |
| Alembic `target database is not up to date` | 执行 `alembic upgrade head` |

## 10. 回滚

```bash
# 裸机
git -C /opt/wensai/app checkout <上一个可用 tag 或 commit>
sudo -u wensai /opt/wensai/app/venv/bin/pip install -r requirements.txt
sudo -u wensai /opt/wensai/app/venv/bin/alembic downgrade <目标 revision>
sudo systemctl restart wensai
```

> 回滚数据库前务必确认迁移可逆，必要时从备份还原。
