import argparse
import json

from sqlalchemy import select

from app.db.models.auth import User
from app.db.session import SessionLocal
from app.services.auth_security import normalize_email


ROLE_VALUES = ("USER", "ADMIN")


def main() -> None:
    args = _parse_args()
    email = normalize_email(args.email)

    with SessionLocal() as session:
        user = session.execute(select(User).where(User.email == email)).scalar_one_or_none()
        if user is None:
            raise SystemExit(f"User not found: {email}")

        previous_role = user.role
        user.role = args.role
        session.commit()

        result = {
            "email": user.email,
            "previous_role": previous_role,
            "role": user.role,
        }

    print(json.dumps(result, ensure_ascii=False))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Set an existing local user's role for admin API testing.",
    )
    parser.add_argument("--email", required=True, help="Existing user's email address.")
    parser.add_argument("--role", required=True, choices=ROLE_VALUES, help="Role to assign.")
    return parser.parse_args()


if __name__ == "__main__":
    main()
