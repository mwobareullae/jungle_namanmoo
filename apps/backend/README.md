# 뭐바를래 Backend

FastAPI 기반 백엔드입니다. 현재 기준 실행 환경은 **Docker Compose 우선**, 로컬 개발은 `.venv` 선택 사용으로 고정합니다.

## 현재 API

현재 FastAPI 앱은 아래 라우트 그룹을 `/api` prefix 아래에 등록합니다.

- `health`: health check
- `auth`: email/nickname 중복 확인, signup, login, Google login, refresh, logout, password reset, `/me`
- `skin`: skin profile, skin test questions/submit/result/apply
- `home`: home sections
- `recommendations`: recommendation create/detail/narrative
- `products`: product detail/search/popular
- `user_activity`: wishlist, recent views
- `cart`: cart item CRUD, anonymous cart merge, checkout preview
- `addresses`: saved address CRUD
- `orders`: order create/list/detail/cancel
- `payments`: mock payment confirm/fail, Toss confirm
- `events`: single/batch event log collection
- `agent`: chat, pending tool call confirmation

## 의존성 관리

- 런타임 의존성: `requirements.txt`
- 개발/테스트 의존성: `requirements-dev.txt`
- Python 기준 버전: `3.12`
- DB/마이그레이션: SQLAlchemy, Alembic, psycopg

## Docker 기준 실행

루트 디렉터리에서 실행합니다.

```bash
docker compose up --build
```

Docker Compose에서는 루트 `data/` 디렉터리를 백엔드 컨테이너의 `/data`에 읽기 전용으로 마운트합니다.
백엔드는 기본적으로 `DATA_DIR=/data`를 사용합니다.

확인:

```bash
curl http://localhost:8000/api/health
```

백엔드 테스트:

```bash
docker compose exec backend python -m pytest
```

Postgres 포트가 이미 사용 중이고 DB가 필요 없는 테스트만 돌릴 때:

```bash
docker compose run --rm --no-deps backend python -m pytest
```

Alembic 설정 확인:

```bash
docker compose run --rm --no-deps backend python -m alembic heads
```

정리:

```bash
docker compose down
```

## 로컬 venv 기준 실행

백엔드 디렉터리에서 실행합니다.

```powershell
cd apps/backend
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r requirements-dev.txt
```

테스트:

```powershell
python -m pytest
```

개발 서버:

```powershell
python -m uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload
```

Alembic 설정 확인:

```powershell
python -m alembic heads
```

## DB 설정

기본 DB URL은 `DATABASE_URL` 환경변수로 설정합니다.

```text
postgresql+psycopg://mwobareullae:change-me@postgres:5432/mwobareullae
```

기존 `postgresql://...` 형식이 들어와도 백엔드 내부에서 `postgresql+psycopg://...` 형식으로 정규화합니다.

## Alembic 명령

새 DB 변경이 필요할 때만 별도 migration을 생성합니다.

```bash
python -m alembic revision --autogenerate -m "add feature schema"
python -m alembic upgrade head
```

현재 migration은 상품/성분/검색, 인증 세션, 피부 프로필/테스트, 이미지/판매자/재고, 장바구니/checkout, 주문/결제, 이벤트 로그, agent tool call까지 포함합니다.

## 현재 구현 상태

- FastAPI 앱 구조, CORS, 공통 에러 응답이 있습니다.
- 주요 P2 API는 DB 모델, 서비스 계층, pytest 기반 계약 테스트와 함께 동작합니다.
- `data/tags.json` 기반 고민 태그 파서가 추천 API에 연결되어 있습니다.
- SQLAlchemy Base, DB engine/session, Alembic migration, CSV/JSON seed/import 구조가 있습니다.
- 추천/검색은 후보 추출, scoring, pgvector 검색, Elasticsearch dev infra 연동 준비를 포함합니다.
- Auth, Profile/Skin test, Cart/Checkout, Address, Order/Payment mock/Toss confirm, Event log, Agent API가 구현되어 있습니다.

## 다음 단계

1. P2 자사몰 API/화면 계약 안정화
2. Dev 서버 migration/seed 운영 절차 점검
3. Redis cache/rate limit 기능 연결
4. Elasticsearch 검색 ranking 연결
5. GA4/internal event 매핑 고도화
