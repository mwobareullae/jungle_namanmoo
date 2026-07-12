import argparse
import json
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select

from app.db.models.catalog import Product
from app.db.session import SessionLocal
from app.services.review_rollup import rollup_product_review_metrics


def main() -> None:
    args = _parse_args()
    computed_at = _parse_computed_at(args.computed_at)

    with SessionLocal() as session:
        db_product_id = _resolve_product_id(session, args.product_id)
        result = rollup_product_review_metrics(
            session,
            product_id=db_product_id,
            computed_at=computed_at,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = asdict(result)
    payload["computed_at"] = result.computed_at.isoformat()
    print(json.dumps(payload, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Roll up published product reviews into product and profile metrics.",
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--full", action="store_true", help="Roll up every product review.")
    scope.add_argument(
        "--product-id",
        default=None,
        help="Roll up one external product ID, for example prod_oy_a000000144177.",
    )
    parser.add_argument(
        "--computed-at",
        default=None,
        help="Override rollup time, for example 2026-07-12T12:00:00+09:00.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Calculate and flush metrics without committing them.",
    )
    return parser.parse_args()


def _resolve_product_id(session, product_code: str | None) -> int | None:
    if product_code is None:
        return None
    db_product_id = session.scalar(
        select(Product.id).where(Product.product_code == product_code)
    )
    if db_product_id is None:
        raise SystemExit(f"Product was not found: {product_code}")
    return int(db_product_id)


def _parse_computed_at(value: str | None) -> datetime | None:
    if value is None:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


if __name__ == "__main__":
    main()
