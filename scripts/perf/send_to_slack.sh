#!/usr/bin/env bash
set -uo pipefail
# 주의: 전체 스크립트에 set -e 를 걸지 않습니다.
# 파일 업로드가 하나 실패해도 나머지는 계속 시도해야 하기 때문입니다.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="$SCRIPT_DIR/config.env"

if [ -f "$CONFIG_FILE" ]; then
  # shellcheck disable=SC1090
  source "$CONFIG_FILE"
fi

if [ "${SLACK_ENABLED:-false}" != "true" ]; then
  echo "Slack disabled. Set SLACK_ENABLED=true to send summary/files."
  exit 0
fi

SLACK_UPLOAD_FILES="${SLACK_UPLOAD_FILES:-true}"

if ! command -v jq >/dev/null 2>&1; then
  echo "jq is required for Slack delivery."
  exit 1
fi

REPORT_MD="${1:?report.md path required}"
K6_SUMMARY_JSON="${2:-}"
BACKEND_LOG="${3:-}"
STATS_LOG="${4:-}"
SLOW_QUERY_SAMPLE="${5:-}"
NOTABLE_ERRORS_LOG="${6:-}"

if [ -n "${SLACK_CHANNEL:-}" ]; then
  case "$SLACK_CHANNEL" in
    C*|G*|D*) ;;
    *)
      echo "WARN: SLACK_CHANNEL='${SLACK_CHANNEL}' is not a channel ID."
      echo "      Use the Slack Channel ID, usually starting with C, G, or D."
      ;;
  esac
fi

table_value() {
  local label="$1"
  awk -F '|' -v target="$label" '
    {
      key=$2
      value=$3
      gsub(/^[ \t]+|[ \t]+$/, "", key)
      gsub(/^[ \t]+|[ \t]+$/, "", value)
      if (key == target) {
        print value
        exit
      }
    }
  ' "$REPORT_MD"
}

PROFILE="$(table_value "Profile")"
DATA_LABEL="$(table_value "Data label")"
CART_WRITES="$(table_value "Cart writes")"
AUTH_HOME_FOR_YOU="$(table_value "Auth home for-you")"
PASS_FAIL="$(table_value "PASS / FAIL")"
FAIL_REASON="$(table_value "실패 이유")"
BOTTLENECK="$(table_value "Bottleneck 후보")"
NEXT_ACTION="$(table_value "Next Action")"
REQS_PER_SEC="$(table_value "http_reqs/s")"
FAILED_RATE="$(table_value "http_req_failed")"
FAST_P95="$(table_value "type=fast p95")"
SEARCH_P95="$(table_value "type=search p95")"
CATALOG_SEARCH_P95="$(table_value "type=catalog_search p95")"
CATALOG_SUGGESTIONS_P95="$(table_value "type=catalog_suggestions p95")"
WRITE_P95="$(table_value "type=write p95")"
SLOW_QUERIES="$(table_value "Slow query count")"
NOTABLE_ERRORS="$(table_value "Notable errors")"
BACKEND_CPU_MEM="$(table_value "backend max cpu/mem")"
POSTGRES_CPU_MEM="$(table_value "postgres max cpu/mem")"
ES_CPU_MEM="$(table_value "elasticsearch max cpu/mem")"

IS_FAIL=false
case "$PASS_FAIL" in
  *FAIL*) IS_FAIL=true ;;
esac

if [ "$SLACK_UPLOAD_FILES" = "true" ]; then
  HANDOFF_FILE_NOTE="확인용 첨부: backend.log, slow-query-sample.log, docker-stats.log"
else
  HANDOFF_FILE_NOTE="확인용 파일: 로컬 perf-runs 결과 폴더의 backend.log, slow-query-sample.log, docker-stats.log"
fi

BACKEND_HANDOFF=""
if [ "$IS_FAIL" = true ]; then
  BACKEND_HANDOFF="$(cat <<HANDOFF

