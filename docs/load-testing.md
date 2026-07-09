# k6 Load Testing Guide

작성일: 2026.07.05  
대상 이슈: #273 k6 부하테스트 스크립트 셋업 + 성공 기준 문서화

## 목적

현재 부하테스트의 1차 목적은 최대 RPS 과장이 아니라 dev 서버 기준선을 잡는 것입니다.

- FastAPI API p95 latency 측정
- error rate 기준선 확보
- EC2 t3.large Dev API 서버에서 backend/Redis/Elasticsearch와 RDS PostgreSQL 조합의 병목 확인
- 이후 #267 주문/결제 동시성 테스트와 #287 종합 부하테스트의 기준값 제공

## 진행 단계

부하테스트는 아래 순서로 진행합니다. 현재 #273은 1단계 smoke test와 이후 단계 실행 기준을 준비하는 작업입니다.

| 단계 | 이름 | 목적 | 실행 기준 |
| --- | --- | --- | --- |
| 1 | Smoke test | 최소 부하로 테스트 스크립트, API, 데이터 상태가 정상인지 확인 | `PROFILE=smoke` |
| 2 | Load test | 예상 트래픽 수준에서 정상 응답, p95, error rate 확인 | `PROFILE=baseline`, 필요 시 `PROFILE=target` |
| 3 | Stress test | 서버가 어디서 깨지는지 한계점 확인 | `PROFILE=stress` |
| 4 | Soak test | 긴 시간 실행 시 메모리 증가, connection 누수, 로그/디스크 증가 확인 | 별도 soak profile 추가 예정 |
| 5 | Spike test | 갑작스러운 트래픽 폭증 상황에서 회복 여부 확인 | 별도 spike profile 추가 예정 |

1차 완료 기준은 smoke/load/stress 실행 기준을 먼저 고정하는 것입니다. Soak/spike는 #287 종합 부하테스트에서 실행 시간을 확정한 뒤 추가합니다.

## 스크립트

```bash
tests/k6/commerce-smoke.js
```

이 파일은 JavaScript 문법으로 작성되어 있지만 Node.js로 실행하지 않습니다. k6 전용 런타임에서 실행합니다.

포함 시나리오:

- `GET /api/health`
- `GET /api/products/popular`
- `GET /api/products/{product_id}`
- `POST /api/recommendations`
- `GET /api/recommendations/{recommendation_id}`
- 선택 실행: `POST /api/cart/items`

장바구니 쓰기 요청은 익명 cart row를 생성하므로 기본 비활성화입니다.

## 사전 조건

dev 서버:

```bash
cd ~/mwobareullae
docker compose ps
docker compose exec backend python -m alembic current
docker compose exec backend python - <<'PY'
from app.db.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    print(db.execute(text("select current_database(), inet_server_addr(), inet_server_port()")).fetchone())
    print(db.execute(text("select count(*) from products")).scalar())
PY
```

로컬에서 dev 서버 대상 실행 시:

```bash
curl http://52.79.240.15:8000/api/health
```

## 실행 명령

### k6 설치 확인

```bash
k6 version
```

설치되어 있지 않으면 macOS 기준:

```bash
brew install k6
```

Ubuntu 서버에서 실행할 경우:

```bash
sudo gpg -k
curl -s https://dl.k6.io/key.gpg | sudo gpg --dearmor -o /usr/share/keyrings/k6-archive-keyring.gpg
echo "deb [signed-by=/usr/share/keyrings/k6-archive-keyring.gpg] https://dl.k6.io/deb stable main" | sudo tee /etc/apt/sources.list.d/k6.list
sudo apt update
sudo apt install k6
```

### JavaScript 실행 방식

`tests/k6/commerce-smoke.js`는 아래처럼 `k6 run`으로 실행합니다.

```bash
k6 run tests/k6/commerce-smoke.js
```

아래 명령은 사용하지 않습니다.

```bash
node tests/k6/commerce-smoke.js
```

### Smoke test

로컬 backend 대상 smoke:

