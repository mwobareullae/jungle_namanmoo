# AGENTS.md

이 문서는 `mwobareullae / 뭐바를래` 프로젝트에서 사람과 AI 에이전트가 동일한 규칙으로 작업하기 위한 공통 개발 규칙입니다.

## 프로젝트 구조

현재 infra 브랜치는 팀 개발을 시작하기 위한 골격만 둡니다.

```text
.
├─ apps/
│  ├─ frontend/          # 프론트엔드 작업 자리
│  └─ backend/           # 백엔드 작업 자리
├─ data/                 # CSV/JSON 데이터 산출물과 예시
│  └─ examples/          # 데이터 형식 예시 파일
├─ docs/                 # 기획, API, 배포, 데이터 계약 문서
├─ .github/
│  └─ workflows/         # GitHub Actions CI/CD 작업 자리
├─ README.md             # 팀 공통 안내
├─ .env.example          # 공유 가능한 환경변수 템플릿
├─ docker-compose.yml    # 로컬/dev 공통 실행 환경
└─ AGENTS.md             # AI/팀원 작업 규칙
```

아직 프론트엔드와 백엔드 실제 구현은 없습니다. 각 담당자는 별도 브랜치에서 자기 영역을 초기화합니다.

## 담당 영역

### 팀원1 지운

- 담당: 프론트엔드, Docker Compose, CI/CD, 배포, 환경변수 템플릿, 팀 공통 실행 문서
- 주 작업 폴더:
  - `apps/frontend/`
  - `docs/`
  - `.github/workflows/`
  - 루트 `README.md`
  - 루트 `.env.example`
  - 루트 `docker-compose.yml`
  - 루트 `AGENTS.md`

### 팀원2 원우

- 담당: FastAPI 백엔드, API, 스코어링, DB 연결, 마이그레이션, 헬스체크
- 주 작업 폴더:
  - `apps/backend/`
  - API 계약 문서가 생기면 `docs/api-*.md`

### 팀원3 지현

- 담당: 고민 태그, 효능 매핑, 자연어 입력 해석, unmatched terms
- 주 작업 폴더:
  - `docs/data-contract.md`
  - `data/`
  - `data/examples/`
- 주 산출물:
  - `data/tags.json`
  - `data/concern_to_effect.json`

### 팀원4 규태

- 담당: 성분 효능 근거, 성분 근거 점수, 성분 위험/주의 정보
- 주 작업 폴더:
  - `docs/data-contract.md`
  - `data/`
  - `data/examples/`
- 주 산출물:
  - `data/ingredients.csv`
  - `data/ingredient_effect.csv`
  - `data/ingredient_evidence.csv`
  - `data/risk_flags.csv`

### 팀원5 세민

- 담당: 상품 10개, 이미지, 가격, 구매 URL, 상품-성분 매핑, seed 데이터
- 주 작업 폴더:
  - `docs/data-contract.md`
  - `data/`
  - `data/examples/`
- 주 산출물:
  - `data/products.csv`
  - `data/product_ingredients.csv`
  - `data/product_prices.csv`
  - `data/vector_docs.csv`

## AI 에이전트 작업 원칙

1. 요청받은 담당 영역 밖의 파일은 수정하지 않는다.
2. 담당 영역 밖 변경이 필요하면 직접 수정하기 전에 이유와 변경안을 설명한다.
3. `main`과 `dev`에 직접 push하지 않는다.
4. 모든 기능 작업은 별도 브랜치에서 진행한다.
5. 기존 파일을 삭제하거나 대규모 리팩터링하지 않는다.
6. 사용자가 만든 변경사항을 되돌리지 않는다.
7. `.env` 같은 실제 비밀값 파일은 절대 생성하거나 커밋하지 않는다.
8. `.env.example`에는 예시 키와 안전한 기본값만 둔다.
9. API 스키마를 바꾸는 경우 API 계약 문서도 함께 갱신한다.
10. Docker, CI/CD, 환경변수 변경은 팀 전체 실행 방식에 영향을 주므로 변경 이유를 PR에 명시한다.
11. 데이터 파일의 컬럼명이나 JSON key는 `docs/data-contract.md` 없이 임의 변경하지 않는다.
12. SQL 직접 작성보다 CSV/JSON 원천 데이터와 seed script 방식을 우선한다.

## 브랜치 규칙

```text
main                 # 실배포
dev                  # 개발/통합 테스트
feat/*               # 기능 추가
fix/*                # 버그 수정
docs/*               # 문서 변경
chore/*              # 설정, 환경, 의존성 변경
```

권장 브랜치 예시:

```text
feat/infra-frontend-setup
feat/backend-api-stub
feat/s1-concern-input
feat/mock-api
fix/docker-compose-env
docs/api-contract
chore/github-actions-ci
```

