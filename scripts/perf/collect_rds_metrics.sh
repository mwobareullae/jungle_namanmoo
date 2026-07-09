#!/usr/bin/env bash
set -euo pipefail

START_TIME_UTC="${1:?start time UTC is required}"
END_TIME_UTC="${2:?end time UTC is required}"
OUTPUT_PATH="${3:-}"

AWS_REGION="${AWS_REGION:-ap-northeast-2}"
RDS_DB_INSTANCE_IDENTIFIER="${RDS_DB_INSTANCE_IDENTIFIER:-mubarelle-db}"
CLOUDWATCH_PERIOD_SECONDS="${CLOUDWATCH_PERIOD_SECONDS:-60}"

TMP_DIR="$(mktemp -d)"
cleanup() {
  rm -rf "$TMP_DIR"
}
trap cleanup EXIT

METRICS="
CPUUtilization
FreeableMemory
DatabaseConnections
ReadIOPS
WriteIOPS
ReadLatency
WriteLatency
FreeStorageSpace
"

for metric_name in $METRICS; do
  output_file="$TMP_DIR/${metric_name}.json"
  error_file="$TMP_DIR/${metric_name}.error"
  if ! aws cloudwatch get-metric-statistics \
    --namespace AWS/RDS \
    --metric-name "$metric_name" \
    --dimensions "Name=DBInstanceIdentifier,Value=${RDS_DB_INSTANCE_IDENTIFIER}" \
    --start-time "$START_TIME_UTC" \
    --end-time "$END_TIME_UTC" \
    --period "$CLOUDWATCH_PERIOD_SECONDS" \
    --statistics Average Maximum Minimum \
    --region "$AWS_REGION" \
    --output json >"$output_file" 2>"$error_file"; then
    python3 - "$metric_name" "$error_file" >"$output_file" <<'PY'
from __future__ import annotations

import json
import sys
from pathlib import Path

metric_name = sys.argv[1]
error_path = Path(sys.argv[2])
print(
    json.dumps(
        {
            "Label": metric_name,
            "Datapoints": [],
            "error": error_path.read_text(encoding="utf-8", errors="ignore").strip(),
        },
        ensure_ascii=False,
    )
)
PY
  fi
done

python3 - "$TMP_DIR" "$START_TIME_UTC" "$END_TIME_UTC" "$AWS_REGION" "$RDS_DB_INSTANCE_IDENTIFIER" "$CLOUDWATCH_PERIOD_SECONDS" <<'PY' >"${OUTPUT_PATH:-/dev/stdout}"
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

tmp_dir = Path(sys.argv[1])
start_time = sys.argv[2]
end_time = sys.argv[3]
region = sys.argv[4]
db_instance_identifier = sys.argv[5]
period_seconds = int(sys.argv[6])

metric_defs = {
    "CPUUtilization": {"label": "CPU 사용률", "display_unit": "percent"},
    "FreeableMemory": {"label": "남은 메모리", "display_unit": "bytes_mb"},
    "DatabaseConnections": {"label": "DB 연결 수", "display_unit": "count"},
    "ReadIOPS": {"label": "Read IOPS", "display_unit": "count_per_second"},
    "WriteIOPS": {"label": "Write IOPS", "display_unit": "count_per_second"},
    "ReadLatency": {"label": "Read Latency", "display_unit": "seconds_ms"},
    "WriteLatency": {"label": "Write Latency", "display_unit": "seconds_ms"},
    "FreeStorageSpace": {"label": "남은 스토리지", "display_unit": "bytes_gb"},
}


def numeric_values(datapoints: list[dict], field: str) -> list[float]:
    values: list[float] = []
    for datapoint in datapoints:
        value = datapoint.get(field)
        if isinstance(value, (int, float)):
            values.append(float(value))
    return values


def avg(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


metrics: dict[str, dict] = {}
for metric_name, definition in metric_defs.items():
    path = tmp_dir / f"{metric_name}.json"
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raw = {"Label": metric_name, "Datapoints": [], "error": str(exc)}

    datapoints = raw.get("Datapoints") or []
    if isinstance(datapoints, list):
        datapoints = sorted(datapoints, key=lambda item: str(item.get("Timestamp", "")))
    else:
        datapoints = []

    average_values = numeric_values(datapoints, "Average")
    maximum_values = numeric_values(datapoints, "Maximum")
    minimum_values = numeric_values(datapoints, "Minimum")
    unit = next((item.get("Unit") for item in datapoints if item.get("Unit")), None)

    metrics[metric_name] = {
        **definition,
        "unit": unit,
        "datapoint_count": len(datapoints),
        "average": avg(average_values),
        "maximum": max(maximum_values) if maximum_values else None,
        "minimum": min(minimum_values) if minimum_values else None,
        "error": raw.get("error"),
        "datapoints": datapoints,
    }

payload = {
    "metadata": {
        "enabled": True,
        "db_instance_identifier": db_instance_identifier,
        "region": region,
        "start_time_utc": start_time,
        "end_time_utc": end_time,
        "period_seconds": period_seconds,
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
    },
    "metrics": metrics,
}

print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
PY
