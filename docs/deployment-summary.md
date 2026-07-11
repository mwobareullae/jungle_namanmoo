# Deployment Summary

이 문서는 P2 자사몰 개발 서버와 P3 인프라 준비 단계의 배포/운영 기준을 기록합니다.

문서보다 실제 코드, migration, GitHub Actions workflow, Docker Compose 설정을 우선합니다. 코드와 문서가 다르면 코드를 확인한 뒤 문서를 갱신합니다.

## 현재 결정 요약

```text
dev branch push
-> GitHub Actions checkout
-> rsync to EC2
-> data/dev-small 재생성
-> docker compose --profile server up -d --build
```

- Dev 서버는 `dev` 브랜치 merge/push 기준으로 GitHub Actions가 자동 배포합니다.
- Dev 서버 CD는 frontend container를 실행하지 않습니다. 프론트는 Vercel Production Branch `dev` 기준으로 배포합니다.
- `dev` 외 PR/feature 브랜치는 `apps/frontend` 변경이 있을 때 Vercel Preview 배포를 생성합니다.
- Dev DB는 RDS PostgreSQL을 사용합니다. Docker Postgres는 로컬/CI 전용 `local-db` profile에서만 실행합니다.
- GitHub Actions는 서버 `.env`를 덮어쓰지 않습니다.
- DB migration은 CD에 포함하지 않습니다. 스키마 변경 PR merge 후 R6 인프라 담당이 Dev 서버에서 수동 실행합니다.
- Seed는 배포 파이프라인에서 자동 실행하지 않습니다. 단, `data/dev-small` CSV subset은 배포 중 자동 재생성합니다.
- Production 자동 배포는 아직 만들지 않습니다.

## 서버 역할

### Dev 서버

- 목적: 팀원 6명 통합 개발/확인
- 인스턴스 기준: `t3.large` 2vCPU / 8GB
- 배포: `dev` 브랜치 push 시 GitHub Actions 자동 배포
- 현재 기본 구성: `backend`, `caddy`
- Search/cache 구성: 현재 `redis`, `elasticsearch`를 같은 EC2에서 실행하되, 후속 작업에서 별도 서버 또는 managed service 분리 검토
- Frontend: Vercel 배포 사용. Docker Compose의 `frontend` 서비스는 로컬 명시 실행용으로만 유지
- DB: RDS PostgreSQL + pgvector
- Docker Postgres: 로컬/CI 테스트용 `local-db` profile에서만 실행
- Auto scaling: 불필요

### 실유저 테스트 / 발표 서버

- Frontend: Vercel Production 배포 사용
- Backend: 안정 커밋 기준 별도 배포 또는 Dev API 동결 승격
- DB: RDS snapshot/PITR 또는 dump 기준으로 보호
- 발표용 동결 시: 배포 자동화 중단, hotfix 외 배포 금지, 데모 데이터/익명화 기준 확인

## Docker Compose Profile

| profile | 서비스 | 용도 |
| --- | --- | --- |
| `server` | `backend`, `redis`, `elasticsearch` | 서버 배포용. RDS 사용, Docker Postgres/Frontend 미실행 |
| `backend-dev` | `backend`, `postgres`, `redis`, `elasticsearch` | backend 개발과 검색/캐시 통합 확인 |
| `frontend-local-backend` | `frontend`, `backend`, `postgres` | frontend가 로컬 backend를 함께 확인 |
| `frontend-dev-server` | `frontend` | frontend만 실행하고 API는 개발 서버 사용 |
| `frontend`, `local-db`, `search-cache` | 일부 서비스 | 기존 명령 호환용 |

기본 `docker compose config --services` 결과는 비어 있어야 합니다. 서비스는 역할별 profile로만 실행합니다.

서버 배포 조합:

```bash
docker compose --profile server up -d --build
```

백엔드 개발 조합:

```bash
docker compose --profile backend-dev up -d --build
```

프론트가 로컬 backend를 사용할 때:

```bash
docker compose --profile frontend-local-backend up -d --build
```

프론트가 Dev API를 사용할 때:

```bash
docker compose --profile frontend-dev-server up -d --build
```

## Backend Env 기준

Dev 서버 backend container는 RDS endpoint가 들어간 `DATABASE_URL`을 사용합니다.

```env
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/<db_name>
DATA_DIR=/data
BACKEND_CORS_ORIGINS=https://dev.mubarelle.com
```

`DATA_DIR`는 DB 접속값이 아니라 seed/index/embedding 스크립트가 읽을 CSV 경로입니다. full/small DB를 전환할 때는 `DATABASE_URL`과 `DATA_DIR`을 같은 데이터 크기 기준으로 함께 맞춥니다.

```env
# full
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/mwobareullae
DATA_DIR=/data

# small
DATABASE_URL=postgresql+psycopg://<user>:<password>@<rds-endpoint>:5432/mwobareullae_small
DATA_DIR=/data/dev-small
```

## Redis / Elasticsearch 기준

현재 Dev 서버에서는 `server` profile로 Redis/Elasticsearch를 backend와 함께 실행합니다.

```env
REDIS_URL=redis://redis:6379/0
REDIS_KEY_PREFIX=mubarelle:dev:
ELASTICSEARCH_URL=http://elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=mubarelle_dev
```

- Redis bind: `127.0.0.1:${REDIS_PORT:-6379}`
- Elasticsearch bind: `127.0.0.1:${ELASTICSEARCH_PORT:-9200}`
- Redis memory limit: `${REDIS_MEMORY_LIMIT:-512m}`
- Elasticsearch memory limit: `${ELASTICSEARCH_MEMORY_LIMIT:-2g}`
- Elasticsearch heap: `${ELASTICSEARCH_HEAP_SIZE:-1g}`
- EC2 security group에서 `6379`, `9200` 외부 공개 금지

Redis/Elasticsearch를 별도 서버로 분리하면 backend `.env`의 `REDIS_URL`, `ELASTICSEARCH_URL`만 private endpoint 기준으로 바꿉니다.

## Prefix 기준

Redis key prefix와 Elasticsearch index prefix는 환경 경계입니다. 같은 Redis/Elasticsearch 인스턴스를 임시 공유하더라도 prefix는 공유하지 않습니다.

| 서버/역할 | Redis key prefix | Elasticsearch index prefix |
| --- | --- | --- |
| Dev 통합 서버 | `mubarelle:dev:` | `mubarelle_dev` |
| 실유저 테스트 | `mubarelle:user-test:` | `mubarelle_user_test` |
| 발표 서버 별도 동결 | `mubarelle:demo:` | `mubarelle_demo` |

prefix를 바꾸면 Redis는 cache miss가 발생하고, Elasticsearch는 새 index 생성 또는 reindex가 필요합니다. 배포 중 prefix 변경은 rollback 계획과 smoke test를 같이 잡은 경우에만 진행합니다.

## Auth / CORS 기준

프론트 Auth 요청은 `credentials: "include"` 기준입니다. 백엔드는 CORS `allow_credentials=True`로 동작하므로, 각 서버 `.env`의 `BACKEND_CORS_ORIGINS`에는 실제 프론트 origin만 넣습니다.

```env
# Local
BACKEND_CORS_ORIGINS=http://localhost:5173

# Dev frontend on Vercel
BACKEND_CORS_ORIGINS=https://dev.mubarelle.com

# Release
BACKEND_CORS_ORIGINS=https://mubarelle.com,https://www.mubarelle.com
```

credentials 요청에는 wildcard origin `*`를 사용하지 않습니다. `dev.mubarelle.com -> dev.api.mubarelle.com`처럼 같은 site의 HTTPS subdomain 구조면 cookie는 아래 기준을 권장합니다.

```env
AUTH_COOKIE_SECURE=true
AUTH_COOKIE_SAMESITE=lax
```

