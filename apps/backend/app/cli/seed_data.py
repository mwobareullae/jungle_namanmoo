import argparse

from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import SessionLocal
from app.services.db_seed import seed_database


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed mwobareullae CSV/JSON data into the database.")
    parser.add_argument(
        "--data-dir",
        default=settings.data_dir,
        help="Directory containing products.csv, tags.json, and other data contract files.",
    )
    args = parser.parse_args()

    with SessionLocal() as session:
        result = _seed_and_commit(session, args.data_dir)

    print(result)


def _seed_and_commit(session: Session, data_dir: str):
    result = seed_database(session, data_dir)
    session.commit()
    return result


if __name__ == "__main__":
    main()
