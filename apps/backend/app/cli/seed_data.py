import argparse
import sys

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal, engine
from app.services.admin.ingredient_mapping_pending_groups import (
    PendingIngredientGroupsRefreshError,
    refresh_pending_ingredient_mapping_groups,
)
from app.services.db_seed import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mwobareullae CSV/JSON data into the database.")
    parser.add_argument(
        "--data-dir",
        default=settings.data_dir,
        help="Directory containing products CSV data, tags.json, and other data contract files.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = _seed_and_commit(session, args.data_dir)

    try:
        refresh_pending_ingredient_mapping_groups(engine)
    except PendingIngredientGroupsRefreshError as exc:
        print(result, file=sys.stderr)
        raise SystemExit(
            "Seed data was committed, but ingredient mapping pending-group refresh failed. "
            "Run: python -m app.cli.refresh_ingredient_mapping_pending_groups"
        ) from exc

    print(result)


def _seed_and_commit(session: Session, data_dir: str):
    result = seed_database(session, data_dir)
    session.commit()
    return result


if __name__ == "__main__":
    main()
