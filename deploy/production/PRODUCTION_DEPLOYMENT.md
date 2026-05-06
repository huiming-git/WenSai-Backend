# WenSai Production Deployment

Production uses official CubeSandbox as a host-level MicroVM service. Do not run CubeSandbox itself inside the AgentSDK Docker container.

## Architecture

```text
Nginx / HTTPS
  /       -> WenSai-App dist-app
  /api    -> Backend api on 127.0.0.1:8000
  /ws     -> Backend websocket on 127.0.0.1:8000

docker compose -f deploy/production/docker-compose.prod.yml
  db
  redis
  api
  worker
  agentsdk

host / bare-metal
  official CubeSandbox
    CubeMaster
    Cubelet
    CubeShim
    network-agent
    E2B-compatible API on :3000
```

AgentSDK is only a caller of the CubeSandbox API in production. The local directory sandbox remains a development fallback and is named `local-sandbox` to avoid confusing it with official CubeSandbox.

## Host prerequisites

- x86_64 Linux bare-metal server or a machine with KVM available.
- `/dev/kvm` exists.
- Docker and Docker Compose plugin.
- Official CubeSandbox installed on the host and healthy.

CubeSandbox official checks:

```bash
ls /dev/kvm
curl http://127.0.0.1:3000/health
```

## Configure

```bash
cp .env.production.example .env.production
```

Required edits:

```ini
SECRET_KEY=<openssl rand -hex 32>
POSTGRES_PASSWORD=<strong password>
INTERNAL_API_TOKEN=<openssl rand -hex 32>
CORS_ORIGINS=https://your-domain.example.com
LLM_API_KEY=<your llm key>

SANDBOX_BACKEND=cube
CUBE_API_URL=http://host.docker.internal:3000
CUBE_API_KEY=dummy
CUBE_TEMPLATE_ID=<official CubeSandbox template id>
```

`host.docker.internal` is mapped to the Docker host by `extra_hosts` in `docker-compose.prod.yml`.

The compose file lives in this Backend repository. It needs a local checkout of the AgentSDK repository:

```bash
mkdir -p /opt/wensai
cd /opt/wensai
git clone -b release https://github.com/huiming-git/WenSai-Backend.git
git clone -b release https://github.com/huiming-git/WenSai-AgentSDK.git
```

From `WenSai-Backend/deploy/production`, the default AgentSDK context is `../../../WenSai-AgentSDK` via `AGENTSDK_BUILD_CONTEXT`. Adjust it in `.env.production` if your directory name differs.

## Start backend stack

```bash
cd /opt/wensai/WenSai-Backend/deploy/production
cp .env.production.example .env.production
docker compose --env-file .env.production -f docker-compose.prod.yml up --build -d
docker compose --env-file .env.production -f docker-compose.prod.yml exec api alembic upgrade head
```

Health checks:

```bash
curl http://127.0.0.1:8000/api/health
docker compose --env-file .env.production -f docker-compose.prod.yml ps
```

## Build frontend

```bash
cd /opt/wensai/WenSai-App
npm ci
VITE_API_BASE_URL=https://your-domain.example.com/api npm run build
sudo mkdir -p /var/www/wensai
sudo rsync -av dist-app/ /var/www/wensai/
```

## Nginx

Serve `/var/www/wensai` and proxy `/api/` plus `/ws/` to `127.0.0.1:8000`. Keep `client_max_body_size 1024m` for large documents.

## Development fallback

For local testing without official CubeSandbox:

```ini
SANDBOX_BACKEND=local
LOCAL_SANDBOX_DIRNAME=local-sandbox
LOCAL_SANDBOX_ENFORCE_PROCESS=true
```

This is not equivalent to official CubeSandbox MicroVM isolation.
