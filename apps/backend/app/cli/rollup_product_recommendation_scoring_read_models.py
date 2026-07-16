import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.recommendation_scoring_read_model_rollup import (
    rollup_product_recommendation_scoring_read_models,
)


def main() -> None:
    args = _parse_args()
    product_ids = None if args.full else tuple(args.product_id or ())
    with SessionLocal() as session:
        result = rollup_product_recommendation_scoring_read_models(
            session,
            product_ids=product_ids,
            batch_size=args.batch_size,
        )
        if args.dry_run:
            session.rollback()
        else:
            session.commit()

    payload = asdict(result)
    payload["computed_at"] = result.computed_at.isoformat()
    payload["dry_run"] = args.dry_run
    print(json.dumps(payload, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Roll up compact product recommendation scoring read models.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--full", action="store_true", help="Roll up every product.")
    target.add_argument(
        "--product-id",
        action="append",
        type=int,
        help="Roll up one product database ID. Repeat for multiple products.",
    )
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