```bash
k6 run tests/k6/commerce-smoke.js
```

dev 서버 대상 smoke:

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=smoke \
k6 run tests/k6/commerce-smoke.js
```

### Load test

dev 서버 기준선:

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=baseline \
k6 run tests/k6/commerce-smoke.js
```

dev 서버 목표 부하:

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=target \
k6 run tests/k6/commerce-smoke.js
```

### Stress test

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=stress \
k6 run tests/k6/commerce-smoke.js
```

stress test는 팀 작업 시간에는 먼저 공유 후 실행합니다.

### 장바구니 쓰기 포함

익명 장바구니 쓰기 포함:

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=baseline \
ENABLE_CART_WRITES=true \
k6 run tests/k6/commerce-smoke.js
```

### 상품 ID 직접 지정

인기상품 데이터가 비어 있으면 상품 ID를 직접 지정합니다.

```bash
BASE_URL=http://52.79.240.15:8000/api \
PROFILE=smoke \
PRODUCT_IDS=prod_oy_a000000163734,prod_oy_a000000250344 \
k6 run tests/k6/commerce-smoke.js
```

## 프로파일

| PROFILE | 용도 | 부하 |
| --- | --- | --- |
| `smoke` | API 정상 응답 확인 | 1 VU, 약 1분 |
| `baseline` | 기준선 기록 | 10 VU, 약 4분 |
| `target` | MVP 실유저 테스트 목표 부하 | 20 VU 유지 후 50 VU 유지 |
| `stress` | 병목 확인 | 50 VU 후 100 VU |

현재 스크립트에는 `soak`, `spike` profile을 넣지 않았습니다. 장시간/폭증 테스트는 팀 작업에 영향을 줄 수 있어 실행 시간과 대상 API를 확정한 뒤 별도 추가합니다.

## 성공 기준

공통:

- `http_req_failed < 1%`
- backend 5xx 급증 없음
- backend/Elasticsearch/Redis OOM 없음
- RDS PostgreSQL connection 고갈 없음

latency:

- `type=fast` p95 < 500ms
  - health
  - popular products
  - product detail
- `type=search` p95 < 1000ms
  - recommendation create
  - recommendation page
- `type=write` p95 < 1500ms
  - anonymous cart add

k6 threshold 실패 시 해당 run은 실패로 봅니다.

## 관측 지표

서버 리소스:

```bash
docker stats
```

서버 전체:

```bash
htop
free -h
df -h
```

backend 로그:

```bash
docker compose logs -f --tail=100 backend
```

RDS/Postgres connection:

```bash
docker compose exec backend python - <<'PY'
from app.db.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    print(db.execute(text("select count(*) from pg_stat_activity")).scalar())
PY
```

ES health:

```bash
curl http://127.0.0.1:9200/_cluster/health?pretty
```

Redis ping:

```bash
docker compose exec redis redis-cli ping
```

## 결과 기록 양식

```text
date:
git sha:
server:
db:
profile:
cart writes:

k6:
- http_reqs/s:
- http_req_failed:
- http_req_duration p95:
- type=fast p95:
- type=search p95:
- type=write p95:

server:
- backend max cpu/mem:
- rds/postgres connection max:
- elasticsearch max cpu/mem:
- redis max cpu/mem:
- pg_stat_activity max:

result:
- PASS/FAIL:
- bottleneck:
- next action:
```

## 주의

- `stress`는 dev 서버 리소스 한계를 찾는 용도입니다. 팀 작업 시간에는 먼저 공유 후 실행합니다.
- `ENABLE_CART_WRITES=true`는 DB에 익명 cart 데이터를 생성합니다. 반복 실행 후 필요하면 테스트 데이터 정리를 별도 진행합니다.
- 주문 생성, 결제 중복, 재고 차감 동시성은 #267에서 별도 스크립트로 다룹니다.
- k6 스크립트는 브라우저 테스트가 아닙니다. React 화면을 열지 않고 FastAPI API를 직접 호출합니다.
