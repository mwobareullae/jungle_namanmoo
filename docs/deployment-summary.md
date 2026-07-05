# Deployment Summary

이 문서는 P2 자사몰 개발 서버와 P3 인프라 준비 단계의 배포/운영 기준을 기록합니다.

문서보다 실제 코드, migration, GitHub Actions workflow, Docker Compose 설정을 우선합니다. 코드와 문서가 다르면 코드를 확인한 뒤 문서를 갱신합니다.

## 현재 결정 요약

```text
dev branch push
-> GitHub Actions checkout
-> rsync to EC2
-> docker compose up --build -d
```

- Dev 서버는 `dev` 브랜치 merge/push 기준으로 GitHub Actions가 자동 배포합니다.
- GitHub Actions는 서버 `.env`를 덮어쓰지 않습니다.
- DB migration은 CD에 포함하지 않습니다. 스키마 변경 PR merge 후 R6 인프라 담당이 Dev 서버에서 수동 실행합니다.
- Seed는 배포 파이프라인에서 자동 실행하지 않습니다. 필요 시 데이터/백엔드 담당 판단으로 수동 실행합니다.
- Production 자동 배포는 아직 만들지 않습니다.

## 서버 역할

### Dev 서버

- 목적: 팀원 6명 통합 개발/확인
- 인스턴스 기준: `t3.xlarge` 4vCPU / 16GB
- 배포: `dev` 브랜치 push 시 GitHub Actions 자동 배포
- 현재 기본 구성: `frontend`, `backend`, `postgres`
- Dev infra profile 구성: `redis`, `elasticsearch`
- DB: EC2 내부 Docker PostgreSQL 유지
- RDS: Dev에는 사용하지 않음
- 데이터 성격: 휘발성 개발 데이터
- Auto scaling: 불필요

Dev 서버에서 Redis/Elasticsearch까지 함께 실행하려면 서버 `.env`에 아래 값을 둡니다.

```env
COMPOSE_PROFILES=dev-infra
```

기존 Dev 서버는 배포 workflow가 `.env`를 덮어쓰지 않으므로, 이미 `.env`가 있다면 위 값은 서버에서 직접 추가해야 합니다.

### 실유저 테스트 서버

- 목적: 화장품 커뮤니티 실유저 피드백 수집
- 배포: Dev 기준 안정 커밋만 별도 배포
- Frontend: Vercel Production 배포 사용, 외부 Vercel dashboard 설정 기준
- 현재 구성 기준: Backend, PostgreSQL
- 서버 분리: Dev와 분리 유지
- RDS: 실데이터 보존과 백업/PITR을 위해 이전 예정

실유저 테스트 서버 `t3.small`에 Elasticsearch까지 얹는 것은 권장하지 않습니다. 검색 인프라는 아래 중 하나로 결정합니다.

- 서버를 `t3.medium` 이상으로 올린 뒤 ES 도입
- 당분간 Postgres 기반 검색 fallback 유지
- 비용상 필요할 때 Dev ES/Redis 임시 공유

Dev ES/Redis를 임시 공유할 경우 public 접근은 금지합니다. 같은 VPC private IP와 security group allowlist 기준으로만 허용하고, prefix를 반드시 분리합니다.

```env
REDIS_KEY_PREFIX=mubarelle:user-test:
ELASTICSEARCH_INDEX_PREFIX=mubarelle_user_test
```

### 발표용 서버

- 방식: 실유저 테스트 서버를 2026-07-22에 동결 승격
- 이유: 서버 신규 구축 없이 비용 절감, 실유저/발표 리스크 격리
- 운영 규칙: 배포 자동화 중단, hotfix 외 배포 금지, 실데이터 그대로 노출 금지

RDS 이전 완료 시:

```text
RDS snapshot/PITR 확보
-> 데모용 DB restore 또는 익명화 데이터 전환
-> smoke test
-> 발표 전 freeze
```

RDS 이전 전:

```text
Docker Postgres volume snapshot 또는 pg_dump 확보
-> 데모 데이터 전환
-> smoke test
-> 발표 전 freeze
```

## Docker Compose 구성

기본 compose 서비스:

```text
postgres
backend
frontend
```

Dev infra profile 포함 서비스:

```text
postgres
backend
frontend
redis
elasticsearch
```

Redis/Elasticsearch는 Dev 인프라만 먼저 제공합니다. 실제 cache/rate limit 적용, ES 검색 ranking 연결은 기능 담당 PR에서 별도로 진행합니다.

### Redis 기준

- image: `redis:7.2-alpine`
- profile: `dev-infra`
- bind: `127.0.0.1:${REDIS_PORT:-6379}`
- memory limit: `${REDIS_MEMORY_LIMIT:-512m}`
- maxmemory: `${REDIS_MAXMEMORY:-256mb}`
- persistence: appendonly enabled
- public port open 금지