## 커밋 컨벤션

커밋 메시지는 아래 형식을 사용한다.

```text
type(scope): subject
```

예시:

```text
feat(frontend): initialize vite react app
chore(frontend): add eslint and prettier config
infra(docker): add postgres compose service
docs(readme): add local setup guide
fix(ci): correct frontend build path
```

### type 목록

```text
feat      # 기능 추가
fix       # 버그 수정
docs      # 문서 수정
style     # 코드 의미 변화 없는 스타일 수정
refactor  # 동작 변화 없는 구조 개선
test      # 테스트 추가/수정
chore     # 빌드, 설정, 패키지, 기타 작업
ci        # GitHub Actions 등 CI/CD 수정
infra     # Docker, 배포, 인프라 설정
```

### scope 예시

```text
frontend
backend
infra
ci
docs
api
env
docker
data
seed
```

### subject 규칙

- 영어 소문자 문장으로 작성한다.
- 마침표를 붙이지 않는다.
- 50자 안팎으로 짧게 쓴다.
- `update`, `fix stuff`, `changes`처럼 의미가 흐린 표현을 피한다.

좋은 예:

```text
feat(frontend): add base folder structure
chore(env): add shared env example
docs(data): add shared data contract
```

나쁜 예:

```text
update
fix
final
change files
프론트 수정
```

## 커밋 단위

커밋은 리뷰 가능한 하나의 작업 단위로 나눈다.

권장:

- 프로젝트 골격 생성 1커밋
- 프론트 초기 세팅 1커밋
- 백엔드 초기 세팅 1커밋
- Docker Compose 변경 1커밋
- GitHub Actions 변경 1커밋
- 문서 변경 1커밋
- API 스키마 변경 1커밋
- 데이터 계약 변경 1커밋
- seed 데이터 변경 1커밋

피해야 할 커밋:

- 프론트, 백엔드, Docker, 문서를 한 번에 바꾸는 커밋
- 기능 구현과 포맷팅 변경이 섞인 커밋
- 실제 동작 변경과 단순 파일 이동이 섞인 커밋
- 여러 팀원의 담당 영역이 섞인 커밋
- 데이터 형식 변경과 실제 데이터 대량 추가가 섞인 커밋

예외:

- 하나의 변경을 완성하기 위해 문서와 설정을 반드시 같이 바꿔야 하는 경우는 같은 커밋에 포함할 수 있다.
- 예: `docker-compose.yml`에서 환경변수를 추가하면서 `.env.example`과 `README.md` 실행법을 함께 갱신하는 경우
- 예: `docs/data-contract.md`에 새 컬럼을 추가하면서 예시 CSV 1개를 같이 갱신하는 경우

## 커밋 전 확인

- `git status`로 의도한 파일만 변경됐는지 확인한다.
- 담당 영역 밖 파일이 섞였으면 커밋하지 않는다.
- `.env` 또는 비밀값이 포함됐는지 확인한다.
- 실행법이나 환경변수가 바뀌면 문서도 같이 수정한다.
- 가능하면 관련 검증 명령을 실행한다.

## 수정 가능 범위 예시

### 프론트엔드 작업

수정 가능:

```text
apps/frontend/
docs/frontend-*.md
```

수정 금지:

```text
apps/backend/
docker-compose.yml
.github/workflows/
```

단, 프론트 실행에 필요한 환경변수나 Compose 수정이 필요하면 먼저 설명 후 진행한다.

### 백엔드 작업

수정 가능:

```text
apps/backend/
docs/api-*.md
```

수정 금지:

```text
apps/frontend/
.github/workflows/
```

API 응답 구조를 바꾸면 프론트 담당자에게 영향이 있으므로 API 계약 문서를 같이 수정한다.

### 인프라/배포 작업

수정 가능:

```text
docker-compose.yml
.env.example
.github/workflows/
README.md
docs/
AGENTS.md
```

주의:

- 실제 앱 코드는 최소한으로만 수정한다.
- 배포 설정 변경 후 `docker compose config` 또는 CI 검증을 수행한다.

### 데이터 작업

수정 가능:

```text
data/
docs/data-contract.md
```

수정 금지:

```text
apps/frontend/
apps/backend/
docker-compose.yml
.github/workflows/
```

주의:

- 데이터 파일 형식은 `docs/data-contract.md`를 따른다.
- CSV header 또는 JSON key를 임의로 바꾸지 않는다.
- 출처가 필요한 데이터는 `source` 또는 근거 문서 경로를 포함한다.
- SQL 직접 작성보다 CSV/JSON 원천 데이터와 seed script 방식을 우선한다.

## 데이터 계약 규칙

