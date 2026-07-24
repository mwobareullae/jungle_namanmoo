# Backend Uvicorn Worker Operations

## Scope

The server deployment combines `docker-compose.yml` with
`docker-compose.proxy.yml`. The proxy override disables development reload and
starts one Uvicorn master with `UVICORN_WORKERS` worker processes.

The initial server value is two workers:

```dotenv
UVICORN_WORKERS=2
```

This setting is consumed by Docker Compose when it renders the server command;
it is not an application-level FastAPI setting.

## Why Two Workers First

Two workers let independent HTTP requests progress in parallel. They do not
make a single recommendation, search, or LLM request twice as fast. Starting
with two is deliberate because the same EC2 also hosts Elasticsearch and Redis.

Do not combine `--workers` and `--reload`. Local development continues to use
the Dockerfile command with `--reload`; the worker override applies only when
`docker-compose.proxy.yml` is included.

## Interaction With Existing Runtime Controls

- The Redis Agent workflow lease remains globally capped at three concurrent
  workflows across every Uvicorn worker.
- Candidate Redis caches remain shared; process-local caches and provider
  circuit breakers are still per worker.
- Each worker creates its own SQLAlchemy engine and connection pool. Check RDS
  connection usage before increasing the worker count beyond two.

## Apply On The Server

From `/home/ubuntu/mwobareullae`, set the root `.env` value and recreate only
the backend service:

```bash
if grep -q '^UVICORN_WORKERS=' .env; then
  sed -i 's/^UVICORN_WORKERS=.*/UVICORN_WORKERS=2/' .env
else
  echo 'UVICORN_WORKERS=2' >> .env
fi

docker compose \
  -f docker-compose.yml \
  -f docker-compose.proxy.yml \
  --profile server \
  config >/tmp/mwobareullae-server-compose.yml

docker compose \
  -f docker-compose.yml \
  -f docker-compose.proxy.yml \
  --profile server \
  up -d --force-recreate backend
```

The recreate can cause a short API interruption while the backend health check
recovers. It does not require a migration, seed, or Elasticsearch reindex.

## Verify

```bash
docker compose \
  -f docker-compose.yml \
  -f docker-compose.proxy.yml \
  --profile server \
  top backend

curl -fsS http://127.0.0.1:8000/api/health

docker compose \
  -f docker-compose.yml \
  -f docker-compose.proxy.yml \
  --profile server \
  logs --tail=100 backend
```

`docker compose top backend` should show one Uvicorn parent process and two
worker processes. Confirm p95 latency, error rate, backend memory, CPU, and RDS
connection counts before considering three workers.

## Rollback

Set `UVICORN_WORKERS=1` in the root `.env` and run the same `up -d
--force-recreate backend` command. No schema or data rollback is involved.
