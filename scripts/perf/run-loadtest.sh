#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel)"
CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

PROFILE="${1:-${PROFILE:-smoke}}"
SSH_USER="${SSH_USER:-ubuntu}"
SSH_HOST="${SSH_HOST:-}"
SSH_KEY="${SSH_KEY:-}"
REMOTE_APP_DIR="${REMOTE_APP_DIR:-/home/ubuntu/mwobareullae}"
BACKEND_SERVICE="${BACKEND_SERVICE:-backend}"
POSTGRES_SERVICE="${POSTGRES_SERVICE:-postgres}"
BACKEND_CONTAINER="${BACKEND_CONTAINER:-mwobareullae-backend}"
POSTGRES_CONTAINER="${POSTGRES_CONTAINER:-mwobareullae-postgres}"
REDIS_CONTAINER="${REDIS_CONTAINER:-mwobareullae-redis}"
ELASTICSEARCH_CONTAINER="${ELASTICSEARCH_CONTAINER:-mwobareullae-elasticsearch}"
DB_MONITOR_MODE="${DB_MONITOR_MODE:-backend}"
DB_NAME="${DB_NAME:-mwobareullae_small}"
DB_USER="${DB_USER:-mwobareullae}"
DATA_DIR="${DATA_DIR:-/data/dev-small}"
DATA_LABEL="${DATA_LABEL:-small-1000}"
K6_SCRIPT="${K6_SCRIPT:-tests/k6/commerce-smoke.js}"
BASE_URL="${BASE_URL:-https://dev.api.mubarelle.com/api}"
CART_WRITES="${CART_WRITES:-false}"
PRODUCT_IDS="${PRODUCT_IDS:-}"
HEAVY_PRODUCT_IDS="${HEAVY_PRODUCT_IDS:-}"
SEARCH_QUERIES="${SEARCH_QUERIES:-}"
DEBUG_ERRORS="${DEBUG_ERRORS:-false}"
SLA_MS="${SLA_MS:-3000}"
SAMPLE_INTERVAL="${SAMPLE_INTERVAL:-10}"
RESULT_ROOT="${RESULT_ROOT:-$REPO_DIR/perf-runs}"
RUN_K6="${RUN_K6:-true}"
SLACK_ENABLED="${SLACK_ENABLED:-false}"
REPORT_TITLE="${REPORT_TITLE:-k6 Performance Run}"
RDS_METRICS_ENABLED="${RDS_METRICS_ENABLED:-true}"
RDS_DB_INSTANCE_IDENTIFIER="${RDS_DB_INSTANCE_IDENTIFIER:-mubarelle-db}"
AWS_REGION="${AWS_REGION:-ap-northeast-2}"
CLOUDWATCH_WAIT_SECONDS="${CLOUDWATCH_WAIT_SECONDS:-180}"
CLOUDWATCH_PERIOD_SECONDS="${CLOUDWATCH_PERIOD_SECONDS:-60}"
RDS_CPU_AVG_WARN_PCT="${RDS_CPU_AVG_WARN_PCT:-40}"

