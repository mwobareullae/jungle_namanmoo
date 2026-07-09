# k6 Performance Run Automation

Dev 서버 성능테스트에서 반복하던 작업을 줄이기 위한 로컬 실행용 도구입니다.

이 스크립트는 로컬 Mac에서 k6를 실행하고, SSH로 Dev EC2에 접속해 Docker/DB/백엔드 로그를 수집합니다.

## Files

| 파일 | 역할 |
| --- | --- |
| `run-loadtest.sh` | k6 실행, 서버 관측, 로그 수집, 리포트 생성 |
| `parse_k6.py` | k6 NDJSON 결과를 요약 JSON으로 변환 |
| `generate_report.py` | Notion에 붙일 수 있는 Markdown 리포트 생성 |
| `send_to_slack.sh` | 선택 사항. Slack 요약/파일 업로드 |
| `config.example.env` | 로컬 설정 템플릿 |

## 실행 구조

기본 원칙은 **로컬 Mac에서 k6 실행 + SSH로 Dev 서버 지표/로그 수집**입니다.

```text
Local Mac
  ├─ k6 run tests/k6/commerce-smoke.js
  ├─ perf-runs/<timestamp>_<profile>_<data-label>/ 생성
  └─ SSH 접속
       └─ Dev EC2
            ├─ docker stats 수집
            ├─ pg_stat_activity 수집
            ├─ docker compose logs backend 수집
            └─ 데이터 건수 / 컨테이너 restart/OOM 수집
```

이 방식은 k6 client 부하가 Dev 서버 CPU/메모리를 먹지 않아서 서버 병목을 더 깨끗하게 볼 수 있습니다.

Dev 서버에서 직접 k6를 실행하는 경우는 아래처럼 제한합니다.

| 실행 위치 | 사용 시점 |
| --- | --- |
| 로컬 Mac | 기본 기준선 측정, 도메인/TLS/Caddy 포함 실제 접근 경로 확인, 팀 공유용 결과 생성 |
| Dev 서버 | 외부 네트워크 영향을 빼고 내부 API만 보고 싶을 때, 로컬 네트워크가 불안정할 때 |

## 1. 사전 준비

로컬 Mac에 필요한 도구가 있어야 합니다.

```bash
k6 version
ssh -V
python3 --version
```

`k6`가 없으면 Homebrew로 설치합니다.

```bash
brew install k6
```

Dev 서버에는 Docker Compose로 아래 컨테이너가 떠 있어야 합니다.

```text
backend
postgres
elasticsearch
redis
frontend
```

Dev 서버 기준 API URL은 도메인을 우선 사용합니다.

```bash
BASE_URL=https://dev.api.mubarelle.com/api
```

IP 직접 접근 비교가 필요할 때만 아래 값을 별도 실행에 사용합니다.

```bash
BASE_URL=http://<dev-server-ip>:8000/api
```

## 2. 로컬 설정 파일 만들기

```bash
# 프로젝트 루트에서 실행
cp scripts/perf/config.example.env scripts/perf/config.env
```

`scripts/perf/config.env`에서 SSH key, DB, BASE_URL 값을 본인 환경에 맞춥니다.

`config.env`는 secret이나 개인 경로가 들어갈 수 있으므로 git에 올리지 않습니다.

최소로 확인할 값은 아래입니다.

```env
SSH_USER="ubuntu"
SSH_HOST="<dev-server-host-or-ip>"
SSH_KEY="<ssh-key-path>"

REMOTE_APP_DIR="/home/ubuntu/mwobareullae"

DB_MONITOR_MODE="backend"
DB_NAME="mwobareullae"
DB_USER="mwobareullae"
DATA_DIR="/data"
DATA_LABEL="full-36000"

BASE_URL="https://dev.api.mubarelle.com/api"
REPORT_TITLE="Dev API k6 Performance Run"
CART_WRITES="false"
SEARCH_QUERIES="세럼,수분 크림,나이아신아마이드,진정,선크림"
HEAVY_PRODUCT_IDS=""
SLA_MS=3000

RDS_METRICS_ENABLED="true"
RDS_DB_INSTANCE_IDENTIFIER="mubarelle-db"
AWS_REGION="ap-northeast-2"
CLOUDWATCH_WAIT_SECONDS=180
```

`scripts/perf/config.env`는 `.gitignore`에 포함되어 있어야 합니다.

## 3. 실행 전 연결 확인

부하테스트 전에 SSH와 API health를 먼저 확인합니다.

