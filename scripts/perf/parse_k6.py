#!/usr/bin/env python3
"""Parse k6 NDJSON output into a compact summary JSON."""

from __future__ import annotations

import json
import math
import re
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Iterable


def percentile(values: Iterable[float], p: float) -> float | None:
    sorted_values = sorted(values)
    if not sorted_values:
        return None
    index = max(0, math.ceil(p / 100 * len(sorted_values)) - 1)
    return sorted_values[index]


def average(values: list[float]) -> float | None:
    return sum(values) / len(values) if values else None


def parse_time(value: str) -> datetime | None:
    match = re.search(
        r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.(\d+))?(Z|[+-]\d{2}:\d{2})",
        value.strip(),
    )
    if not match:
        return None
    base, fraction, timezone = match.groups()
    normalized = base
    if fraction:
        normalized += "." + fraction[:6].ljust(6, "0")
    normalized += timezone.replace("Z", "+00:00")
    return datetime.fromisoformat(normalized)


def main() -> None:
    if len(sys.argv) != 2:
        print("usage: parse_k6.py <k6-result.ndjson>", file=sys.stderr)
        sys.exit(1)

    path = Path(sys.argv[1])
    durations_by_type: dict[str, list[float]] = defaultdict(list)
    durations_by_endpoint: dict[str, list[float]] = defaultdict(list)
    durations_all: list[float] = []
    failed_flags: list[float] = []
    request_times: list[str] = []

    with path.open("r", encoding="utf-8", errors="ignore") as file:
        for line in file:
            line = line.strip()
            if not line:
                continue
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if item.get("type") != "Point":
                continue

            metric = item.get("metric")
            data = item.get("data") or {}
            tags = data.get("tags") or {}
            value = data.get("value")
            timestamp = data.get("time")

            if metric == "http_req_duration" and isinstance(value, (int, float)):
                request_type = tags.get("type", "untagged")
                endpoint = tags.get("endpoint", "untagged")
                durations_by_type[request_type].append(float(value))
                durations_by_endpoint[endpoint].append(float(value))
                durations_all.append(float(value))
            elif metric == "http_req_failed" and isinstance(value, (int, float, bool)):
                failed_flags.append(float(value))
            elif metric == "http_reqs" and timestamp:
                request_times.append(str(timestamp))

    total_requests = len(request_times)
    failed_count = sum(1 for value in failed_flags if value == 1)
    failed_total = len(failed_flags)
    failed_rate = (failed_count / failed_total * 100) if failed_total else 0.0

    if len(request_times) >= 2:
        parsed_times = [parsed for value in request_times if (parsed := parse_time(value)) is not None]
        parsed_times.sort()
        duration_sec = (
            max((parsed_times[-1] - parsed_times[0]).total_seconds(), 1.0)
            if len(parsed_times) >= 2
            else 1.0
        )
    else:
        duration_sec = 1.0

    summary = {
        "total_requests": total_requests,
        "duration_sec": round(duration_sec, 2),
        "reqs_per_sec": round(total_requests / duration_sec, 4),
        "failed_count": failed_count,
        "failed_total": failed_total,
        "failed_rate_pct": round(failed_rate, 2),
        "http_req_duration_avg_ms": round(average(durations_all), 2) if durations_all else None,
        "http_req_duration_p50_ms": round(percentile(durations_all, 50), 2) if durations_all else None,
        "http_req_duration_p95_ms": round(percentile(durations_all, 95), 2) if durations_all else None,
        "http_req_duration_p99_ms": round(percentile(durations_all, 99), 2) if durations_all else None,
        "by_type": {},
        "by_endpoint": {},
    }

    for request_type, values in sorted(durations_by_type.items()):
        summary["by_type"][request_type] = {
            "count": len(values),
            "avg_ms": round(average(values), 2) if values else None,
            "p50_ms": round(percentile(values, 50), 2) if values else None,
            "p95_ms": round(percentile(values, 95), 2) if values else None,
            "p99_ms": round(percentile(values, 99), 2) if values else None,
        }

    for endpoint, values in sorted(durations_by_endpoint.items()):
        summary["by_endpoint"][endpoint] = {
            "count": len(values),
            "avg_ms": round(average(values), 2) if values else None,
            "p50_ms": round(percentile(values, 50), 2) if values else None,
            "p95_ms": round(percentile(values, 95), 2) if values else None,
            "p99_ms": round(percentile(values, 99), 2) if values else None,
        }

    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