## Migration / Seed 운영

### DB migration

CD workflow는 migration을 실행하지 않습니다. 스키마 변경이 포함된 PR은 PR 설명과 리뷰 요청에 migration 포함 여부를 명시합니다.

Dev 서버 반영 명령:

```bash
docker compose exec backend python -m alembic upgrade head
```

수동 실행 주체를 R6 인프라 담당으로 고정합니다. 누락을 막기 위해 스키마 변경 PR merge 전후에는 Slack 등으로 migration 필요 여부를 공유합니다.

### Seed

Seed는 배포 자동화에 넣지 않습니다.

- seed 실행 여부는 데이터/백엔드 담당자가 배포 단위로 수동 판단
- seed script는 idempotent하게 유지
- full 데이터, 이미지, 재고, 검색 인덱스 관련 seed/import는 별도 작업 로그 작성
- 새 seed를 추가하면 중복 insert가 생기지 않는지 확인

수동 실행 기준:

```bash
docker compose exec backend python -m app.cli.seed_data
```

### data/dev-small

CD의 `rsync --delete`로 서버에서 만든 `data/dev-small`이 사라질 수 있으므로, Dev 배포 workflow는 `data/products.csv` 또는 `data/products/`가 있을 때 1,000개 subset CSV를 자동으로 다시 생성합니다.

```bash
python3 data/scripts/build_seed_subset.py --source-dir data --output-dir data/dev-small --force
```

## Redis / Elasticsearch Smoke Test

```bash
docker compose --profile server config
docker compose --profile server up -d redis elasticsearch
docker compose ps redis elasticsearch
docker compose exec -T redis redis-cli ping
curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'
```

통과 기준:

- Redis와 Elasticsearch container가 `healthy`
- Redis `PING` 응답이 `PONG`
- Elasticsearch `_cluster/health`가 `green` 또는 `yellow`
- `docker compose --profile server config`에서 Redis/Elasticsearch host bind가 `127.0.0.1`
- EC2 security group에서 `6379`, `9200` inbound가 외부 공개되지 않음

## 장애 운영 기준

### Redis 장애

- 상품 조회, 추천, 장바구니, 주문 같은 핵심 흐름은 Redis 장애만으로 막지 않습니다.
- cache 기능은 Redis 장애 시 DB 조회로 fail-open합니다.
- rate limit 기능을 붙일 때는 남용 방지 정책이 필요하므로 fail-open/fail-closed 기준을 PR에서 명시합니다.
- Redis 데이터 삭제, volume 삭제, prefix 변경은 운영 결정으로 보고 먼저 공유합니다.

확인 명령:

```bash
docker compose ps redis
docker compose logs --tail=100 redis
docker compose exec -T redis redis-cli INFO memory
docker compose exec -T redis redis-cli INFO stats
```

### Elasticsearch 장애

- ES 장애는 Auth, Profile, Cart, Order, Payment mock 흐름을 막지 않습니다.
- 검색/추천은 ES 연결 전까지 Postgres 기반 검색/추천 fallback을 유지합니다.
- ES 검색 ranking을 붙이는 PR은 fallback 조건, fallback 응답 품질, index rebuild 방법을 같이 문서화합니다.
- index 삭제, prefix 변경, reindex는 검색/추천 담당과 인프라 담당이 함께 확인합니다.

확인 명령:

```bash
docker compose ps elasticsearch
docker compose logs --tail=100 elasticsearch
curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'
curl -fsS 'http://127.0.0.1:9200/_cat/indices?v'
```

## 최소 모니터링 기준

CloudWatch를 아직 붙이지 못한 상태에서는 배포 전후와 실유저 테스트 중 아래 항목을 최소 수동 확인합니다.

```bash
docker compose ps
docker stats --no-stream
df -h
docker system df
docker compose logs --tail=100 backend
docker compose logs --tail=100 redis
docker compose logs --tail=100 elasticsearch
docker compose exec -T redis redis-cli INFO memory
docker compose exec -T redis redis-cli INFO stats
curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'
```