```bash
ssh -i "<ssh-key-path>" ubuntu@<dev-server-host-or-ip> "cd /home/ubuntu/mwobareullae && docker compose ps"
curl -fsS https://dev.api.mubarelle.com/api/health
```

서버에서 DB 이름이 맞는지도 확인합니다.

```bash
ssh -i "<ssh-key-path>" ubuntu@<dev-server-host-or-ip> \
  "cd /home/ubuntu/mwobareullae && docker compose exec -T backend python - <<'PY'
from app.db.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    print(db.execute(text('select current_database()')).scalar())
    print(db.execute(text('select count(*) from products')).scalar())
PY"
```

여기서 SSH, docker compose, DB 접속 중 하나라도 실패하면 `run-loadtest.sh`도 로그/지표 수집이 비어 있을 수 있습니다.

RDS CloudWatch 지표는 Dev 서버 EC2 IAM Role을 사용합니다. 서버에서 아래 명령이 동작하면 별도 AWS key 설정은 필요 없습니다.

```bash
ssh -i "<ssh-key-path>" ubuntu@<dev-server-host-or-ip> \
  'START=$(date -u -d "10 minutes ago" +%Y-%m-%dT%H:%M:%S); END=$(date -u +%Y-%m-%dT%H:%M:%S); aws cloudwatch get-metric-statistics --namespace AWS/RDS --metric-name CPUUtilization --dimensions Name=DBInstanceIdentifier,Value=mubarelle-db --start-time "$START" --end-time "$END" --period 60 --statistics Average Maximum --region ap-northeast-2 --output json'
```

## 4. Smoke 실행

가장 먼저 smoke로 전체 자동화가 정상 동작하는지 확인합니다.

```bash
scripts/perf/run-loadtest.sh smoke
```

smoke는 1 VU로 1분 동안 실행됩니다. 이 단계의 목적은 성능 판단이 아니라 아래를 확인하는 것입니다.

- k6가 API를 호출할 수 있는지
- SSH로 Dev 서버에 접속할 수 있는지
- DB count, docker stats, backend log가 수집되는지
- `report.md`가 생성되는지

## 5. Baseline 실행

smoke가 통과하면 기준선 측정을 실행합니다.

```bash
scripts/perf/run-loadtest.sh baseline
```

baseline은 10 VU로 4분 동안 실행됩니다. 36,000건 상품 데이터 기준 주요 API 응답 기준선을 잡는 용도입니다.

## 6. Cart Write 포함 실행

기본 baseline은 읽기/추천 중심입니다. 장바구니 쓰기까지 포함하려면 별도 실행으로 분리합니다.

```bash
CART_WRITES=true scripts/perf/run-loadtest.sh baseline
```

이 실행은 익명 cart item을 실제로 생성하므로 결과 기록에 `cart writes: true`를 반드시 남깁니다.

## 7. Full DB 기준 설정

`scripts/perf/config.env`를 full DB 기준으로 바꿉니다.

```env
DB_NAME="mwobareullae"
DATA_DIR="/data"
DATA_LABEL="full-36000"
```

그 다음 실행합니다.

```bash
scripts/perf/run-loadtest.sh baseline
```

## 8. 결과 위치

결과는 기본적으로 아래에 생성됩니다.

```text
perf-runs/<timestamp>_<profile>_<data-label>/
├── backend.log
├── container-health.txt
├── data-counts.txt
├── docker-stats.log
├── k6-output.txt
├── k6-result.ndjson
├── k6-summary.json
├── notable-errors.log
├── pg-stat-activity.log
├── report.md
├── rds-metrics.json
├── rds-metrics.log
└── slow-query-sample.log
```

백엔드/검색 담당에게는 보통 아래를 전달하면 됩니다.

```text
report.md
backend.log
slow-query-sample.log
notable-errors.log
```

## 9. report.md 기록 기준

`report.md`에는 아래 항목이 자동으로 정리됩니다.

```text
date:
git sha:
server:
db:
data count:
profile:
cart writes:

k6:
- http_reqs/s:
- http_req_failed:
- http_req_duration avg:
- http_req_duration p95:
- type=fast p95:
- type=search p95:
- type=write p95:
- endpoint별 avg/p95:

server:
- backend max cpu/mem:
- postgres max cpu/mem:
- elasticsearch max cpu/mem:
- redis max cpu/mem:
- pg_stat_activity max:
- RDS CPU/Memory/Connection/IOPS/Latency/Storage:

result:
- PASS/FAIL:
- bottleneck:
- next action:
```

팀 공유 시에는 `report.md` 내용을 노션에 붙이고, 필요하면 아래 파일을 같이 첨부합니다.

