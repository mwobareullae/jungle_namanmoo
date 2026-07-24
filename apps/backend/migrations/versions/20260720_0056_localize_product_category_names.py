"""localize product category names

Revision ID: 20260720_0056
Revises: 20260719_0055
Create Date: 2026-07-20

``product_categories.name`` was seeded with the raw ``category_code`` value
(e.g. "makeup") instead of a Korean display label, so the admin product list's
카테고리 column/filter showed English codes. This backfills the 24 existing
rows with Korean labels; no schema change needed since ``name`` is already
the display-name column used by admin/product queries.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260720_0056"
down_revision: str | None = "20260719_0055"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CATEGORY_NAMES_KO = {
    "accessory": "액세서리",
    "beauty_tool": "뷰티 디바이스",
    "bodycare": "바디케어",
    "cleanser": "클렌저",
    "cleansing": "클렌징",
    "cream": "크림",
    "exfoliant": "각질 케어",
    "eye_neck": "아이·넥 케어",
    "fragrance": "프래그런스",
    "hair_body": "헤어·바디",
    "haircare": "헤어케어",
    "lotion": "로션",
    "makeup": "메이크업",
    "mask": "마스크",
    "mask_pack": "마스크팩",
    "men_allinone": "남성 올인원",
    "nail": "네일",
    "serum": "세럼",
    "set": "세트",
    "spot": "스팟 케어",
    "suncare": "선케어",
    "sunscreen": "선크림",
    "toner": "토너",
    "unknown": "미분류",
}


def upgrade() -> None:
    connection = op.get_bind()
    for category_code, name_ko in _CATEGORY_NAMES_KO.items():
        connection.execute(
            sa.text("UPDATE product_categories SET name = :name WHERE category_code = :code"),
            {"name": name_ko, "code": category_code},
        )


def downgrade() -> None:
    connection = op.get_bind()
    for category_code in _CATEGORY_NAMES_KO:
        connection.execute(
            sa.text("UPDATE product_categories SET name = :code WHERE category_code = :code"),
            {"code": category_code},
        )