- 데이터 파일 형식의 단일 기준은 `docs/data-contract.md`이다.
- 실제 데이터는 `data/` 아래에 둔다.
- 예시 데이터는 `data/examples/` 아래에 둔다.
- `data/`의 CSV는 UTF-8 인코딩과 header row를 사용한다.
- `data/`의 JSON은 `docs/data-contract.md`에 정의된 object 또는 array schema를 따른다.
- 컬럼명, enum 값, JSON key를 바꾸면 `docs/data-contract.md`와 예시 파일도 같이 수정한다.
- 실제 서비스 DB에 직접 SQL을 실행하는 방식은 MVP 기본 방식으로 사용하지 않는다.

## 환경변수 규칙

- 커밋 가능: `.env.example`
- 커밋 금지: `.env`, `.env.local`, `.env.production`, `.env.*.local`
- 로컬 개발자는 `.env.example`을 복사해서 각자 `.env`를 만든다.
- dev 서버와 production 서버는 서로 다른 실제 환경변수를 사용한다.
- `VITE_`로 시작하는 값은 브라우저에 노출될 수 있으므로 secret을 넣지 않는다.
- Phase 0에서는 OpenAI API key를 기본 환경변수로 요구하지 않는다.

## Docker Compose 규칙

- 루트 `docker-compose.yml`은 팀 공통 실행 기준이다.
- 현재 Compose에는 Postgres/pgvector만 포함한다.
- frontend/backend 서비스는 각 담당 브랜치에서 Dockerfile이 생긴 뒤 추가한다.
- 서비스 이름, 포트, 환경변수명을 바꾸면 README와 `.env.example`도 같이 갱신한다.

기본 검증:

```bash
docker compose config
```

## CI/CD 규칙

- GitHub Actions 파일은 `.github/workflows/`에 둔다.
- PR에서는 현재 가능한 검증부터 추가한다.
- 프론트/백엔드 초기화 전에는 앱 빌드를 억지로 넣지 않는다.
- `main` 배포와 `dev` 배포는 환경을 분리한다.
- secret 값은 GitHub Secrets 또는 배포 플랫폼 Secrets에 둔다.

## PR 체크리스트

PR을 만들기 전에 아래를 확인한다.

- [ ] 커밋 메시지가 컨벤션을 따르는가?
- [ ] 커밋 단위가 너무 크거나 여러 담당 영역을 섞지 않았는가?
- [ ] 담당 영역 안의 파일만 수정했는가?
- [ ] `.env` 또는 비밀값을 커밋하지 않았는가?
- [ ] 실행 방법이 바뀌었다면 `README.md`를 수정했는가?
- [ ] 환경변수가 바뀌었다면 `.env.example`을 수정했는가?
- [ ] API 스키마가 바뀌었다면 문서를 수정했는가?
- [ ] 데이터 파일 구조가 `docs/data-contract.md`와 일치하는가?
- [ ] CSV header 또는 JSON key를 임의 변경하지 않았는가?
- [ ] Docker/CI 변경이 있다면 검증 명령을 실행했는가?
- [ ] 불필요한 포맷 변경이나 대규모 리팩터링을 하지 않았는가?

## 현재 infra 브랜치 범위

infra 브랜치에서는 프로젝트 골격과 공통 개발환경만 준비한다.

포함:

- `apps/frontend/README.md`로 팀원1 작업 위치 안내
- `apps/backend/README.md`로 팀원2 작업 위치 안내
- `docs/data-contract.md` 초안
- `data/README.md`
- `data/examples/` 예시 파일
- 루트 `README.md`
- 루트 `.env.example`
- 루트 `docker-compose.yml`의 Postgres/pgvector 서비스
- 루트 `AGENTS.md`

제외:

- Vite + React + TypeScript 초기 세팅
- Tailwind, ESLint, Prettier 설정
- S1~S4 실제 화면 구현
- mock API 실제 구현
- FastAPI 실제 코드 구현
- 스코어링 구현
- DB 모델/마이그레이션 구현
- 실제 상품/성분/근거 데이터 대량 추가
- 실제 seed script 구현
- frontend/backend Dockerfile 작성
- 실제 배포 secret 추가

## MVP 기술 스택

```text
Frontend: Vite + React + TypeScript 예정
Styling: Tailwind CSS 예정
Code Quality: ESLint, Prettier 예정
Mock API: MSW 또는 mock JSON 예정
Backend: FastAPI 예정
API Base Path: /api
DB: PostgreSQL + pgvector
Infra: Docker Compose
CI/CD: GitHub Actions 예정
```

Spring Boot는 MVP 범위에는 포함하지 않는다. 추후 회원, 권한, 주문, 관리자, 복잡한 서비스 로직이 커질 때 별도 도입을 검토한다.
