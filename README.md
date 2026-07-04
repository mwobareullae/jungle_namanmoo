# 뭐바를래

내 피부 고민에 맞는 화장품을 성분 근거와 구매 흐름까지 이어서 추천하는 P2 자사몰 프로젝트입니다.

- 서비스 식별자: `mwobareullae`
- 현재 방향: P2 자사몰 완성 -> P3 자사몰 고도화 -> P4+ 마켓플레이스 확장
- 실행 기준: 루트 `docker-compose.yml`
- 환경변수 기준: 루트 `.env.example`

## 현재 단계

현재 repo는 초기 stub 단계를 지나 P2 자사몰 구현과 P3 고도화 준비를 함께 진행 중입니다.

- Frontend: Vite, React, TypeScript 기반 고객 화면
- Backend: FastAPI, SQLAlchemy, Alembic 기반 API
- Database: PostgreSQL + pgvector image
- Data: CSV/JSON seed, 상품/성분/이미지/검색 문서 데이터
- Infra: Docker Compose, GitHub Actions CI/CD, EC2 dev 배포
- Dev infra profile: Redis, Elasticsearch 컨테이너를 `dev-infra` profile로 추가
- Image assets: S3 + CloudFront 기준 운영 설계

현재 백엔드는 `health`, `auth`, `home`, `recommendations`, `products` API를 포함합니다. 프론트는 홈, 추천/검색, 상품 상세, 로그인/회원가입, checkout/payment mock 화면을 포함하며, 커뮤니티 모드에서는 커머스 행동을 제한합니다.

## 기준 문서

- 작업 규칙과 역할 범위: `AGENTS.MD`
- 데이터 계약: `docs/data-contract.md`
- 배포 결정 기록: `docs/deployment-summary.md`
- 이벤트/GA4 로드맵: `docs/analytics-event-roadmap.md`
- P2 AI commerce 계약: `docs/p2-ai-commerce-contract.md`
- 프론트 상세: `apps/frontend/README.md`
- 백엔드 상세: `apps/backend/README.md`

문서와 코드가 다르면 실제 코드, migration, 테스트를 먼저 확인하고 문서를 갱신합니다.

## 로컬 개발 환경

### 1. 환경변수 파일 만들기

```bash
cp .env.example .env
```

`.env`는 로컬 또는 서버에서만 사용합니다. 실제 API key, secret, credential은 커밋하지 않습니다.

루트 `.env.example` 하나를 Docker Compose 실행 기준 source of truth로 둡니다.

- `VITE_*`: 브라우저에 노출되는 프론트 공개값입니다. secret을 넣지 않습니다.
- `DATABASE_URL`: 백엔드가 실제로 사용하는 DB 연결 문자열입니다.
- `POSTGRES_*`: Docker Compose의 postgres 컨테이너 초기화/포트 설정값입니다.
- `BACKEND_CORS_ORIGINS`: 브라우저에서 API 호출을 허용할 프론트 origin 목록입니다.
- `REDIS_*`, `ELASTICSEARCH_*`: Dev 통합 확인용 Redis/Elasticsearch 연결과 prefix 기준입니다.
- `COMPOSE_PROFILES=dev-infra`: Redis/Elasticsearch 서비스를 함께 띄우는 Dev 서버용 profile입니다.
- `DEV_HOST`, `DEV_SSH_KEY` 같은 배포 secret은 `.env.example`에 넣지 않고 GitHub Secrets에만 둡니다.
- EC2 서버의 `.env`는 배포 workflow가 덮어쓰지 않습니다. 서버에서 직접 관리합니다.

### 2. Docker Compose 설정 확인

```bash
docker compose config
```

proxy 구성을 함께 확인할 때:

```bash
docker compose -f docker-compose.yml -f docker-compose.proxy.yml config
```

### 3. 전체 개발환경 실행

```bash
docker compose up --build
```

루트 `.env`에 `COMPOSE_PROFILES=dev-infra`가 있으면 Redis와 Elasticsearch도 함께 실행됩니다. t3.xlarge Dev 서버는 이 profile을 켜고, 메모리가 부족한 로컬에서는 `COMPOSE_PROFILES=`로 비워서 app/postgres만 실행할 수 있습니다.

