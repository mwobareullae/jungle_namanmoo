from __future__ import annotations

import argparse
import json
from pathlib import Path

import httpx

from app.services.catalog_search_quality import (
    evaluate_catalog_search_cases,
    render_catalog_quality_markdown,
)


DEFAULT_FIXTURE_PATH = Path("tests/catalog_search_quality_cases.json")
DEFAULT_JSON_OUTPUT = Path("catalog-search-quality-report.json")
DEFAULT_MARKDOWN_OUTPUT = Path("catalog-search-quality-report.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="일반 상품 검색 품질 정답지를 실제 API로 평가합니다.")
    parser.add_argument("--base-url", default="http://backend:8000/api")
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--json-output", type=Path, default=DEFAULT_JSON_OUTPUT)
    parser.add_argument("--markdown-output", type=Path, default=DEFAULT_MARKDOWN_OUTPUT)
    parser.add_argument("--timeout-seconds", type=float, default=10.0)
    parser.add_argument("--include-blocked", action="store_true")
    parser.add_argument(
        "--fail-on-threshold",
        action=argparse.BooleanOptionalAction,
        default=True,
    )
    args = parser.parse_args()

    fixture = json.loads(args.fixture.read_text(encoding="utf-8"))
    with httpx.Client(base_url=f"{args.base_url.rstrip('/')}/", timeout=args.timeout_seconds) as client:
        report = evaluate_catalog_search_cases(
            client,
            fixture,
            include_blocked=args.include_blocked,
        )

    args.json_output.parent.mkdir(parents=True, exist_ok=True)
    args.markdown_output.parent.mkdir(parents=True, exist_ok=True)
    args.json_output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    args.markdown_output.write_text(
        render_catalog_quality_markdown(report),
        encoding="utf-8",
    )
    print(json.dumps(report["summary"], ensure_ascii=False))
    if args.fail_on_threshold and not report["summary"]["overall_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
