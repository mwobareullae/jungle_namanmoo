#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
from pathlib import Path
from typing import Callable
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


class PublishError(RuntimeError):
    pass


def read_candidate_payload(path: Path) -> dict[str, list[dict[str, object]]]:
    with path.open(encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.DictReader(handle))
    candidates: list[dict[str, object]] = []
    for row in rows:
        candidates.append(
            {
                **row,
                "abstract_available": _bool_value(row.get("abstract_available", "false")),
                "score_eligible": False,
                "review_status": "candidate_unverified",
            }
        )
    return {"candidates": candidates}


def publish_candidates(
    *,
    endpoint: str,
    token: str,
    payload: dict[str, list[dict[str, object]]],
    timeout_seconds: float = 30,
    max_attempts: int = 3,
    opener: Callable[..., object] = urlopen,
) -> dict[str, object]:
    if not endpoint.strip():
        raise PublishError("EVIDENCE_INGEST_URL이 설정되지 않았습니다.")
    if not token:
        raise PublishError("EVIDENCE_INGEST_TOKEN이 설정되지 않았습니다.")
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = Request(
        endpoint,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/json",
            "X-Evidence-Ingest-Token": token,
        },
    )
    last_error: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            with opener(request, timeout=timeout_seconds) as response:
                response_body = response.read().decode("utf-8")
            parsed = json.loads(response_body)
            if not isinstance(parsed, dict):
                raise PublishError("후보 적재 API 응답이 객체가 아닙니다.")
            return parsed
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")
            if exc.code < 500 or attempt == max_attempts:
                raise PublishError(f"후보 적재 API 오류 {exc.code}: {detail}") from exc
            last_error = exc
        except (URLError, TimeoutError) as exc:
            if attempt == max_attempts:
                raise PublishError(f"후보 적재 API 연결 실패: {exc}") from exc
            last_error = exc
        time.sleep(attempt)
    raise PublishError(f"후보 적재 실패: {last_error}")


def _bool_value(value: str) -> bool:
    return value.strip().casefold() in {"1", "true", "yes", "y"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="신규 논문 후보 CSV를 영구 보관 API로 전송합니다.")
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--endpoint", default=os.getenv("EVIDENCE_INGEST_URL", ""))
    parser.add_argument("--token", default=os.getenv("EVIDENCE_INGEST_TOKEN", ""))
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = read_candidate_payload(args.input)
    if not payload["candidates"]:
        print("신규 논문 후보 0건: DB 적재를 건너뜁니다.")
        return 0
    try:
        result = publish_candidates(
            endpoint=args.endpoint,
            token=args.token,
            payload=payload,
        )
    except PublishError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(
        "후보 DB 적재 완료: "
        f"received={result.get('received', 0)} "
        f"inserted={result.get('inserted', 0)} "
        f"refreshed={result.get('refreshed', 0)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