- Frontend: <http://localhost:5173>
- Backend: <http://localhost:8000>
- Backend health: <http://localhost:8000/api/health>
- Postgres: `localhost:5432`
- Redis: `127.0.0.1:6379`
- Elasticsearch: <http://127.0.0.1:9200>

DB만 실행할 때:

```bash
docker compose up -d postgres
```

중지:

```bash
docker compose down
```

DB volume까지 초기화해야 할 때만 아래 명령을 사용합니다.

```bash
docker compose down -v
```

## 환경변수 운영 기준

서버 `.env`에서 FastAPI 추천/검색 튜닝값을 조절하려면 `.env.example`과 `docker-compose.yml`의 `backend.environment`가 함께 맞아야 합니다.

```text
server .env
-> docker compose variable substitution
-> backend container environment
-> FastAPI config.py os.getenv()
-> recommendation/search logic
```

현재 조절 가능한 추천/검색 값:

```env
HYBRID_KEYWORD_WEIGHT=0.5
HYBRID_VECTOR_WEIGHT=0.5
RECOMMENDATION_CANDIDATE_POOL_LIMIT=500
EMBEDDING_DIMENSIONS=1536
```

`EMBEDDING_DIMENSIONS`는 vector DB/index 생성 후 마음대로 바꾸면 안 됩니다. 변경이 필요하면 migration 또는 index rebuild 계획을 같이 잡아야 합니다.

### Auth / CORS

프론트 Auth 요청은 `fetch(..., { credentials: "include" })` 기준으로 이동 중입니다. 백엔드는 CORS `allow_credentials=True`로 동작하므로, 배포 환경의 `BACKEND_CORS_ORIGINS`에는 실제 프론트 origin을 정확히 넣어야 합니다.

```env
# Local/dev default
BACKEND_CORS_ORIGINS=http://localhost:5173

# Release server .env
BACKEND_CORS_ORIGINS=https://mubarelle.com,https://www.mubarelle.com
```

credentials 요청에는 wildcard origin `*`를 쓰지 않습니다. HTTPOnly cookie 인증의 `Set-Cookie`, 만료, `SameSite`, `Secure`, `/me` cookie 처리 전환은 백엔드 Auth 작업에서 별도로 추적합니다.

Docker 로그와 메모리 제한은 `.env`에서 조절합니다.

```env
DOCKER_LOG_MAX_SIZE=10m
DOCKER_LOG_MAX_FILE=5
FRONTEND_MEMORY_LIMIT=1g
BACKEND_MEMORY_LIMIT=2g
POSTGRES_MEMORY_LIMIT=2g
REDIS_MEMORY_LIMIT=512m
ELASTICSEARCH_MEMORY_LIMIT=2g
ELASTICSEARCH_HEAP_SIZE=1g
```

Redis와 Elasticsearch는 첫 단계에서 Dev 인프라만 제공합니다. 실제 cache/rate limit, ES 검색 ranking 연결은 담당 기능 PR에서 별도로 진행합니다.

```env
REDIS_URL=redis://redis:6379/0
REDIS_KEY_PREFIX=mubarelle:dev:
ELASTICSEARCH_URL=http://elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=mubarelle_dev
```

## CI

현재 GitHub Actions CI는 `main`, `dev` push와 PR에서 실행됩니다.

- frontend dependency install
- frontend lint
- frontend build
- 필수 파일 존재 확인
- 실제 `.env` 파일 커밋 여부 확인
- `docker compose config`
- Docker Compose 서비스 기동
- backend health check
- backend pytest
- Alembic heads 확인
- frontend page check

로컬에서 PR 전 최소 확인:

```bash
docker compose config
docker compose up --build -d
curl http://localhost:8000/api/health
docker compose exec -T backend python -m pytest
docker compose exec -T backend python -m alembic heads
curl http://localhost:5173
docker compose down
```

## Dev 서버 배포

