#!/usr/bin/env python3
"""Generate a Notion-friendly Markdown report for a k6 performance run."""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path


CONTAINER_ALIASES = {
    "backend": "mwobareullae-backend",
    "postgres": "mwobareullae-postgres",
    "elasticsearch": "mwobareullae-elasticsearch",
    "redis": "mwobareullae-redis",
}


def read_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="ignore")


def parse_stats_log(path: Path) -> dict:
    max_cpu: dict[str, float] = {}
    max_mem: dict[str, str] = {}
    max_conn = {"total": 0, "active": 0, "idle in transaction": 0}
    current_conn: dict[str, int] = {}

    def flush_conn() -> None:
        nonlocal current_conn
        if not current_conn:
            return
        total = sum(current_conn.values())
        max_conn["total"] = max(max_conn["total"], total)
        max_conn["active"] = max(max_conn["active"], current_conn.get("active", 0))
        max_conn["idle in transaction"] = max(
            max_conn["idle in transaction"],
            current_conn.get("idle in transaction", 0),
        )
        current_conn = {}

    for raw_line in read_text(path).splitlines():
        line = raw_line.strip()
        if line.startswith("==="):
            flush_conn()
            continue

        stats_match = re.match(r"^(\S+)\s+([\d.]+)%\s+(.+?)\s*/\s*(\S+)$", line)
        if stats_match:
            name, cpu, mem_used, _mem_limit = stats_match.groups()
            cpu_value = float(cpu)
            if cpu_value > max_cpu.get(name, -1):
                max_cpu[name] = cpu_value
                max_mem[name] = mem_used
            continue

        conn_match = re.match(r"^(.+?)\s*\|\s*(\d+)$", line)
        if conn_match:
            state, count = conn_match.groups()
            state = state.strip().lower() or "unknown"
            current_conn[state] = current_conn.get(state, 0) + int(count)

    flush_conn()
    return {"max_cpu": max_cpu, "max_mem": max_mem, "max_conn": max_conn}


def count_slow_queries(path: Path) -> int:
    return sum(1 for line in read_text(path).splitlines() if '"event":"db_slow_query"' in line)


def count_notable_errors(path: Path) -> int:
    pattern = re.compile(r" 5[0-9][0-9] |(^|\s)ERROR(\s|:|$)|Traceback|Exception|status_code\":5")
    return sum(1 for line in read_text(path).splitlines() if pattern.search(line))


def format_ms(value: float | int | None) -> str:
    if value is None:
        return "N/A"
    if value >= 1000:
        return f"{value / 1000:.2f}s"
    return f"{value:.2f}ms"


def format_rate(value: float | int | None) -> str:
    """None-safe numeric formatter."""
    if value is None:
        return "N/A"
    return f"{value}"


