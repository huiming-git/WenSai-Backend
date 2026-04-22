# WenSai Backend

基于 FastAPI 的论文提交与评审后端服务，支持用户注册登录、论文上传（PDF/PPTX）、人工评审以及 LLM 驱动的 AI 评审。

## 特性

- JWT 鉴权，注册支持邀请码
- 论文 CRUD、草稿 / 定稿状态、附件上传与下载
- 人工评审与 AI 评审（OpenAI 兼容接口）
- 文件存储支持本地磁盘与 S3（兼容 MinIO）
- SQLAlchemy + Alembic 数据库迁移（SQLite / PostgreSQL）
- SlowAPI 限流，CORS，结构化日志

## 技术栈

Python 3.12 · FastAPI · SQLAlchemy 2 · Alembic · Pydantic v2 · OpenAI SDK · PyPDF2 / python-pptx · boto3 · slowapi · passlib + python-jose

## 目录结构

```
app/
  main.py            FastAPI 入口、中间件、路由注册
  config.py          环境变量与配置
  database.py        SQLAlchemy 引擎与 Session
  dependencies.py    依赖（当前用户等）
  limiter.py         SlowAPI 限流器
  logging_config.py  日志配置
  storage.py         本地 / S3 存储抽象
  utils.py           密码哈希、JWT 等工具
  models/            ORM 模型：user / paper / review
  schemas/           Pydantic 模型
  routers/           auth / papers / reviews
  services/agent.py  LLM 评审服务
alembic/             数据库迁移
tests/               pytest 测试
Dockerfile           容器镜像
```

## 快速开始

### 1. 环境准备

```bash
python3.12 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 2. 配置 `.env`

在项目根目录创建 `.env`：

```ini
SECRET_KEY=请替换为强随机字符串
DATABASE_URL=sqlite:///./wensai.db
UPLOAD_DIR=./uploads
INVITE_CODE=huiming

# LLM（OpenAI 兼容）
LLM_API_KEY=sk-xxx
LLM_BASE_URL=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# 存储：local 或 s3
STORAGE_BACKEND=local
# S3_BUCKET=
# S3_ENDPOINT_URL=
# S3_ACCESS_KEY=
# S3_SECRET_KEY=
# S3_REGION=us-east-1

# CORS（逗号分隔）
CORS_ORIGINS=http://localhost:1420,http://localhost:5173
```

### 3. 初始化数据库

```bash
alembic upgrade head
```

### 4. 启动开发服务器

```bash
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

访问 `http://localhost:8000/docs` 查看 Swagger UI，`http://localhost:8000/api/health` 健康检查。

## 主要接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/auth/register` | 注册（需邀请码） |
| POST | `/api/auth/login` | 登录，返回 JWT |
| GET | `/api/auth/me` | 当前用户 |
| GET | `/api/papers` | 论文列表 |
| POST | `/api/papers` | 创建论文 |
| GET | `/api/papers/{id}` | 论文详情 |
| PUT | `/api/papers/{id}` | 更新论文 |
| DELETE | `/api/papers/{id}` | 删除论文 |
| POST | `/api/papers/{id}/finalize` | 定稿 |
| POST | `/api/papers/{id}/upload` | 上传附件 |
| GET | `/api/papers/{id}/file` | 下载附件 |
| GET/POST | `/api/papers/{id}/reviews` | 评审列表 / 创建 |
| POST | `/api/papers/{id}/ai-review` | AI 评审 |
| PUT/DELETE | `/api/reviews/{id}` | 更新 / 删除评审 |

## 测试

```bash
pytest
```

## 数据库迁移

```bash
# 根据模型变更生成迁移
alembic revision --autogenerate -m "描述"
# 应用迁移
alembic upgrade head
```

## 部署

生产部署指引见 [AGENT.md](./AGENT.md)。

## 分支

- `dev`：开发分支
- `release`：发布分支
