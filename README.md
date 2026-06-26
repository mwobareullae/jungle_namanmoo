# 뭐바를래

피부 고민을 입력하면 성분 효능 근거를 바탕으로 나에게 맞는 화장품을 추천해주는 서비스입니다.

- 서비스 식별자: `mwobareullae`

## 현재 단계

팀원 모두가 개발을 시작할 수 있도록 개발 환경과 프로젝트 골격만 준비합니다.

- Frontend: `apps/frontend`
- Backend: `apps/backend`
- Data: `data`
- Docs: `docs`
- GitHub workflows: `.github/workflows`

## 기술 스택

- Frontend: Vite, React, TypeScript, Tailwind CSS 예정
- Backend: FastAPI 예정
- Database: PostgreSQL + pgvector 예정
- Infra: Docker Compose
- CI/CD: GitHub Actions 최소 CI

## 이번 골격에 포함된 것

- 프론트엔드 작업 자리: `apps/frontend`
- 백엔드 작업 자리: `apps/backend`
- 데이터 산출물 작업 자리: `data`
- 문서 작업 자리: `docs`
- GitHub Actions 작업 자리: `.github/workflows`
- Docker Compose Postgres 서비스: `docker-compose.yml`
- 데이터 계약 문서: `docs/data-contract.md`
- 최소 CI workflow: `.github/workflows/ci.yml`

## 로컬 개발 환경 준비

### 1. 환경변수 파일 만들기

```bash
cp .env.example .env
```

`.env`는 각자 로컬 또는 서버에서만 사용합니다. 실제 비밀번호, API key, secret은 커밋하지 않습니다.

### 2. Docker Compose 설정 확인

```bash
docker compose config
```

이 명령이 통과하면 `.env`와 `docker-compose.yml` 문법이 유효한 상태입니다.

### 3. Postgres/pgvector 실행

```bash
docker compose up -d postgres
```

현재 Compose에는 `postgres` 서비스만 포함되어 있습니다. 프론트엔드와 백엔드 서비스는 각 담당 브랜치에서 Dockerfile이 생긴 뒤 추가합니다.

### 4. 컨테이너 상태 확인

```bash
docker compose ps
```

### 5. Compose smoke test 실행

```bash
docker compose --profile test up --abort-on-container-exit --exit-code-from db-check db-check
```

이 명령은 Postgres가 정상 기동되는지, DB 접속이 되는지, `vector` extension을 생성할 수 있는지 확인합니다.

테스트 후 컨테이너를 정리합니다.

```bash
docker compose --profile test down
```

### 6. 로컬 DB 중지

```bash
docker compose down
```

DB 데이터를 포함해 완전히 초기화해야 할 때만 volume을 함께 삭제합니다.

```bash
docker compose down -v
```

## 팀원별 시작 위치

- 팀원1 프론트엔드/인프라: `apps/frontend`, `.env.example`, `docker-compose.yml`, `.github/workflows`, `docs`
- 팀원2 백엔드/API: `apps/backend`
- 팀원3 고민 태그/효능 매핑: `data`, `docs/data-contract.md`
- 팀원4 성분/근거/주의 성분: `data`, `docs/data-contract.md`
- 팀원5 상품/가격/이미지/seed 원천 데이터: `data`, `docs/data-contract.md`

공통 작업 규칙은 `AGENTS.md`를 따릅니다.

## 개발 흐름

1. `dev` 브랜치에서 작업 브랜치를 생성합니다.
2. 브랜치 이름은 `feat/*`, `fix/*`, `docs/*`, `chore/*` 규칙을 따릅니다.
3. 담당 영역만 수정합니다.
4. 커밋 메시지는 `type(scope): subject` 형식을 사용합니다.
5. PR을 열고 CI 통과 후 `dev`에 머지합니다.
6. `main`은 실배포 브랜치이며 직접 push하지 않습니다.

## 현재 CI 범위

현재 CI는 앱 빌드가 아니라 인프라 골격 검증만 수행합니다.

- 필수 파일 존재 확인
- 실제 `.env` 파일 커밋 여부 확인
- `docker compose --profile test config`
- Docker Compose smoke test

프론트엔드와 백엔드가 초기화되면 각 담당 브랜치에서 lint, typecheck, test, build 검증을 추가합니다.

## 아직 하지 않은 것

- 프론트엔드 프로젝트 초기화
- S1~S4 화면 구현
- mock API 구현
- 백엔드 구현
- 실제 데이터 적재
- 실제 API 연동
- Docker Compose frontend/backend 서비스 추가
- frontend/backend lint/build/test CI 추가
- CD workflow 작성
- 배포 설정
