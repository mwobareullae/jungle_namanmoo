from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from app.db.session import SessionLocal
from app.services.recommendation_coarse_quality import (
    evaluate_coarse_quality_cases,
    parse_coarse_quality_cases,
    render_coarse_quality_markdown,
    summarize_coarse_quality_results,
)


DEFAULT_FIXTURE_PATH = (
    Path(__file__).parent
    / "fixtures"
    / "recommendation_coarse_top50_quality_cases.json"
)


def main() -> None:
    _configure_stdout()
    args = _parse_args()
    payload = json.loads(args.fixture.read_text(encoding="utf-8"))
    cases = parse_coarse_quality_cases(payload)
    with SessionLocal() as session:
        results = evaluate_coarse_quality_cases(
            session,
            cases,
            candidate_pool_limit=args.candidate_pool_limit,
        )

    if args.format == "json":
        report = json.dumps(
            {
                "summary": summarize_coarse_quality_results(results),
                "cases": [result.to_dict() for result in results],
            },
            ensure_ascii=False,
            indent=2,
        ) + "\n"
    else:
        report = render_coarse_quality_markdown(
            results,
            candidate_pool_limit=args.candidate_pool_limit,
        )
    if args.output is None:
        print(report, end="")
    else:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"report={args.output}")

    if args.fail_on_quality_loss and _has_quality_loss(results):
        raise SystemExit(1)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Compare legacy exact ranking with coarse top50 selection on fixed cases."
        )
    )
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE_PATH)
    parser.add_argument("--candidate-pool-limit", type=int, default=500)
    parser.add_argument("--format", choices=("markdown", "json"), default="markdown")
    parser.add_argument("--output", type=Path)
    parser.add_argument(
        "--fail-on-quality-loss",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Fail on errors, fallback, exact parity loss, or legacy top1 loss.",
    )
    return parser.parse_args()


def _has_quality_loss(results) -> bool:
    return any(
        result.error is not None
        or result.scoring_fallback
        or result.exact_value_parity is False
        or result.top1_retained is False
        for result in results
    )


def _configure_stdout() -> None:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")


if __name__ == "__main__":
    main()
