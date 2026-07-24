import argparse
import json
from dataclasses import asdict

from app.db.session import SessionLocal
from app.services.home_evidence_pick_feature_rollup import (
    rollup_home_evidence_pick_features,
)


def main() -> None:
    args = _parse_args()
    product_ids = None if args.full else tuple(args.product_id or ())
    with SessionLocal() as session:
        result = rollup_home_evidence_pick_features(
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
        description="Materialize the independent evidence-led home candidate set.",
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--full", action="store_true")
    target.add_argument("--product-id", action="append", type=int)
    parser.add_argument("--batch-size", type=int, default=500)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