### Elasticsearch 기준

- image: `docker.elastic.co/elasticsearch/elasticsearch:8.15.3`
- profile: `dev-infra`
- mode: single-node
- bind: `127.0.0.1:${ELASTICSEARCH_PORT:-9200}`
- memory limit: `${ELASTICSEARCH_MEMORY_LIMIT:-2g}`
- heap: `-Xms${ELASTICSEARCH_HEAP_SIZE:-1g} -Xmx${ELASTICSEARCH_HEAP_SIZE:-1g}`
- security: local/dev container 기준 `xpack.security.enabled=false`
- public port open 금지

### Backend env 기준

Dev 서버 backend container는 아래 env를 받습니다.

```env
BACKEND_CORS_ORIGINS=http://localhost:5173
REDIS_URL=redis://redis:6379/0
REDIS_KEY_PREFIX=mubarelle:dev:
ELASTICSEARCH_URL=http://elasticsearch:9200
ELASTICSEARCH_INDEX_PREFIX=mubarelle_dev
```

### 서버별 prefix 기준

Redis key prefix와 Elasticsearch index prefix는 환경 경계입니다. 같은 Redis/Elasticsearch 인스턴스를 임시 공유하더라도 URL만 같고 prefix는 반드시 다르게 둡니다.

| 서버/역할 | Redis URL | Redis key prefix | Elasticsearch URL | Elasticsearch index prefix |
| --- | --- | --- | --- | --- |
| Dev 통합 서버 | `redis://redis:6379/0` | `mubarelle:dev:` | `http://elasticsearch:9200` | `mubarelle_dev` |
| 실유저 테스트 서버 독립 운영 | 서버 내부 Redis URL | `mubarelle:user-test:` | 서버 내부 ES URL 또는 fallback | `mubarelle_user_test` |
| 실유저 테스트가 Dev ES/Redis 임시 공유 | Dev private URL | `mubarelle:user-test:` | Dev private URL | `mubarelle_user_test` |
| 발표 서버 별도 동결 운영 | 발표용 Redis URL | `mubarelle:demo:` | 발표용 ES URL 또는 snapshot restore | `mubarelle_demo` |

발표 서버를 실유저 테스트 서버 그대로 freeze하는 경우에는 `user-test` prefix를 유지하고, 배포 중단과 DB snapshot/dump로 동결합니다. 발표용 데이터를 별도로 복제하거나 index를 따로 만들 때만 `demo` prefix를 사용합니다.

prefix를 바꾸면 Redis는 cache miss가 발생하고, Elasticsearch는 새 index 생성 또는 reindex가 필요합니다. 배포 중 prefix 변경은 rollback 계획과 smoke test를 같이 잡은 경우에만 진행합니다.

백엔드 작업자가 SSH tunnel로 Dev infra를 사용할 때는 로컬 `.env`에서 host를 `localhost`로 바꿉니다.

```env
DATABASE_URL=postgresql+psycopg://mwobareullae:<password>@localhost:5432/mwobareullae
REDIS_URL=redis://localhost:6379/0
ELASTICSEARCH_URL=http://localhost:9200
```

### Auth / CORS 기준

프론트 Auth 요청은 `credentials: "include"` 기준으로 전환 중입니다. 백엔드는 CORS `allow_credentials=True`로 동작하므로, 각 서버 `.env`의 `BACKEND_CORS_ORIGINS`에는 실제 프론트 origin만 넣습니다.

```env
# Dev/local
BACKEND_CORS_ORIGINS=http://localhost:5173

# Release
BACKEND_CORS_ORIGINS=https://mubarelle.com,https://www.mubarelle.com
```

credentials 요청에는 wildcard origin `*`를 사용하지 않습니다. HTTPOnly cookie 인증을 완성하려면 백엔드에서 login/signup/refresh `Set-Cookie`, logout cookie 삭제, `/me` cookie token 처리, cookie 만료, `SameSite`, `Secure` 기준을 별도 작업으로 맞춰야 합니다.

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
- 100k 데이터, 이미지, 재고, 검색 인덱스 관련 seed/import는 별도 작업 로그 작성
- 새 seed를 추가하면 중복 insert가 생기지 않는지 확인

수동 실행 기준:

```bash
docker compose exec backend python -m app.cli.seed_data
```

## 역할별 로컬 개발 기준

### Frontend 작업자

Frontend는 로컬에서 frontend만 띄우고 Dev 서버 API를 사용합니다.

```env
VITE_API_BASE_URL=http://<dev-server-host>:8000/api
```