즉시 확인이 필요한 신호:

- container `unhealthy` 또는 반복 restart
- backend `/api/health` 실패
- backend 로그의 반복 5xx/error
- Redis `used_memory`가 `maxmemory`에 근접하거나 `evicted_keys`가 빠르게 증가
- ES cluster status `red`
- host disk 사용률 80% 이상
- Docker log 또는 image/volume 누적으로 disk 부족
- EC2 status check 실패

## 이미지 자산 인프라

P2 상품 이미지 적재와 공개 서빙은 EC2 로컬 디스크가 아니라 S3 + CloudFront 기준으로 운영합니다.

- S3 bucket: `mubarelle-images`, 서울 리전 `ap-northeast-2`
- S3 공개 설정: private bucket, public access block 활성화
- 원본 이미지: `original/{storage_key}`에 보관하고 외부 공개하지 않음
- 공개 이미지: `resized/w400/{storage_key}`, `resized/w1200/{storage_key}`
- CloudFront domain: `https://d3hg0esuwey1za.cloudfront.net`
- CloudFront 접근: OAC로 S3 private origin 연결
- 브라우저 공개 URL: `.env`의 `VITE_IMAGE_CDN_BASE_URL`로 관리
- EC2 upload role: dev EC2에 S3 업로드 전용 IAM role 연결

서비스 DB에는 CloudFront 절대 URL을 저장하지 않고 `product_images.storage_key`를 저장합니다. 프론트는 `VITE_IMAGE_CDN_BASE_URL`과 `storage_key`를 조합해 실제 이미지 URL을 만듭니다.

## 보안그룹 기준

현재 Dev API 서버:

```text
22    SSH, 관리자 IP 또는 GitHub Actions 접근 방식에 맞게 제한
80    전체 허용
443   전체 허용
8000  가능하면 외부 차단, 필요 시 팀원 IP만 임시 허용
5173  외부 차단
5432  RDS/Postgres, 외부 공개 금지
6379  Redis, 외부 공개 금지
9200  Elasticsearch, 외부 공개 금지
```

## GitHub Actions SSH 배포 주의

현재 `cd-dev.yml`은 GitHub-hosted runner가 EC2에 SSH 접속하는 방식입니다.

EC2에 repository를 미리 clone할 필요는 없습니다. GitHub Actions가 현재 checkout된 소스를 `rsync`로 `DEV_APP_DIR`에 동기화합니다.

서버의 `.env`는 GitHub Actions가 덮어쓰지 않습니다. 서버에 `.env`가 없으면 첫 배포 때 `.env.example`을 복사해 생성하고, 실제 dev secret은 EC2에서 직접 수정합니다.

## 커뮤니티 실유저 테스트 최소 기준

Smoke test:

- Frontend 접속 가능
- Backend `/api/health` 정상
- `VITE_API_BASE_URL`이 대상 API origin을 가리킴
- `BACKEND_CORS_ORIGINS`가 대상 frontend origin을 허용함
- 회원가입/로그인 흐름 정상
- 홈/상품/추천/검색 주요 화면 정상
- 이미지 CDN URL 정상
- 서버 로그에 반복 에러 없음

Rollback:

- 직전 안정 커밋 확인
- 서버 `.env` 백업
- RDS snapshot 또는 dump 확보
- rollback 후 `/api/health`와 주요 화면 재확인

## 아직 하지 않는 것

- production 자동 배포
- ECS/Fargate
- ALB
- ECR
- production 자동 DB 백업
- production Elasticsearch 운영 클러스터
- production Redis 운영 구성
- Redis cache/rate limit 기능 연결
- Elasticsearch 검색 ranking 기능 연결
- event log 저장 API와 GA4 전체 매핑

이 항목들은 P2/P3 일정과 발표 전 안정화 기준에 맞춰 별도 이슈와 PR로 결정합니다.