현재 production 자동 배포는 만들지 않습니다. `dev` 브랜치에 push되면 GitHub Actions가 EC2 개발 서버로 소스를 동기화한 뒤 Docker Compose를 재실행합니다.

```text
dev push -> GitHub Actions checkout -> rsync to EC2 -> docker compose up --build -d
```

### EC2 구성 기준

- AWS EC2 1대
- Docker + Docker Compose
- `frontend`, `backend`, `postgres` 컨테이너를 같은 EC2에서 실행
- `COMPOSE_PROFILES=dev-infra`일 때 `redis`, `elasticsearch` 컨테이너를 같은 EC2에서 실행
- DB는 RDS가 아니라 EC2 내부 Postgres container로 시작
- EC2에 repository clone은 필수 아님
- 서버 `.env`는 EC2에서 직접 관리

최초 준비 예시:

```bash
sudo apt update
sudo apt install -y ca-certificates curl rsync
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
```

권한 적용을 위해 SSH 재접속 후 확인합니다.

```bash
docker --version
docker compose version
```

### GitHub Secrets

Repository Settings > Secrets and variables > Actions에 아래 값을 등록합니다.

```text
DEV_HOST      EC2 public IP 또는 DNS
DEV_USER      예: ubuntu
DEV_SSH_KEY   EC2 접속 private key
DEV_APP_DIR   예: /home/ubuntu/mwobareullae
SLACK_WEBHOOK_URL   선택: PR/댓글/dev 배포 완료 Slack 알림용 incoming webhook
```

`DEV_SSH_KEY`는 공개키가 아니라 private key입니다. 레포 파일에 넣지 않습니다.

### 보안그룹 기준

초기 dev 확인 단계:

```text
22    SSH, 관리자 IP 또는 GitHub Actions 접근 방식에 맞게 제한
5173  frontend, 팀원 IP 또는 임시 공개
8000  backend, 팀원 IP 또는 임시 공개
5432  postgres, 외부 공개 금지
6379  redis, 외부 공개 금지
9200  elasticsearch, 외부 공개 금지
```

Caddy/Nginx를 붙인 뒤:

```text
22    관리자 IP만 허용
80    전체 허용
443   전체 허용
5173  외부 차단
8000  외부 차단
5432  외부 차단
6379  외부 차단
9200  외부 차단
```

## 이미지 자산 인프라

P2 상품 이미지 적재와 공개 서빙은 EC2 로컬 디스크가 아니라 S3 + CloudFront 기준입니다.

- S3 bucket: `mubarelle-images`
- Region: `ap-northeast-2`
- CloudFront domain: `https://d3hg0esuwey1za.cloudfront.net`
- 원본: `original/{storage_key}`
- 공개 이미지: `resized/w400/{storage_key}`, `resized/w1200/{storage_key}`
- 브라우저 공개 base URL: `VITE_IMAGE_CDN_BASE_URL`

서비스 DB에는 CloudFront 절대 URL을 저장하지 않고 `storage_key` 기준을 유지합니다.

## 개발 흐름

1. `dev` 브랜치에서 작업 브랜치를 생성합니다.
2. 브랜치 이름은 `feat/*`, `fix/*`, `docs/*`, `chore/*` 규칙을 따릅니다.
3. 담당 영역만 수정합니다.
4. 커밋 메시지는 Angular 스타일과 한글 요약을 사용합니다.
5. PR을 열고 CI 통과 후 `dev`에 머지합니다.
6. `main`에 직접 push하지 않습니다.

예시:

```text
chore(infra): 환경변수 예시와 README 정리
feat(backend): 인증 사용자 모델 추가
docs(data): 자사몰 판매 구조 기준 정리
```

## 아직 하지 않는 것

- production 자동 배포
- RDS
- ECS/Fargate
- ALB
- ECR
- 자동 DB 백업
- production Elasticsearch 운영 클러스터
- production Redis 운영 구성
- Redis cache/rate limit 기능 연결
- Elasticsearch 검색 ranking 기능 연결
- event log 저장 API와 GA4 전체 매핑

이 항목들은 P2/P3 일정과 발표 전 안정화 기준에 맞춰 별도 이슈와 PR로 결정합니다.