이 프로젝트는 Vite 기반이므로 `NEXT_PUBLIC_API_URL`은 사용하지 않습니다.

현재 기본 `docker-compose.yml`은 `frontend -> backend -> postgres` 의존성이 있습니다. 프론트만 실행할 때는 역할 분리용 `docker-compose.dev-modes.yml`의 `frontend-only` 서비스를 사용합니다.

역할 분리 compose를 사용할 때:

```bash
docker compose -f docker-compose.yml -f docker-compose.dev-modes.yml --profile frontend-only up --build frontend-only
```

### Backend 작업자 기본 모드

일반 백엔드 개발은 로컬 Docker Compose의 `postgres` 컨테이너를 사용합니다.

```text
backend container
+ local Docker Compose postgres container
```

용도:

- 일반 API 개발
- migration 작성
- seed 수정
- auth/cart/order/payment 등 DB 중심 기능 개발

PR 전에는 로컬에서 `alembic upgrade head`가 정상 적용되는지 확인합니다.

실행:

```bash
docker compose up --build backend
```

이 명령은 `backend`의 `depends_on` 때문에 `postgres`도 함께 실행하고, backend는 compose 내부 주소 `postgres:5432`로 DB에 연결합니다.

### Backend 통합 확인 모드

검색/추천/캐시 통합 확인이 필요할 때는 Dev 서버의 Postgres/ES/Redis를 한 세트로 SSH 터널링해서 사용합니다.

```text
backend local
+ SSH tunnel
+ dev Postgres
+ dev Elasticsearch
+ dev Redis
```

`local Docker Compose Postgres + dev ES/Redis` 혼합 사용은 기본 규칙으로 두지 않습니다. DB 데이터와 ES index, Redis cache가 서로 달라져 디버깅이 어려워질 수 있습니다.

실행:

```bash
ssh dev-tunnel
```

```bash
docker compose -f docker-compose.yml -f docker-compose.dev-modes.yml --profile backend-dev-tunnel up --build backend-dev-tunnel
```

`backend-dev-tunnel` 컨테이너는 호스트의 SSH tunnel을 `host.docker.internal`로 접근합니다. Docker 밖에서 백엔드를 직접 실행하는 경우에는 `localhost` 기준 URL을 사용합니다.

기본 `frontend`/`backend` 서비스와 `frontend-only`/`backend-dev-tunnel` 서비스는 각각 같은 host port를 사용합니다. 동시에 띄우지 말고, 동시에 필요하면 `FRONTEND_PORT` 또는 `BACKEND_PORT`를 바꿉니다.

## SSH tunnel 기준

팀원별 개인 SSH 키를 사용합니다. PEM 키 공유는 지양합니다.

```bash
ssh-keygen -t ed25519 -C "<name>@mwobareullae"
```

공유 대상은 개인키가 아니라 공개키입니다.

```text
~/.ssh/id_ed25519.pub
```

`~/.ssh/config` 예시:

```sshconfig
Host dev-tunnel
    HostName <dev-server-host>
    User <user-name>
    IdentityFile ~/.ssh/id_ed25519
    IdentitiesOnly yes
    LocalForward 5432 localhost:5432
    LocalForward 6379 localhost:6379
    LocalForward 9200 localhost:9200
```

접속:

```bash
ssh dev-tunnel
```

## Redis/Elasticsearch smoke test

실제 Dev 서버에서 Redis/Elasticsearch까지 확인할 때는 SSH 접속 후 서버의 `DEV_APP_DIR`에서 실행합니다.

```bash
docker compose --profile dev-infra config
docker compose --profile dev-infra up -d redis elasticsearch
docker compose ps redis elasticsearch
docker compose exec -T redis redis-cli ping
curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'
```

통과 기준:

- Redis와 Elasticsearch container가 `healthy`
- Redis `PING` 응답이 `PONG`
- Elasticsearch `_cluster/health`가 `green` 또는 `yellow`
- `docker compose --profile dev-infra config`에서 Redis/Elasticsearch host bind가 `127.0.0.1`
- EC2 security group에서 `6379`, `9200` inbound가 외부 공개되지 않음

현재 `docker-compose.yml` 기준으로 Redis는 `appendonly yes`, `maxmemory-policy allkeys-lru`, memory limit `512m`, Elasticsearch는 memory limit `2g`, heap `1g`로 시작합니다.

## Redis/Elasticsearch 장애 운영 기준

Redis/Elasticsearch는 현재 Dev 인프라와 연결 env만 제공합니다. 실제 cache/rate limit, ES 검색 ranking 연결은 기능 담당 PR에서 별도로 진행합니다.

### Redis 장애

원칙:

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

복구 순서:

```bash
docker compose up -d redis
docker compose restart redis
docker compose ps redis
docker compose exec -T redis redis-cli ping
```

