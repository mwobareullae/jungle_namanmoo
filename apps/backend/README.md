# Backend

FastAPI 백엔드 작업 자리입니다.

## 담당 범위

- 현재는 Docker Compose 실행 확인을 위한 FastAPI Hello World만 있습니다.
- 팀원2가 별도 백엔드 작업 브랜치에서 실제 API, 스코어링, DB 연결을 확장합니다.
- Phase 0 API base path는 `/api`입니다.
- 인증은 Phase 0에서 제외합니다.

## 예정 endpoint

- `GET /api/health`
- `POST /api/recommendations`
- `GET /api/recommendations/{id}`
- `GET /api/products/{id}`

## 현재 상태

`http://localhost:8000`과 `http://localhost:8000/api/health`가 응답하는 상태입니다.