```text
backend.log
slow-query-sample.log
notable-errors.log
```

## 10. Logs Only Mode

k6는 이미 실행했고 특정 시간대 로그만 다시 자르고 싶을 때 사용합니다.

```bash
RUN_K6=false \
START_TIME_UTC="2026-07-07T09:36:09+00:00" \
END_TIME_UTC="2026-07-07T09:40:15+00:00" \
scripts/perf/run-loadtest.sh baseline
```

이 모드는 `START_TIME_UTC`, `END_TIME_UTC`가 필수입니다.

## 11. 자주 막히는 지점

### config.env가 없을 때

아래 명령으로 생성합니다.

```bash
cp scripts/perf/config.example.env scripts/perf/config.env
```

### SSH가 안 될 때

키 경로와 권한을 확인합니다.

```bash
ls -l "<ssh-key-path>"
chmod 600 "<ssh-key-path>"
```

그 다음 직접 접속을 확인합니다.

```bash
ssh -i "<ssh-key-path>" ubuntu@<dev-server-host-or-ip> "hostname"
```

### report.md는 생겼지만 서버 지표가 N/A일 때

대부분 아래 중 하나입니다.

- `REMOTE_APP_DIR`가 실제 서버 compose 경로와 다름
- `DB_NAME`이 실제 DB 이름과 다름
- `DB_MONITOR_MODE`가 현재 서버 구조와 다름
- `BACKEND_CONTAINER`, `REDIS_CONTAINER`, `ELASTICSEARCH_CONTAINER` 이름이 compose와 다름
- SSH 접속은 되지만 docker 권한이 없음

### RDS 지표가 N/A일 때

대부분 아래 중 하나입니다.

- `RDS_METRICS_ENABLED=false`
- `RDS_DB_INSTANCE_IDENTIFIER`가 실제 RDS identifier와 다름
- Dev 서버에 AWS CLI가 없거나 EC2 IAM Role 권한이 부족함
- CloudWatch 집계 지연 때문에 최근 datapoint가 아직 없음

`smoke`는 실행 시간이 짧아 datapoint가 1~2개만 잡힐 수 있습니다. RDS 병목 판단은 `baseline` 이상에서 보는 것을 권장합니다.

### k6가 400/404를 많이 낼 때

`DEBUG_ERRORS=true`로 한 번만 짧게 실행합니다.

```bash
DEBUG_ERRORS=true scripts/perf/run-loadtest.sh smoke
```

`k6-output.txt`와 `backend.log`에서 실패 응답을 확인합니다.

## 12. 테스트 대상 API 확장 기준

현재 k6 시나리오는 8만 상품/대규모 성분 데이터에서 병목 가능성이 큰 읽기/검색/추천 흐름을 포함합니다.

```text
GET  /api/health
GET  /api/products/popular
GET  /api/products/{product_id}
GET  /api/products/search
GET  /api/home/layout
GET  /api/home/market-popular
GET  /api/home/evidence-picks
GET  /api/home/for-you
POST /api/recommendations
GET  /api/recommendations/{recommendation_id}
GET  /api/products/{product_id}?recommendation_id=...
POST /api/cart/items          # CART_WRITES=true 일 때만
POST /api/checkout/preview    # CART_WRITES=true 일 때만
```

검색어는 `SEARCH_QUERIES`로 조절합니다.
로그인 사용자 홈 추천은 `AUTH_HOME_FOR_YOU=true`와 `AUTH_COOKIE`를 설정했을 때만 추가 실행합니다.
리포트 제목은 `REPORT_TITLE`로 조절합니다.

```env
SEARCH_QUERIES="세럼,수분 크림,나이아신아마이드,진정,선크림"
```

성분이 많거나 이미지/가격/evidence가 무거운 상품 상세를 따로 보고 싶으면 `HEAVY_PRODUCT_IDS`를 지정합니다.

```env
HEAVY_PRODUCT_IDS="prod_001,prod_002"
```

리포트의 `Endpoint` 섹션에서 endpoint별 `avg`, `p95`를 확인하고, 가장 느린 endpoint를 백엔드 병목 후보로 전달합니다.

## Notes

- k6는 가능하면 Dev 서버가 아니라 로컬에서 실행합니다.
- Dev 서버에서는 backend/postgres/elasticsearch/redis만 실행 중인 상태가 좋습니다.
- Slack 전송은 기본 비활성화입니다. `SLACK_ENABLED=true`일 때만 실행됩니다.
- `.env`, `scripts/perf/config.env`, `perf-runs/`는 커밋하지 않습니다.
