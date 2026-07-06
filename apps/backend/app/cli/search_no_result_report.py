import argparse

from app.db.session import SessionLocal
from app.services.search_no_result_report import (
    DEFAULT_SCAN_LIMIT,
    DEFAULT_TOP_N,
    build_search_no_result_report,
    format_json_report,
    format_markdown_report,
)


def main() -> None:
    args = _parse_args()
    with SessionLocal() as session:
        report = build_search_no_result_report(
            session,
            scan_limit=args.scan_limit,
            top_n=args.top_n,
        )

    if args.format == "json":
        print(format_json_report(report))
    else:
        print(format_markdown_report(report))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Report search no-result diagnostics and alias candidate terms.",
    )
    parser.add_argument(
        "--scan-limit",
        type=int,
        default=DEFAULT_SCAN_LIMIT,
        help="Number of recent recommendation runs to scan.",
    )
    parser.add_argument(
        "--top-n",
        type=int,
        default=DEFAULT_TOP_N,
        help="Number of alias candidate terms to include.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "json"),
        default="markdown",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()