*백엔드/검색 담당자 확인 요청*
1. \`recommendation_pipeline_completed\` 로그의 단계별 소요시간 중 (candidate_load_ms / search_match_ms / scoring_ms / result_save_ms / commit_ms / response_load_ms) 가장 큰 구간이 어디인지
2. \`slow-query-sample.log\`에 반복되는 SQL 패턴이 있는지
3. postgres \`idle in transaction\` 상태가 오래 유지되는 이유 (session commit/flush 타이밍, 응답 조립 시 transaction 유지 여부)
4. 이번 profile(${PROFILE:-N/A}) 기준 search 계열 p95를 SLA 이내로 줄이기 위한 우선순위
${HANDOFF_FILE_NOTE}
HANDOFF
)"
fi

SUMMARY_TEXT="$(cat <<SUMMARY
*k6 ${PASS_FAIL:-Result}*
*Profile*: ${PROFILE:-N/A} / *Data*: ${DATA_LABEL:-N/A} / *Cart writes*: ${CART_WRITES:-N/A}
*Auth home for-you*: ${AUTH_HOME_FOR_YOU:-N/A}
*k6*: ${REQS_PER_SEC:-N/A}, failed ${FAILED_RATE:-N/A}
*p95*: fast ${FAST_P95:-N/A}, search ${SEARCH_P95:-N/A}, catalog ${CATALOG_SEARCH_P95:-N/A}, suggestions ${CATALOG_SUGGESTIONS_P95:-N/A}, write ${WRITE_P95:-N/A}
*Server*: backend ${BACKEND_CPU_MEM:-N/A}, postgres ${POSTGRES_CPU_MEM:-N/A}, es ${ES_CPU_MEM:-N/A}
*Logs*: slow queries ${SLOW_QUERIES:-N/A}, notable errors ${NOTABLE_ERRORS:-N/A}
*Bottleneck*: ${BOTTLENECK:-N/A}
*Reason*: ${FAIL_REASON:-N/A}
*Next*: ${NEXT_ACTION:-N/A}${BACKEND_HANDOFF}
$(if [ "$SLACK_UPLOAD_FILES" = "true" ]; then
  echo "(상세 표는 아래 첨부된 report.md 파일 참고 - Slack은 마크다운 표를 지원하지 않아 요약만 표시됩니다)"
else
  echo "(파일 업로드는 SLACK_UPLOAD_FILES=false로 생략했습니다. 상세 파일은 로컬 perf-runs 결과 폴더에서 확인합니다.)"
fi)
SUMMARY
)"

if [ -n "${SLACK_WEBHOOK_URL:-}" ]; then
  curl -s -X POST -H "Content-type: application/json" \
    --data "$(jq -n --arg text "$SUMMARY_TEXT" '{text: $text}')" \
    "$SLACK_WEBHOOK_URL" >/dev/null
  echo "Slack webhook summary sent."
fi

upload_file() {
  local filepath="$1"
  local title="$2"

  if [ -z "${SLACK_BOT_TOKEN:-}" ] || [ -z "${SLACK_CHANNEL:-}" ]; then
    echo "SLACK_BOT_TOKEN or SLACK_CHANNEL missing. Skip upload: $title"
    return 0
  fi
  if [ ! -f "$filepath" ]; then
    echo "File not found. Skip upload: $filepath"
    return 0
  fi
  if [ ! -s "$filepath" ]; then
    echo "File is empty. Skip upload: $filepath"
    return 0
  fi

  local filename filesize url_resp upload_url file_id complete_resp

  filename="$(basename "$filepath")"
  filesize="$(wc -c < "$filepath" | tr -d " ")"

  url_resp="$(curl -s -X POST "https://slack.com/api/files.getUploadURLExternal" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    --data-urlencode "filename=${filename}" \
    --data-urlencode "length=${filesize}")"

  if [ "$(echo "$url_resp" | jq -r ".ok")" != "true" ]; then
    echo "ERROR [1/3 getUploadURLExternal] failed for '$title': $(echo "$url_resp" | jq -r '.error')"
    echo "raw response: $url_resp"
    return 1
  fi

  upload_url="$(echo "$url_resp" | jq -r ".upload_url")"
  file_id="$(echo "$url_resp" | jq -r ".file_id")"

  local put_http_code put_response put_body
  put_response="$(curl -s -w '\n%{http_code}' -X POST "$upload_url" \
    -H "Content-Type: application/octet-stream" \
    --data-binary "@${filepath}")"
  put_http_code="$(echo "$put_response" | tail -n1)"
  put_body="$(echo "$put_response" | sed '$d')"
  if [ "$put_http_code" != "200" ]; then
    echo "ERROR [2/3 upload bytes] failed for '$title': HTTP $put_http_code"
    echo "response body: $put_body"
    return 1
  fi

  complete_resp="$(curl -s -X POST "https://slack.com/api/files.completeUploadExternal" \
    -H "Authorization: Bearer ${SLACK_BOT_TOKEN}" \
    -H "Content-Type: application/json" \
    --data "$(jq -n \
      --arg file_id "$file_id" \
      --arg title "$title" \
      --arg channel "$SLACK_CHANNEL" \
      '{files: [{id: $file_id, title: $title}], channel_id: $channel}')")"

  if [ "$(echo "$complete_resp" | jq -r ".ok")" != "true" ]; then
    echo "ERROR [3/3 completeUploadExternal] failed for '$title': $(echo "$complete_resp" | jq -r '.error')"
    echo "raw response: $complete_resp"
    return 1
  fi

  echo "Slack uploaded: $title"
  return 0
}

UPLOAD_FAIL_COUNT=0

if [ "$SLACK_UPLOAD_FILES" != "true" ]; then
  echo "Slack file upload skipped. Set SLACK_UPLOAD_FILES=true to upload report/log files."
  exit 0
fi

if ! upload_file "$REPORT_MD" "k6 report"; then
  UPLOAD_FAIL_COUNT=$((UPLOAD_FAIL_COUNT + 1))
fi

if [ "$IS_FAIL" = true ]; then
  echo "FAIL detected. Uploading investigation logs."
  if [ -n "$BACKEND_LOG" ] && ! upload_file "$BACKEND_LOG" "backend log"; then
    UPLOAD_FAIL_COUNT=$((UPLOAD_FAIL_COUNT + 1))
  fi
  if [ -n "$STATS_LOG" ] && ! upload_file "$STATS_LOG" "docker stats"; then
    UPLOAD_FAIL_COUNT=$((UPLOAD_FAIL_COUNT + 1))
  fi
  if [ -n "$SLOW_QUERY_SAMPLE" ] && ! upload_file "$SLOW_QUERY_SAMPLE" "slow query sample"; then
    UPLOAD_FAIL_COUNT=$((UPLOAD_FAIL_COUNT + 1))
  fi
  if [ -n "$NOTABLE_ERRORS_LOG" ] && ! upload_file "$NOTABLE_ERRORS_LOG" "notable errors"; then
    UPLOAD_FAIL_COUNT=$((UPLOAD_FAIL_COUNT + 1))
  fi
else
  echo "PASS. Uploading report.md only."
fi

if [ "$UPLOAD_FAIL_COUNT" -gt 0 ]; then
  echo "WARN: $UPLOAD_FAIL_COUNT file upload(s) failed. Check the ERROR logs above."
  exit 1
fi

echo "All file uploads completed."
