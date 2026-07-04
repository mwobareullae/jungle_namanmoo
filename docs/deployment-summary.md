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

일반 백엔드 개발은 로컬 Postgres를 사용합니다.

```text
backend local
+ postgres local
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

### Backend 통합 확인 모드

검색/추천/캐시 통합 확인이 필요할 때는 Dev 서버의 Postgres/ES/Redis를 한 세트로 SSH 터널링해서 사용합니다.

```text
backend local
+ SSH tunnel
+ dev Postgres
+ dev Elasticsearch
+ dev Redis
```

`local Postgres + dev ES/Redis` 혼합 사용은 기본 규칙으로 두지 않습니다. DB 데이터와 ES index, Redis cache가 서로 달라져 디버깅이 어려워질 수 있습니다.

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