case "$RESULT_ROOT" in
  /*) ;;
  *) RESULT_ROOT="$REPO_DIR/$RESULT_ROOT" ;;
esac

TIMESTAMP="$(date +%Y%m%d-%H%M%S)"
SAFE_DATA_LABEL="$(printf '%s' "$DATA_LABEL" | tr -cs '[:alnum:]_.-' '-')"
RESULT_DIR="$RESULT_ROOT/${TIMESTAMP}_${PROFILE}_${SAFE_DATA_LABEL}"
mkdir -p "$RESULT_DIR"

K6_JSON="$RESULT_DIR/k6-result.ndjson"
K6_STDOUT="$RESULT_DIR/k6-output.txt"
K6_SUMMARY_JSON="$RESULT_DIR/k6-summary.json"
STATS_LOG="$RESULT_DIR/docker-stats.log"
PG_LOG="$RESULT_DIR/pg-stat-activity.log"
BACKEND_LOG="$RESULT_DIR/backend.log"
REPORT_MD="$RESULT_DIR/report.md"
DATA_COUNTS="$RESULT_DIR/data-counts.txt"
CONTAINER_HEALTH="$RESULT_DIR/container-health.txt"
SLOW_QUERY_SAMPLE="$RESULT_DIR/slow-query-sample.log"
NOTABLE_ERRORS="$RESULT_DIR/notable-errors.log"
RDS_METRICS_JSON="$RESULT_DIR/rds-metrics.json"
RDS_METRICS_LOG="$RESULT_DIR/rds-metrics.log"

log() {
  echo "[$(date '+%H:%M:%S')] $*"
}

require_config() {
  local name="$1"
  local value="$2"
  if [ -z "$value" ] || [[ "$value" == \<* ]]; then
    echo "Missing required config: $name" >&2
    echo "Copy scripts/perf/config.example.env to scripts/perf/config.env and fill $name." >&2
    exit 1
  fi
}

utc_now() {
  date -u '+%Y-%m-%dT%H:%M:%S+00:00'
}

kst_now() {
  TZ=Asia/Seoul date '+%Y-%m-%dT%H:%M:%S+09:00'
}

ssh_cmd() {
  ssh -o BatchMode=yes -i "$SSH_KEY" "${SSH_USER}@${SSH_HOST}" "$@"
}

remote_collect_once() {
  ssh_cmd "cd '$REMOTE_APP_DIR' && $1"
}

start_monitoring() {
  log "remote monitoring start: interval=${SAMPLE_INTERVAL}s"
  ssh -o BatchMode=yes -i "$SSH_KEY" "${SSH_USER}@${SSH_HOST}" \
    "REMOTE_APP_DIR='$REMOTE_APP_DIR' SAMPLE_INTERVAL='$SAMPLE_INTERVAL' DB_MONITOR_MODE='$DB_MONITOR_MODE' DB_NAME='$DB_NAME' DB_USER='$DB_USER' BACKEND_SERVICE='$BACKEND_SERVICE' POSTGRES_SERVICE='$POSTGRES_SERVICE' bash -s" \
    >"$STATS_LOG" 2>&1 <<'REMOTE_SCRIPT' &
cd "$REMOTE_APP_DIR"
while true; do
  echo "=== $(date -u -Is) ==="
  docker stats --no-stream --format "{{.Name}} {{.CPUPerc}} {{.MemUsage}}" || true
  echo "--- pg_stat_activity ---"
  if [ "$DB_MONITOR_MODE" = "backend" ]; then
    docker compose exec -T "$BACKEND_SERVICE" python - <<'PY' || true
from app.db.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    rows = db.execute(
        text(
            "select coalesce(state, 'unknown') as state, count(*) "
            "from pg_stat_activity "
            "where datname = current_database() "
            "group by state order by count(*) desc"
        )
    ).fetchall()
    for state, count in rows:
        print(f"{state} | {count}")
PY
  else
    docker compose exec -T "$POSTGRES_SERVICE" psql -U "$DB_USER" -d "$DB_NAME" -t -c \
      "select coalesce(state,'unknown'), count(*) from pg_stat_activity where datname='${DB_NAME}' group by state order by count(*) desc;" || true
  fi
  sleep "$SAMPLE_INTERVAL"
done
REMOTE_SCRIPT
  MONITOR_PID=$!
  echo "$MONITOR_PID" >"$RESULT_DIR/monitor.pid"
}

stop_monitoring() {
  if [ -n "${MONITOR_PID:-}" ]; then
    log "remote monitoring stop: pid=$MONITOR_PID"
    kill "$MONITOR_PID" 2>/dev/null || true
    wait "$MONITOR_PID" 2>/dev/null || true
  fi
}

collect_pg_snapshot() {
  if [ "$DB_MONITOR_MODE" = "backend" ]; then
    ssh -o BatchMode=yes -i "$SSH_KEY" "${SSH_USER}@${SSH_HOST}" \
      "cd '$REMOTE_APP_DIR' && docker compose exec -T '$BACKEND_SERVICE' python -" \
      >>"$PG_LOG" 2>&1 <<'PY' || true
from app.db.session import SessionLocal
from sqlalchemy import text

with SessionLocal() as db:
    rows = db.execute(
        text(
            "select coalesce(state, 'unknown') as state, count(*) "
            "from pg_stat_activity "
            "where datname = current_database() "
            "group by state order by count(*) desc"
        )
    ).fetchall()
    for state, count in rows:
        print(f"{state} | {count}")
PY
  else
    remote_collect_once "docker compose exec -T '$POSTGRES_SERVICE' psql -U '$DB_USER' -d '$DB_NAME' -c \"select state, count(*) from pg_stat_activity where datname='$DB_NAME' group by state order by count(*) desc;\"" \
      >>"$PG_LOG" 2>&1 || true
  fi
}

collect_data_counts() {
  log "collect data counts"
  if [ "$DB_MONITOR_MODE" = "backend" ]; then
    ssh -o BatchMode=yes -i "$SSH_KEY" "${SSH_USER}@${SSH_HOST}" \
      "cd '$REMOTE_APP_DIR' && docker compose exec -T '$BACKEND_SERVICE' python -" \
      >"$DATA_COUNTS" 2>&1 <<'PY' || true
from app.db.session import SessionLocal
from sqlalchemy import text

queries = [
    ("products", "select count(*) from products"),
    ("product_images", "select count(*) from product_images"),
    ("product_ingredients", "select count(*) from product_ingredients"),
    ("ingredients", "select count(*) from ingredients"),
    ("inventories", "select count(*) from inventories"),
    ("brands", "select count(*) from brands"),
    ("product_categories", "select count(*) from product_categories"),
    ("product_prices", "select count(*) from product_prices"),
    ("product_skin_profiles", "select count(*) from product_skin_profiles"),
    ("search_documents", "select count(*) from search_documents"),
    ("embedded_documents", "select count(*) from search_documents where embedding is not null"),
    ("image_non_jpg", "select count(*) from product_images where storage_key not like '%.jpg'"),
]

with SessionLocal() as db:
    for name, sql in queries:
        print(f"{name}={db.execute(text(sql)).scalar()}")
PY
  else
    remote_collect_once "docker compose exec -T '$POSTGRES_SERVICE' psql -U '$DB_USER' -d '$DB_NAME' -At -F '=' -c \"
select 'products', count(*) from products
union all
select 'product_images', count(*) from product_images
union all
select 'product_ingredients', count(*) from product_ingredients
union all
select 'ingredients', count(*) from ingredients
union all
select 'inventories', count(*) from inventories
union all
select 'brands', count(*) from brands
union all
select 'product_categories', count(*) from product_categories
union all
select 'product_prices', count(*) from product_prices
union all
select 'product_skin_profiles', count(*) from product_skin_profiles
union all
select 'search_documents', count(*) from search_documents
union all
select 'embedded_documents', count(*) from search_documents where embedding is not null
union all
select 'image_non_jpg', count(*) from product_images where storage_key not like '%.jpg'
order by 1;
\"" >"$DATA_COUNTS" 2>&1 || true
  fi
}

collect_container_health() {
  log "collect container restart/OOM"
  if [ "$DB_MONITOR_MODE" = "backend" ]; then
    remote_collect_once "docker inspect '$BACKEND_CONTAINER' --format='backend restart={{.RestartCount}} oom={{.State.OOMKilled}}'; echo 'postgres external=RDS'; docker inspect '$ELASTICSEARCH_CONTAINER' --format='elasticsearch restart={{.RestartCount}} oom={{.State.OOMKilled}}'; docker inspect '$REDIS_CONTAINER' --format='redis restart={{.RestartCount}} oom={{.State.OOMKilled}}'" \
      >"$CONTAINER_HEALTH" 2>&1 || true
  else
    remote_collect_once "docker inspect '$BACKEND_CONTAINER' --format='backend restart={{.RestartCount}} oom={{.State.OOMKilled}}'; docker inspect '$POSTGRES_CONTAINER' --format='postgres restart={{.RestartCount}} oom={{.State.OOMKilled}}'; docker inspect '$ELASTICSEARCH_CONTAINER' --format='elasticsearch restart={{.RestartCount}} oom={{.State.OOMKilled}}'; docker inspect '$REDIS_CONTAINER' --format='redis restart={{.RestartCount}} oom={{.State.OOMKilled}}'" \
      >"$CONTAINER_HEALTH" 2>&1 || true
  fi
}

collect_rds_metrics() {
  if [ "$RDS_METRICS_ENABLED" != "true" ]; then
    log "RDS metrics skipped"
    printf '{"metadata":{"enabled":false},"metrics":{}}\n' >"$RDS_METRICS_JSON"
    return
  fi

  log "collect RDS CloudWatch metrics: db=$RDS_DB_INSTANCE_IDENTIFIER region=$AWS_REGION"
  ssh -o BatchMode=yes -i "$SSH_KEY" "${SSH_USER}@${SSH_HOST}" \
    "AWS_REGION='$AWS_REGION' RDS_DB_INSTANCE_IDENTIFIER='$RDS_DB_INSTANCE_IDENTIFIER' CLOUDWATCH_PERIOD_SECONDS='$CLOUDWATCH_PERIOD_SECONDS' bash -s -- '$START_TIME_UTC' '$END_TIME_UTC'" \
    <"$SCRIPT_DIR/collect_rds_metrics.sh" >"$RDS_METRICS_JSON" 2>"$RDS_METRICS_LOG" || {
      log "RDS metrics collection failed. See $(basename "$RDS_METRICS_LOG")"
      python3 - "$RDS_METRICS_JSON" "$RDS_METRICS_LOG" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

out_path = Path(sys.argv[1])
log_path = Path(sys.argv[2])
out_path.write_text(
    json.dumps(
        {
            "metadata": {"enabled": True, "error": log_path.read_text(encoding="utf-8", errors="ignore")},
            "metrics": {},
        },
        ensure_ascii=False,
        indent=2,
    ),
    encoding="utf-8",
)
PY
    }
}

run_k6() {
  log "k6 run: profile=$PROFILE base_url=$BASE_URL cart_writes=$CART_WRITES"
  set +e
  (
    cd "$REPO_DIR"
    k6 run \
      --out "json=$K6_JSON" \
      -e BASE_URL="$BASE_URL" \
      -e PROFILE="$PROFILE" \
      -e CART_WRITES="$CART_WRITES" \
      -e PRODUCT_IDS="$PRODUCT_IDS" \
      -e HEAVY_PRODUCT_IDS="$HEAVY_PRODUCT_IDS" \
      -e SEARCH_QUERIES="$SEARCH_QUERIES" \
      -e DEBUG_ERRORS="$DEBUG_ERRORS" \
      -e SLA_MS="$SLA_MS" \
      -e AUTH_HOME_FOR_YOU="${AUTH_HOME_FOR_YOU:-false}" \
      -e AUTH_COOKIE="${AUTH_COOKIE:-}" \
      "$K6_SCRIPT"
  ) 2>&1 | tee "$K6_STDOUT"
  K6_EXIT="${PIPESTATUS[0]}"
  set -e
  echo "$K6_EXIT" >"$RESULT_DIR/k6-exit-code.txt"
}

extract_backend_logs() {
  log "extract backend logs"
  remote_collect_once "docker compose logs --since '$START_TIME_UTC' --until '$END_TIME_UTC' '$BACKEND_SERVICE'" \
    >"$BACKEND_LOG" 2>&1 || true
  grep '"event":"db_slow_query"' "$BACKEND_LOG" | head -50 >"$SLOW_QUERY_SAMPLE" || true
  grep -E ' 5[0-9][0-9] |(^|[[:space:]])ERROR([[:space:]:]|$)|Traceback|Exception|status_code":5' "$BACKEND_LOG" \
    | head -100 >"$NOTABLE_ERRORS" || true
}

generate_summary() {
  log "parse k6 output"
  if [ -s "$K6_JSON" ]; then
    python3 "$SCRIPT_DIR/parse_k6.py" "$K6_JSON" >"$K6_SUMMARY_JSON"
  else
    printf '{"total_requests":0,"failed_rate_pct":0,"by_type":{}}\n' >"$K6_SUMMARY_JSON"
  fi

  log "generate report"
  python3 "$SCRIPT_DIR/generate_report.py" \
    --title "$REPORT_TITLE" \
    --profile "$PROFILE" \
    --git-sha "$GIT_SHA" \
    --server "Dev EC2 t3.large" \
    --db-name "$DB_NAME" \
    --data-dir "$DATA_DIR" \
    --data-label "$DATA_LABEL" \
    --cart-writes "$CART_WRITES" \
    --start-utc "$START_TIME_UTC" \
    --end-utc "$END_TIME_UTC" \
    --start-kst "$START_TIME_KST" \
    --end-kst "$END_TIME_KST" \
    --k6-summary "$K6_SUMMARY_JSON" \
    --stats-log "$STATS_LOG" \
    --backend-log "$BACKEND_LOG" \
    --data-counts "$DATA_COUNTS" \
    --container-health "$CONTAINER_HEALTH" \
    --rds-metrics "$RDS_METRICS_JSON" \
    --rds-cpu-avg-warn-pct "$RDS_CPU_AVG_WARN_PCT" \
    --sla-ms "$SLA_MS" \
    --out "$REPORT_MD"
}

GIT_SHA="$(git -C "$REPO_DIR" rev-parse --short HEAD 2>/dev/null || echo unknown)"
log "repo=$REPO_DIR"
log "result_dir=$RESULT_DIR"
log "git_sha=$GIT_SHA"

require_config "SSH_HOST" "$SSH_HOST"
require_config "SSH_KEY" "$SSH_KEY"
require_config "REMOTE_APP_DIR" "$REMOTE_APP_DIR"

collect_data_counts
collect_container_health

if [ "$RUN_K6" = "true" ]; then
  START_TIME_UTC="$(utc_now)"
  START_TIME_KST="$(kst_now)"
  start_monitoring
  sleep 2
  run_k6
  END_TIME_UTC="$(utc_now)"
  END_TIME_KST="$(kst_now)"
  stop_monitoring
else
  START_TIME_UTC="${START_TIME_UTC:?START_TIME_UTC is required when RUN_K6=false}"
  END_TIME_UTC="${END_TIME_UTC:?END_TIME_UTC is required when RUN_K6=false}"
  START_TIME_KST="${START_TIME_KST:-$START_TIME_UTC}"
  END_TIME_KST="${END_TIME_KST:-$END_TIME_UTC}"
  log "RUN_K6=false. Collect logs only."
  printf "RUN_K6=false\n" >"$K6_STDOUT"
  printf "{}\n" >"$K6_JSON"
fi

collect_pg_snapshot
if [ "$RUN_K6" = "true" ] && [ "$RDS_METRICS_ENABLED" = "true" ] && [ "${CLOUDWATCH_WAIT_SECONDS:-0}" -gt 0 ]; then
  log "wait CloudWatch aggregation: ${CLOUDWATCH_WAIT_SECONDS}s"
  sleep "$CLOUDWATCH_WAIT_SECONDS"
fi
collect_rds_metrics
extract_backend_logs
generate_summary

if [ "$SLACK_ENABLED" = "true" ]; then
  bash "$SCRIPT_DIR/send_to_slack.sh" \
    "$REPORT_MD" \
    "$K6_SUMMARY_JSON" \
    "$BACKEND_LOG" \
    "$STATS_LOG" \
    "$SLOW_QUERY_SAMPLE" \
    "$NOTABLE_ERRORS" || true
else
  log "Slack skipped"
fi

log "done: $RESULT_DIR"
