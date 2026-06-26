# 뭐바를래 Backend

FastAPI 기반 백엔드입니다. 현재 기준 실행 환경은 **Docker Compose 우선**, 로컬 개발은 `.venv` 선택 사용으로 고정합니다.

## 현재 API

- `GET /api/health`
- `POST /api/recommendations`
- `GET /api/recommendations/{id}`
- `GET /api/products/{id}`

## 의존성 관리

- 런타임 의존성: `requirements.txt`
- 개발/테스트 의존성: `requirements-dev.txt`
- Python 기준 버전: `3.12`

DB 의존성인 SQLAlchemy, Alembic, psycopg는 다음 단계인 DB/Alembic 셋업에서 추가합니다.

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

특정 테스트만 실행:

```bash
docker compose exec backend python -m pytest tests/test_api_contracts.py
docker compose exec backend python -m pytest tests/test_data_loader.py
docker compose exec backend python -m pytest tests/test_parser.py
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

## 현재 구현 상태

- FastAPI 앱 구조와 CORS 설정이 있습니다.
- 3개 MVP API는 Mock 응답 기반으로 동작합니다.
- `data/tags.json` 기반 고민 태그 파서 연결을 진행 중입니다.
- 아직 DB, SQLAlchemy, Alembic, pgvector, 실제 스코어링은 없습니다.

## 다음 단계

1. SQLAlchemy + Alembic 셋업
2. MVP v0 ERD 기준 ORM 모델 작성
3. 첫 migration 생성 및 적용
4. CSV/JSON seed/import 구조 추가
5. Mock API를 DB 조회 기반으로 점진 교체