def load_key_values(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in read_text(path).splitlines():
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def flatten_for_table_cell(text: str, fallback: str = "N/A") -> str:
    lines = [line.strip() for line in text.strip().splitlines() if line.strip()]
    return "; ".join(lines) if lines else fallback


def row(label: str, value: str | int | float | None) -> str:
    return f"| {label} | {value if value not in (None, '') else 'N/A'} |"


def truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def auth_home_for_you_summary(enabled: str, cookie_provided: str) -> str:
    if truthy(enabled) and truthy(cookie_provided):
        return "enabled, AUTH_COOKIE provided. home_for_you_auth 실행"
    if truthy(enabled):
        return "enabled, but AUTH_COOKIE empty. home_for_you_auth 미실행"
    return "disabled. 비로그인/fallback for-you만 실행"


def max_cpu_mem(stats: dict, alias: str) -> str:
    name = CONTAINER_ALIASES[alias]
    cpu = stats["max_cpu"].get(name)
    mem = stats["max_mem"].get(name)
    if cpu is None and mem is None:
        return "N/A"
    return f"{cpu:.2f}% / {mem}" if cpu is not None else f"N/A / {mem}"


def load_json(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def format_rds_value(value: float | int | None, display_unit: str, *, stat: str, warn: bool = False) -> str:
    if value is None:
        return "-"

    numeric = float(value)
    if display_unit == "percent":
        text = f"{numeric:.2f}%"
    elif display_unit == "bytes_mb":
        text = f"{numeric / 1024 / 1024:.2f} MB"
    elif display_unit == "bytes_gb":
        text = f"{numeric / 1024 / 1024 / 1024:.2f} GB"
    elif display_unit == "seconds_ms":
        text = f"{numeric * 1000:.2f} ms"
    elif display_unit == "count":
        text = f"{numeric:.0f}"
    else:
        text = f"{numeric:.2f}"

    if warn and stat == "average":
        text = f"⚠️ {text}"
    return text


def rds_metric_rows(rds: dict, *, cpu_avg_warn_pct: float) -> str:
    metadata = rds.get("metadata") or {}
    if metadata.get("enabled") is False:
        return "| RDS CloudWatch | 비활성화 | - | - | - | - |"
    if metadata.get("error"):
        error = flatten_for_table_cell(str(metadata.get("error")), fallback="수집 실패")
        return f"| RDS CloudWatch | {error} | - | - | - | - |"

    metrics = rds.get("metrics") or {}
    definitions = [
        ("CPUUtilization", "CPU 사용률(%)"),
        ("FreeableMemory", "남은 메모리(MB)"),
        ("DatabaseConnections", "DB 연결 수"),
        ("ReadIOPS", "Read IOPS"),
        ("WriteIOPS", "Write IOPS"),
        ("ReadLatency", "Read Latency(ms)"),
        ("WriteLatency", "Write Latency(ms)"),
        ("FreeStorageSpace", "남은 스토리지(GB)"),
    ]

    rows: list[str] = []
    for metric_name, label in definitions:
        metric = metrics.get(metric_name) or {}
        display_unit = metric.get("display_unit") or ""
        average = metric.get("average")
        cpu_warn = metric_name == "CPUUtilization" and isinstance(average, (int, float)) and average > cpu_avg_warn_pct
        rows.append(
            "| {label} | {avg} | {max_} | {min_} | {count} | {error} |".format(
                label=label,
                avg=format_rds_value(average, display_unit, stat="average", warn=cpu_warn),
                max_=format_rds_value(metric.get("maximum"), display_unit, stat="maximum"),
                min_=format_rds_value(metric.get("minimum"), display_unit, stat="minimum"),
                count=metric.get("datapoint_count", 0),
                error=flatten_for_table_cell(str(metric.get("error") or ""), fallback="-"),
            )
        )
    return "\n".join(rows)


def rds_note(rds: dict) -> str:
    metadata = rds.get("metadata") or {}
    metrics = rds.get("metrics") or {}
    datapoint_counts = [
        metric.get("datapoint_count", 0)
        for metric in metrics.values()
        if isinstance(metric, dict)
    ]
    max_datapoints = max(datapoint_counts) if datapoint_counts else 0
    if metadata.get("enabled") is False:
        return "RDS CloudWatch 수집 비활성화"
    if metadata.get("error"):
        return "RDS CloudWatch 수집 실패"
    if any(isinstance(metric, dict) and metric.get("error") for metric in metrics.values()):
        return "일부 RDS 지표 수집 오류. note 열 또는 rds-metrics.log를 확인합니다."
    if max_datapoints < 3:
        return "데이터 포인트가 적어 smoke 결과는 참고용으로 봅니다."
    return "-"


def endpoint_rows(k6: dict, *, limit: int = 16) -> str:
    endpoints = k6.get("by_endpoint") or {}
    rows: list[str] = []
    sorted_items = sorted(
        endpoints.items(),
        key=lambda item: (
            -1 if item[1].get("p95_ms") is None else item[1].get("p95_ms"),
            item[0],
        ),
        reverse=True,
    )
    for endpoint, values in sorted_items[:limit]:
        rows.append(
            f"| {endpoint} | {values.get('count')} | {format_ms(values.get('avg_ms'))} | {format_ms(values.get('p50_ms'))} | {format_ms(values.get('p95_ms'))} | {format_ms(values.get('p99_ms'))} |"
        )
    return "\n".join(rows) if rows else "| N/A | N/A | N/A | N/A | N/A | N/A |"


def determine_result(
    k6: dict,
    slow_query_count: int,
    notable_error_count: int,
    sla_ms: float,
    type_sla_ms: dict[str, float] | None = None,
) -> tuple[str, str, str]:
    reasons: list[str] = []
    failed_rate = k6.get("failed_rate_pct") or 0
    overall_p95 = k6.get("http_req_duration_p95_ms")

    if failed_rate >= 1:
        reasons.append(f"http_req_failed {failed_rate}%로 1% 이상")
    if overall_p95 is not None and overall_p95 > sla_ms:
        reasons.append(f"전체 p95 {format_ms(overall_p95)}로 SLA {sla_ms / 1000:.0f}s 초과")

    worst_type = None
    worst_p95 = -1.0
    for request_type, values in (k6.get("by_type") or {}).items():
        p95 = values.get("p95_ms")
        request_sla_ms = (type_sla_ms or {}).get(request_type, sla_ms)
        if p95 is not None and p95 > worst_p95:
            worst_type = request_type
            worst_p95 = p95
        if p95 is not None and p95 > request_sla_ms:
            reasons.append(
                f"type={request_type} p95 {format_ms(p95)}로 SLA {format_ms(request_sla_ms)} 초과"
            )

    if notable_error_count > 0:
        reasons.append(f"notable error {notable_error_count}건")

    pass_fail = "❌ FAIL" if reasons else "✅ PASS"
    bottleneck = "-"
    if worst_type:
        bottleneck = f"type={worst_type} 계열 (p95 {format_ms(worst_p95)})"
        if worst_type == "search" and slow_query_count > 0:
            bottleneck += f", slow query {slow_query_count}건"
    worst_endpoint = None
    worst_endpoint_p95 = -1.0
    for endpoint, values in (k6.get("by_endpoint") or {}).items():
        p95 = values.get("p95_ms")
        if p95 is not None and p95 > worst_endpoint_p95:
            worst_endpoint = endpoint
            worst_endpoint_p95 = p95
    if worst_endpoint:
        endpoint_text = f"endpoint={worst_endpoint} (p95 {format_ms(worst_endpoint_p95)})"
        bottleneck = endpoint_text if bottleneck == "-" else f"{bottleneck}; {endpoint_text}"
    return pass_fail, "; ".join(reasons) if reasons else "-", bottleneck


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--title", default="k6 Performance Run")
    parser.add_argument("--profile", required=True)
    parser.add_argument("--git-sha", required=True)
    parser.add_argument("--server", required=True)
    parser.add_argument("--db-name", required=True)
    parser.add_argument("--data-dir", required=True)
    parser.add_argument("--data-label", required=True)
    parser.add_argument("--cart-writes", required=True)
    parser.add_argument("--auth-home-for-you", default="false")
    parser.add_argument("--auth-cookie-provided", default="false")
    parser.add_argument("--start-utc", required=True)
    parser.add_argument("--end-utc", required=True)
    parser.add_argument("--start-kst", required=True)
    parser.add_argument("--end-kst", required=True)
    parser.add_argument("--k6-summary", required=True)
    parser.add_argument("--stats-log", required=True)
    parser.add_argument("--backend-log", required=True)
    parser.add_argument("--data-counts", required=True)
    parser.add_argument("--container-health", required=True)
    parser.add_argument("--rds-metrics", required=True)
    parser.add_argument("--rds-cpu-avg-warn-pct", type=float, default=40)
    parser.add_argument("--sla-ms", type=float, default=3000)
    parser.add_argument("--catalog-search-sla-ms", type=float, default=500)
    parser.add_argument("--catalog-suggestions-sla-ms", type=float, default=200)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    k6 = json.loads(Path(args.k6_summary).read_text(encoding="utf-8"))
    stats = parse_stats_log(Path(args.stats_log))
    data_counts = load_key_values(Path(args.data_counts))
    container_health = flatten_for_table_cell(read_text(Path(args.container_health)))
    rds_metrics = load_json(Path(args.rds_metrics))
    backend_log_path = Path(args.backend_log)
    slow_query_count = count_slow_queries(backend_log_path)
    notable_error_count = count_notable_errors(backend_log_path)
    pass_fail, fail_reason, bottleneck = determine_result(
        k6,
        slow_query_count,
        notable_error_count,
        args.sla_ms,
        {
            "catalog_search": args.catalog_search_sla_ms,
            "catalog_suggestions": args.catalog_suggestions_sla_ms,
        },
    )

    by_type = k6.get("by_type") or {}

    reqs_per_sec = k6.get("reqs_per_sec")
    reqs_per_sec_display = f"{reqs_per_sec}/s" if reqs_per_sec is not None else None

    failed_rate_pct = k6.get("failed_rate_pct")
    failed_count = k6.get("failed_count")
    failed_total = k6.get("failed_total")
    failed_display = (
        f"{failed_rate_pct}% ({failed_count} out of {failed_total})"
        if failed_rate_pct is not None
        else None
    )

    report = f"""# {args.title}

## 어떤 테스트를 했는가

`{args.data_label}` 데이터 기준으로 Dev 서버의 기본 성능을 확인한 `{args.profile}` 부하테스트입니다.

k6가 MVP 핵심 API를 반복 호출합니다.

- `GET /api/health`
- `GET /api/products/popular`
- `GET /api/products/{{product_id}}`
- `GET /api/search/products`
- `GET /api/search/suggestions`
- `GET /api/home/layout`
- `GET /api/home/market-popular`
- `GET /api/home/evidence-picks`
- `GET /api/home/for-you` 비로그인/fallback 및 선택 조건
- `GET /api/home/for-you` 로그인 사용자 선택 실행 (`AUTH_HOME_FOR_YOU=true` + `AUTH_COOKIE` 필요)
- `POST /api/recommendations`
- `GET /api/recommendations/{{recommendation_id}}`
- `GET /api/products/{{product_id}}?recommendation_id=...`
- `POST /api/cart/items` 선택 실행
- `POST /api/checkout/preview` 장바구니 쓰기 선택 실행 시 함께 실행

## Overview

| 항목 | 값 |
| --- | --- |
{row("Date", args.start_kst[:10])}
{row("Git SHA", args.git_sha)}
{row("Server", args.server)}
{row("DB", args.db_name)}
{row("Data dir", args.data_dir)}
{row("Data label", args.data_label)}
{row("Profile", args.profile)}
{row("Cart writes", args.cart_writes)}
{row("Auth home for-you", auth_home_for_you_summary(args.auth_home_for_you, args.auth_cookie_provided))}
{row("Started at UTC", args.start_utc)}
{row("Ended at UTC", args.end_utc)}
{row("Started at KST", args.start_kst)}
{row("Ended at KST", args.end_kst)}
{row("SLA", f"p95 < {args.sla_ms / 1000:.0f}s")}
{row("Catalog search SLA", f"p95 < {args.catalog_search_sla_ms:.0f}ms")}
{row("Catalog suggestions SLA", f"p95 < {args.catalog_suggestions_sla_ms:.0f}ms")}

## Data Count

| 데이터 | 수량 |
| --- | --- |
{row("products", data_counts.get("products"))}
{row("product_images", data_counts.get("product_images"))}
{row("product_ingredients", data_counts.get("product_ingredients"))}
{row("ingredients", data_counts.get("ingredients"))}
{row("inventories", data_counts.get("inventories"))}
{row("brands", data_counts.get("brands"))}
{row("product_categories", data_counts.get("product_categories"))}
{row("product_prices", data_counts.get("product_prices"))}
{row("product_skin_profiles", data_counts.get("product_skin_profiles"))}
{row("search_documents", data_counts.get("search_documents"))}
{row("embedded_documents", data_counts.get("embedded_documents"))}
{row("image non_jpg", data_counts.get("image_non_jpg"))}

## k6

| 지표 | 값 |
| --- | --- |
{row("http_reqs/s", reqs_per_sec_display)}
{row("http_req_failed", failed_display)}
{row("http_req_duration avg", format_ms(k6.get("http_req_duration_avg_ms")))}
{row("http_req_duration p50", format_ms(k6.get("http_req_duration_p50_ms")))}
{row("http_req_duration p95", format_ms(k6.get("http_req_duration_p95_ms")))}
{row("http_req_duration p99", format_ms(k6.get("http_req_duration_p99_ms")))}
{row("type=fast p95", format_ms((by_type.get("fast") or {}).get("p95_ms")))}
{row("type=home p95", format_ms((by_type.get("home") or {}).get("p95_ms")))}
{row("type=search p95", format_ms((by_type.get("search") or {}).get("p95_ms")))}
{row("type=catalog_search p95", format_ms((by_type.get("catalog_search") or {}).get("p95_ms")))}
{row("type=catalog_suggestions p95", format_ms((by_type.get("catalog_suggestions") or {}).get("p95_ms")))}
{row("type=write p95", format_ms((by_type.get("write") or {}).get("p95_ms")))}

## Endpoint

| endpoint | count | avg | p50 | p95 | p99 |
| --- | --- | --- | --- | --- | --- |
{endpoint_rows(k6)}

## Server

| 항목 | 값 |
| --- | --- |
{row("backend max cpu/mem", max_cpu_mem(stats, "backend"))}
{row("postgres max cpu/mem", max_cpu_mem(stats, "postgres"))}
{row("elasticsearch max cpu/mem", max_cpu_mem(stats, "elasticsearch"))}
{row("redis max cpu/mem", max_cpu_mem(stats, "redis"))}
{row("pg_stat_activity max", stats["max_conn"]["total"])}
{row("max active", stats["max_conn"]["active"])}
{row("max idle in transaction", stats["max_conn"]["idle in transaction"])}
{row("container restart/OOM", container_health)}

## RDS 지표

| 지표 | Avg | Max | Min | datapoints | note |
| --- | --- | --- | --- | --- | --- |
{rds_metric_rows(rds_metrics, cpu_avg_warn_pct=args.rds_cpu_avg_warn_pct)}

RDS note: {rds_note(rds_metrics)}

## Logs

| 항목 | 값 |
| --- | --- |
{row("Backend log file", Path(args.backend_log).name)}
{row("Slow query count", slow_query_count)}
{row("Notable errors", "None" if notable_error_count == 0 else notable_error_count)}
{row("Slow query sample", "slow-query-sample.log")}
{row("Notable errors file", "notable-errors.log")}

## Result

| 항목 | 값 |
| --- | --- |
{row("PASS / FAIL", pass_fail)}
{row("실패 이유", fail_reason)}
{row("Bottleneck 후보", bottleneck)}
{row("Next Action", "backend.log와 slow-query-sample.log 확인 후 병목 구간 공유")}
"""

    Path(args.out).write_text(report, encoding="utf-8")
    print(f"report generated: {args.out}")


if __name__ == "__main__":
    main()