Redis memory limit 또는 `maxmemory`에 걸려 eviction이 급증하면 `REDIS_MAXMEMORY`, `REDIS_MEMORY_LIMIT`, cache TTL, key prefix 사용량을 함께 확인합니다.

### Elasticsearch 장애

원칙:

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

복구 순서:

```bash
docker compose up -d elasticsearch
docker compose restart elasticsearch
docker compose ps elasticsearch
curl -fsS 'http://127.0.0.1:9200/_cluster/health?pretty'
```

ES cluster status가 `red`이면 새 배포를 멈추고 DB fallback으로 주요 화면 smoke를 먼저 확인합니다. index 재생성은 reindex script와 대상 prefix가 확정된 뒤 진행합니다.

### Rollback 기준

- 앱 배포 문제는 우선 직전 안정 커밋으로 rollback하고 Redis/ES volume은 유지합니다.
- Redis cache 문제는 volume 삭제보다 key prefix 변경 또는 특정 prefix cleanup을 우선 검토합니다.
- ES index 문제는 DB fallback 유지 후 index rebuild 또는 이전 prefix/index로 전환합니다.
- `docker compose down -v`, Redis volume 삭제, ES volume 삭제는 데이터/검색/인프라 담당 확인 없이 실행하지 않습니다.

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

CloudWatch를 붙일 때의 최소 기준:

- EC2 `CPUUtilization`, `StatusCheckFailed`
- CloudWatch Agent 기반 memory/disk 사용률
- disk 사용률 80% 이상 알림
- 비용 예산 초과 알림
- 가능하면 backend health endpoint 외부 synthetic check

## 이미지 자산 인프라

P2 상품 이미지 적재와 공개 서빙은 EC2 로컬 디스크가 아니라 S3 + CloudFront 기준으로 운영합니다.

- 비용 모니터링: CloudWatch/Budgets 기반 비용 알림 운영 중
- S3 bucket: `mubarelle-images`, 서울 리전 `ap-northeast-2`
- S3 공개 설정: private bucket, public access block 활성화
- 원본 이미지: `original/{storage_key}`에 보관하고 외부 공개하지 않음
- 공개 이미지: `resized/w400/{storage_key}`, `resized/w1200/{storage_key}`
- CloudFront distribution: `jungle-namanmoo`
- CloudFront domain: `https://d3hg0esuwey1za.cloudfront.net`
- CloudFront 접근: OAC로 S3 private origin 연결
- 브라우저 공개 URL: `.env`의 `VITE_IMAGE_CDN_BASE_URL`로 관리
- EC2 upload role: dev EC2에 S3 업로드 전용 IAM role 연결
- EC2 upload permission: 이미지 버킷에 대한 `PutObject`, `GetObject`, `DeleteObject` 권한
- EC2 역할 검증: boto3 업로드 테스트 완료

서비스 DB에는 CloudFront 절대 URL을 저장하지 않고 `product_images.storage_key`를 저장합니다. 프론트는 `VITE_IMAGE_CDN_BASE_URL`과 `storage_key`를 조합해 실제 이미지 URL을 만듭니다.

## 보안그룹 기준

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

## GitHub Actions SSH 배포 주의

현재 `cd-dev.yml`은 GitHub-hosted runner가 EC2에 SSH 접속하는 방식입니다.

EC2에 repository를 미리 clone할 필요는 없습니다. GitHub Actions가 현재 checkout된 소스를 `rsync`로 `DEV_APP_DIR`에 동기화합니다.

서버의 `.env`는 GitHub Actions가 덮어쓰지 않습니다. 서버에 `.env`가 없으면 첫 배포 때 `.env.example`을 복사해 생성하고, 실제 dev secret은 EC2에서 직접 수정합니다.

따라서 EC2 보안그룹의 SSH 인바운드가 GitHub-hosted runner에서 접근 가능해야 합니다. 더 안전한 방식은 추후 아래 중 하나로 전환합니다.

- self-hosted runner를 EC2에 설치
- AWS credentials로 배포 직전에 GitHub Actions runner IP만 보안그룹에 임시 허용 후 제거
- Caddy/Nginx와 별도 배포 채널 정리

## 커뮤니티 실유저 테스트 최소 기준

실유저 테스트 서버는 Dev와 분리해서 운영합니다. 배포 전 최소 확인 항목은 별도 smoke/rollback 문서에서 확정하되, 현재 기준은 아래와 같습니다.

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
- DB snapshot 또는 dump 확보
- rollback 후 `/api/health`와 주요 화면 재확인

## 아직 하지 않는 것

- production 자동 배포
- Dev RDS 사용
- 실유저 테스트 RDS 이전 완료
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
